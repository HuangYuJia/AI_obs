"""
OBS Virtual Try-On Server
Connects to OBS via WebSocket, captures live stream, and applies AI virtual try-on.
"""

import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Configure proxy from env
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
HTTPS_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
if HTTP_PROXY:
    os.environ["HTTP_PROXY"] = HTTP_PROXY
if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# App initialization
# ──────────────────────────────────────────────
app = FastAPI(title="OBS Virtual Try-On", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
OBS_HOST = os.getenv("OBS_HOST", "localhost")
OBS_PORT = int(os.getenv("OBS_PORT", "4455"))
OBS_PASSWORD = os.getenv("OBS_PASSWORD", "")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8443"))

# Directories
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
CLOTHING_DIR = BASE_DIR / "clothing"

for d in [UPLOAD_DIR, OUTPUT_DIR, CLOTHING_DIR]:
    d.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# State management
# ──────────────────────────────────────────────
class AppState:
    def __init__(self):
        self.obs_connected = False
        self.is_live = False
        self.is_generating = False
        self.current_mode = "tryon"  # tryon, swap, generate
        self.current_model = "lucy-vton-3"
        self.current_prompt = ""
        self.current_clothing: Optional[str] = None
        self.current_person: Optional[str] = None
        self.generated_image: Optional[str] = None
        self.websocket_clients: list[WebSocket] = []
        self.frame_count = 0
        self.start_time: Optional[float] = None
        # VTON model placeholder - replace with actual model
        self.vton_model = None

    def get_status(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        return {
            "obs_connected": self.obs_connected,
            "is_live": self.is_live,
            "is_generating": self.is_generating,
            "current_mode": self.current_mode,
            "current_model": self.current_model,
            "current_prompt": self.current_prompt,
            "current_clothing": self.current_clothing,
            "current_person": self.current_person,
            "generated_image": self.generated_image,
            "timecode": f"{minutes:02d}:{seconds:02d}",
            "frame_count": self.frame_count,
            "connected_clients": len(self.websocket_clients),
        }

state = AppState()

# ──────────────────────────────────────────────
# OBS WebSocket integration (optional)
# ──────────────────────────────────────────────
try:
    import obsws_python as obsws
    OBS_SDK_AVAILABLE = True
except ImportError:
    OBS_SDK_AVAILABLE = False

import websocket
import hashlib
import base64

OBS_AVAILABLE = True  # We always have WebSocket support


class OBSController:
    """Manages OBS WebSocket connection with proper authentication."""

    def __init__(self):
        self.ws = None
        self.connected = False
        self._request_id = 0
        self._responses = {}

    def _next_id(self):
        self._request_id += 1
        return str(self._request_id)

    def _send_request(self, request_type: str, data: dict = None) -> dict:
        """Send a request to OBS and wait for response."""
        if not self.ws or not self.connected:
            raise Exception("Not connected to OBS")

        req_id = self._next_id()
        message = {
            "op": 6,  # Request
            "d": {
                "requestType": request_type,
                "requestId": req_id,
                "requestData": data or {}
            }
        }

        self.ws.send(json.dumps(message))

        # Wait for response
        while True:
            try:
                response = self.ws.recv()
                msg = json.loads(response)

                if msg.get("op") == 7:  # RequestResponse
                    if msg["d"]["requestId"] == req_id:
                        result = msg["d"]
                        if result.get("requestStatus", {}).get("result"):
                            return result.get("responseData", {})
                        else:
                            error = result.get("requestStatus", {}).get("comment", "Unknown error")
                            raise Exception(error)
            except websocket.WebSocketTimeoutException:
                raise Exception("Timeout waiting for OBS response")

    def connect(self, host: str, port: int, password: str) -> bool:
        try:
            # Close existing connection if any
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
                self.connected = False

            logger.info(f"Connecting to OBS WebSocket at {host}:{port}")

            # Connect to OBS WebSocket
            self.ws = websocket.create_connection(
                f"ws://{host}:{port}",
                timeout=10
            )

            # Receive Hello message
            hello = json.loads(self.ws.recv())
            logger.info(f"OBS WebSocket version: {hello['d'].get('obsWebSocketVersion', 'unknown')}")

            # Check if authentication is required
            auth_info = hello["d"].get("authentication", {})

            if auth_info and password:
                # Perform authentication
                challenge = auth_info.get("challenge", "")
                salt = auth_info.get("salt", "")

                # Calculate authentication string
                secret = base64.b64encode(
                    hashlib.sha256((password + salt).encode()).digest()
                ).decode()

                auth_response = base64.b64encode(
                    hashlib.sha256((secret + challenge).encode()).digest()
                ).decode()

                identify = {
                    "op": 1,
                    "d": {
                        "rpcVersion": 1,
                        "authentication": auth_response
                    }
                }
            else:
                # No authentication needed
                identify = {
                    "op": 1,
                    "d": {
                        "rpcVersion": 1
                    }
                }

            self.ws.send(json.dumps(identify))

            # Receive Identified message
            response = json.loads(self.ws.recv())

            if response.get("op") == 2:  # Identified
                logger.info("Successfully connected to OBS")
                self.connected = True
                state.obs_connected = True
                return True
            else:
                error_msg = response.get("d", {}).get("error", "Authentication failed")
                logger.error(f"OBS authentication failed: {error_msg}")
                self.ws.close()
                self.ws = None
                return False

        except Exception as e:
            logger.error(f"Failed to connect to OBS: {e}")
            self.connected = False
            state.obs_connected = False
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
            return False

    def disconnect(self):
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        self.ws = None
        self.connected = False
        state.obs_connected = False

    def get_current_scene(self) -> Optional[str]:
        if not self.connected:
            return None
        try:
            result = self._send_request("GetCurrentProgramScene")
            return result.get("currentProgramSceneName")
        except Exception as e:
            logger.error(f"Error getting current scene: {e}")
            return None

    def get_screenshot(self, scene_name: str = None) -> Optional[str]:
        """Capture current OBS output as base64 image."""
        if not self.connected:
            return None
        try:
            if not scene_name:
                scene_name = self.get_current_scene()
            if not scene_name:
                return None

            result = self._send_request(
                "GetSourceScreenshot",
                {
                    "sourceName": scene_name,
                    "imageFormat": "png",
                    "imageWidth": 1920,
                    "imageHeight": 1080,
                    "imageCompressionQuality": 80
                }
            )
            # Remove data:image/png;base64, prefix if present
            img_data = result.get("imageData", "")
            if img_data.startswith("data:"):
                img_data = img_data.split(",", 1)[1]
            return img_data
        except Exception as e:
            logger.error(f"Error capturing screenshot: {e}")
            return None

    def set_virtual_camera_output(self, enabled: bool):
        if not self.connected:
            return False
        try:
            if enabled:
                self._send_request("StartVirtualCam")
            else:
                self._send_request("StopVirtualCam")
            return True
        except Exception as e:
            logger.error(f"Error toggling virtual camera: {e}")
            return False

obs_controller = OBSController()

# ──────────────────────────────────────────────
# VTON (Virtual Try-On) Model Integration
# ──────────────────────────────────────────────
class VTONProcessor:
    """
    Virtual Try-On processor using Gradio API.
    Uses IDM-VTON model on Hugging Face Spaces via HTTP API.
    """

    def __init__(self):
        self.space_url = "https://yisol-idm-vton.hf.space"
        self.client = None
        self.hf_token = os.getenv("HUGGINGFACE_TOKEN")

    def load_model(self):
        logger.info(f"Connecting to Gradio space: {self.space_url}")
        try:
            from gradio_client import Client
            self.client = Client(self.space_url, ssl_verify=False, verbose=False)
            logger.info("Connected to Gradio space successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Gradio space: {e}")
            self.client = None

    def _upload_file(self, file_path: str) -> str:
        """Upload file to Space and return remote path."""
        import requests as req
        upload_url = f"{self.space_url}/upload"
        filename = os.path.basename(file_path)

        with open(file_path, 'rb') as f:
            r = req.post(
                upload_url,
                files={'files': (filename, f, 'image/png')},
                verify=False,
                timeout=30
            )
        if r.status_code == 200:
            return r.json()[0]
        raise Exception(f"Upload failed: {r.status_code}")

    def _make_filedata(self, remote_path: str, local_path: str, url_prefix: str = None) -> dict:
        """Create FileData dict for Gradio API."""
        data = {
            'path': remote_path,
            'url': None,
            'size': os.path.getsize(local_path),
            'orig_name': os.path.basename(local_path),
            'mime_type': 'image/png',
            'is_stream': False,
            'meta': {'_type': 'gradio.FileData'}
        }
        if url_prefix:
            data['url'] = f"{url_prefix}/file={remote_path}"
        return data

    def generate(self, person_image: Image.Image, clothing_image: Image.Image, prompt: str = "") -> Image.Image:
        """Generate virtual try-on result."""
        import requests as req

        # Save images to temp files
        person_path = str(UPLOAD_DIR / "temp_person.png")
        clothing_path = str(CLOTHING_DIR / "temp_clothing.png")
        person_image.save(person_path, "PNG")
        clothing_image.save(clothing_path, "PNG")

        logger.info("Uploading images to Space...")
        person_remote = self._upload_file(person_path)
        clothing_remote = self._upload_file(clothing_path)
        logger.info(f"Uploaded: person={person_remote}, clothing={clothing_remote}")

        # Build FileData
        person_file = self._make_filedata(person_remote, person_path)
        clothing_file = self._make_filedata(clothing_remote, clothing_path, self.space_url)
        editor = {'background': person_file, 'layers': [], 'composite': person_file}

        # Call API via queue
        session_hash = f"gen_{int(time.time())}"
        payload = {
            'data': [editor, clothing_file, prompt or "a photo of clothing", True, False, 30, 42],
            'fn_index': 0,
            'session_hash': session_hash
        }

        logger.info("Calling API via queue...")
        r = req.post(f"{self.space_url}/queue/join", json=payload, verify=False, timeout=30)
        if r.status_code != 200:
            raise Exception(f"Queue join failed: {r.status_code}")

        event_id = r.json()['event_id']
        logger.info(f"Event ID: {event_id}")

        # Wait for result
        start = time.time()
        while time.time() - start < 180:
            r = req.get(
                f"{self.space_url}/queue/data?session_hash={session_hash}",
                verify=False, timeout=60, stream=True
            )

            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode('utf-8')
                if not line.startswith('data:'):
                    continue

                data = json.loads(line[5:])
                msg = data.get('msg')

                if msg == 'process_completed':
                    success = data.get('success', False)
                    output = data.get('output', {})

                    if success and output.get('data'):
                        result_data = output['data']
                        if result_data and len(result_data) > 0:
                            result = result_data[0]
                            if isinstance(result, dict):
                                result_url = result.get('url') or result.get('path')
                                if result_url:
                                    if result_url.startswith('/'):
                                        result_url = f"{self.space_url}/file={result_url}"
                                    img_r = req.get(result_url, verify=False, timeout=60)
                                    return Image.open(io.BytesIO(img_r.content))
                            elif isinstance(result, str) and os.path.exists(result):
                                return Image.open(result)

                    raise Exception("Space returned empty result - service may be temporarily unavailable")

                elif msg == 'error':
                    raise Exception(f"Space error: {data}")

        raise Exception("Timeout waiting for result")

    def process(
        self,
        person_image: Image.Image,
        clothing_image: Image.Image,
        prompt: str = "",
    ) -> Image.Image:
        """Apply virtual try-on using HTTP API."""
        # Ensure images are RGB
        person_image = person_image.convert("RGB")
        clothing_image = clothing_image.convert("RGB")

        # Resize images to reasonable dimensions
        max_size = 768
        if max(person_image.size) > max_size:
            person_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if max(clothing_image.size) > max_size:
            clothing_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        return self.generate(person_image, clothing_image, prompt)

vton_processor = VTONProcessor()

# ──────────────────────────────────────────────
# WebSocket for real-time updates
# ──────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.websocket_clients.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(state.websocket_clients)}")

    try:
        # Send initial state
        await websocket.send_json({"type": "status", "data": state.get_status()})

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "get_status":
                await websocket.send_json({"type": "status", "data": state.get_status()})

    except WebSocketDisconnect:
        state.websocket_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(state.websocket_clients)}")


async def broadcast_update(message_type: str, data: dict):
    """Broadcast update to all connected WebSocket clients."""
    message = json.dumps({"type": message_type, "data": data})
    disconnected = []
    for client in state.websocket_clients:
        try:
            await client.send_text(message)
        except:
            disconnected.append(client)
    for client in disconnected:
        state.websocket_clients.remove(client)

# ──────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>OBS Virtual Try-On</h1><p>Static files not found.</p>")


@app.get("/api/status")
async def get_status():
    """Get current application state."""
    return state.get_status()


@app.post("/api/obs/connect")
async def connect_obs(host: str = OBS_HOST, port: int = OBS_PORT, password: str = OBS_PASSWORD):
    """Connect to OBS WebSocket."""
    logger.info(f"API: Connecting to OBS at {host}:{port}")
    try:
        success = obs_controller.connect(host, port, password)
        if success:
            await broadcast_update("obs_status", {"connected": True})
            logger.info("API: OBS connection successful")
            return {"status": "connected"}
        else:
            logger.error("API: OBS connection failed")
            raise HTTPException(status_code=500, detail="Failed to connect to OBS")
    except Exception as e:
        logger.error(f"API: OBS connection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/obs/disconnect")
async def disconnect_obs():
    """Disconnect from OBS."""
    obs_controller.disconnect()
    await broadcast_update("obs_status", {"connected": False})
    return {"status": "disconnected"}


@app.get("/api/obs/scene")
async def get_current_scene():
    """Get current OBS scene name."""
    scene = obs_controller.get_current_scene()
    if scene:
        return {"scene": scene}
    raise HTTPException(status_code=404, detail="No active scene or not connected")


@app.get("/api/obs/screenshot")
async def get_obs_screenshot():
    """Capture OBS screenshot as base64 PNG."""
    screenshot = obs_controller.get_screenshot()
    if screenshot:
        return {"image": screenshot, "timestamp": time.time()}
    raise HTTPException(status_code=500, detail="Failed to capture screenshot")


@app.post("/api/clothing/upload")
async def upload_clothing(file: UploadFile = File(...)):
    """Upload a clothing image for virtual try-on."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    file_id = str(uuid.uuid4())[:8]
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    filename = f"clothing_{file_id}.{ext}"
    filepath = CLOTHING_DIR / filename

    content = await file.read()
    filepath.write_bytes(content)

    state.current_clothing = str(filepath)
    await broadcast_update("clothing_updated", {"path": str(filepath), "filename": filename})

    return {
        "status": "uploaded",
        "filename": filename,
        "path": str(filepath),
        "size": len(content),
    }


@app.post("/api/person/upload")
async def upload_person(file: UploadFile = File(...)):
    """Upload a person image for virtual try-on."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    file_id = str(uuid.uuid4())[:8]
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    filename = f"person_{file_id}.{ext}"
    filepath = UPLOAD_DIR / filename

    content = await file.read()
    filepath.write_bytes(content)

    state.current_person = str(filepath)
    await broadcast_update("person_updated", {"path": str(filepath), "filename": filename})

    return {
        "status": "uploaded",
        "filename": filename,
        "path": str(filepath),
        "size": len(content),
    }


class GenerateRequest(BaseModel):
    prompt: str = ""
    mode: str = "tryon"
    model: str = "lucy-vton-3"


@app.post("/api/generate")
async def generate(request: GenerateRequest):
    """Generate virtual try-on result using AI API."""
    if not state.current_clothing:
        raise HTTPException(status_code=400, detail="请先上传服装图片")

    state.is_generating = True
    state.current_mode = request.mode
    state.current_model = request.model
    state.current_prompt = request.prompt

    await broadcast_update("generation_started", {"mode": request.mode})

    try:
        # Load clothing image
        clothing_img = Image.open(state.current_clothing)

        # Get person image: try OBS screenshot first, then uploaded image
        person_img = None

        # Method 1: Get from OBS live stream
        if obs_controller.connected:
            screenshot_b64 = obs_controller.get_screenshot()
            if screenshot_b64:
                try:
                    # Remove data:image prefix if present
                    if screenshot_b64.startswith("data:"):
                        screenshot_b64 = screenshot_b64.split(",", 1)[1]
                    screenshot_bytes = base64.b64decode(screenshot_b64)
                    person_img = Image.open(io.BytesIO(screenshot_bytes))
                    logger.info("Using OBS screenshot as person image")
                except Exception as e:
                    logger.warning(f"Failed to decode OBS screenshot: {e}")

        # Method 2: Use uploaded person image
        if person_img is None and state.current_person and Path(state.current_person).exists():
            person_img = Image.open(state.current_person)
            logger.info("Using uploaded person image")

        # Method 3: No person image available
        if person_img is None:
            raise Exception("无法获取人物图片：请连接 OBS 直播或上传人物照片")

        # Process with VTON model (API only, no fallback)
        result_img = vton_processor.process(
            person_img, clothing_img, request.prompt
        )

        # Save result
        output_id = str(uuid.uuid4())[:8]
        output_path = OUTPUT_DIR / f"result_{output_id}.png"
        result_img.save(str(output_path))

        state.generated_image = str(output_path)
        state.is_generating = False

        # Convert to base64 for response
        buffered = io.BytesIO()
        result_img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()

        await broadcast_update("generation_complete", {
            "image": img_base64,
            "path": str(output_path),
        })

        return {
            "status": "success",
            "image": img_base64,
            "path": str(output_path),
        }

    except Exception as e:
        state.is_generating = False
        logger.error(f"Generation error: {e}")
        await broadcast_update("generation_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# Image Search API (Bing)
# ──────────────────────────────────────────────
BING_SEARCH_KEY = os.getenv("BING_SEARCH_KEY", "")

@app.get("/api/search/images")
async def search_images(query: str = "COSPLAY服装", count: int = 8):
    """Search for clothing images using Bing Image Search API."""
    if not BING_SEARCH_KEY:
        # Return placeholder images if no API key
        logger.warning("Bing Search API key not configured, returning placeholders")
        return {
            "status": "no_api_key",
            "images": _get_placeholder_images(query, count),
            "message": "请配置 BING_SEARCH_KEY 以启用真实图片搜索"
        }

    try:
        # Call Bing Image Search API
        search_url = "https://api.bing.microsoft.com/v7.0/images/search"
        headers = {"Ocp-Apim-Subscription-Key": BING_SEARCH_KEY}
        params = {
            "q": query,
            "count": count,
            "imageType": "Photo",
            "safeSearch": "Moderate",
            "mkt": "zh-CN"
        }

        logger.info(f"Searching images: {query}")
        response = requests.get(search_url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            images = []
            for item in data.get("value", []):
                images.append({
                    "url": item.get("contentUrl", ""),
                    "thumbnail": item.get("thumbnailUrl", ""),
                    "title": item.get("name", ""),
                    "source": item.get("hostPageDomainFriendlyName", ""),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                })
            return {"status": "success", "images": images}
        else:
            logger.error(f"Bing API error: {response.status_code}")
            return {"status": "error", "images": _get_placeholder_images(query, count), "message": f"搜索失败: {response.status_code}"}

    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"status": "error", "images": _get_placeholder_images(query, count), "message": str(e)}


def _get_placeholder_images(query: str, count: int) -> list:
    """Generate placeholder images when API is not available."""
    images = []
    for i in range(count):
        seed = f"{query}_{i}"
        images.append({
            "url": f"https://picsum.photos/seed/{seed}/400/560",
            "thumbnail": f"https://picsum.photos/seed/{seed}/200/280",
            "title": f"{query} {i+1}",
            "source": "示例图片",
            "width": 400,
            "height": 560,
        })
    return images


@app.post("/api/obs/start-virtual-cam")
async def start_virtual_camera():
    """Start OBS Virtual Camera output."""
    success = obs_controller.set_virtual_camera_output(True)
    if success:
        state.is_live = True
        state.start_time = time.time()
        await broadcast_update("live_status", {"is_live": True})
        return {"status": "started"}
    raise HTTPException(status_code=500, detail="Failed to start virtual camera")


@app.post("/api/obs/stop-virtual-cam")
async def stop_virtual_camera():
    """Stop OBS Virtual Camera output."""
    success = obs_controller.set_virtual_camera_output(False)
    if success:
        state.is_live = False
        await broadcast_update("live_status", {"is_live": False})
        return {"status": "stopped"}
    raise HTTPException(status_code=500, detail="Failed to stop virtual camera")


@app.get("/api/image/{image_type}/{filename}")
async def get_image(image_type: str, filename: str):
    """Serve uploaded/generated images."""
    if image_type == "clothing":
        path = CLOTHING_DIR / filename
    elif image_type == "person":
        path = UPLOAD_DIR / filename
    elif image_type == "output":
        path = OUTPUT_DIR / filename
    else:
        raise HTTPException(status_code=400, detail="Invalid image type")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(str(path))


@app.delete("/api/clothing/{filename}")
async def delete_clothing(filename: str):
    """Delete a clothing image."""
    path = CLOTHING_DIR / filename
    if path.exists():
        path.unlink()
        if state.current_clothing == str(path):
            state.current_clothing = None
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/api/clothing/list")
async def list_clothing():
    """List all uploaded clothing images."""
    files = []
    for f in CLOTHING_DIR.iterdir():
        if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
            files.append({
                "filename": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return {"files": sorted(files, key=lambda x: x["modified"], reverse=True)}


@app.get("/api/stream")
async def stream_frames():
    """SSE endpoint for streaming processed frames."""
    async def generate():
        while True:
            if state.generated_image and Path(state.generated_image).exists():
                img = Image.open(state.generated_image)
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG", quality=80)
                img_base64 = base64.b64encode(buffered.getvalue()).decode()
                yield f"data: {json.dumps({'frame': img_base64, 'timestamp': time.time()})}\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ──────────────────────────────────────────────
# Mount static files
# ──────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ──────────────────────────────────────────────
# Startup / Shutdown
# ──────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info(f"Server starting on port {SERVER_PORT}")
    logger.info(f"OBS WebSocket: {OBS_HOST}:{OBS_PORT}")
    logger.info(f"Static dir: {STATIC_DIR}")

    # Try to connect to OBS on startup
    if OBS_AVAILABLE:
        try:
            obs_controller.connect(OBS_HOST, OBS_PORT, OBS_PASSWORD)
        except:
            logger.warning("Could not connect to OBS on startup")


@app.on_event("shutdown")
async def shutdown():
    obs_controller.disconnect()
    logger.info("Server shutting down")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=SERVER_PORT,
        reload=True,
        log_level="info",
    )
