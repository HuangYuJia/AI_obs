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
load_dotenv(override=True)

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
CLOTHING_DIR = BASE_DIR / "clothing"
UPLOAD_DIR = BASE_DIR / "uploads"

for d in [CLOTHING_DIR, UPLOAD_DIR]:
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


# ──────────────────────────────────────────────
# WebSocket for Lucy VTON real-time streaming
# ──────────────────────────────────────────────
@app.websocket("/ws/vton")
async def websocket_vton(websocket: WebSocket):
    """WebSocket endpoint for real-time virtual try-on via Lucy VTON WebRTC."""
    from lucy_realtime import lucy_realtime

    await websocket.accept()
    logger.info("VTON WebSocket client connected")

    if not lucy_realtime.is_configured():
        await websocket.send_json({"type": "error", "message": "Lucy VTON realtime not configured (missing SDK or API key)"})
        await websocket.close()
        return

    ws_frame_count = 0
    sent_frame_count = 0

    async def send_processed_frame(frame_img: Image.Image):
        """Callback: send processed frame back to frontend."""
        nonlocal sent_frame_count
        sent_frame_count += 1
        try:
            buffered = io.BytesIO()
            frame_img.save(buffered, format="PNG")
            frame_b64 = base64.b64encode(buffered.getvalue()).decode()
            await websocket.send_json({"type": "frame", "image": frame_b64})
            if sent_frame_count == 1 or sent_frame_count % 10 == 0:
                logger.info(f"Sent processed frame #{sent_frame_count} to frontend")
        except Exception as e:
            if sent_frame_count <= 2:
                logger.error(f"Error sending processed frame: {e}")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "start":
                # Start a new VTON session with clothing
                clothing_path = data.get("clothing", "")
                prompt = data.get("prompt", "try on")

                # Load clothing image bytes
                image_bytes = None
                if clothing_path:
                    full_path = Path(clothing_path)
                    if not full_path.is_absolute():
                        full_path = CLOTHING_DIR / clothing_path
                    if full_path.exists():
                        image_bytes = full_path.read_bytes()
                    else:
                        logger.warning(f"Clothing file not found: {full_path}")

                connected = await lucy_realtime.connect(
                    on_frame=send_processed_frame,
                    prompt=prompt,
                    image_bytes=image_bytes,
                )

                if connected:
                    await websocket.send_json({"type": "connected", "message": "Lucy VTON realtime session started"})
                else:
                    await websocket.send_json({"type": "error", "message": "Failed to connect to Lucy VTON realtime"})

            elif msg_type == "frame":
                # Push OBS frame to WebRTC stream
                ws_frame_count += 1
                if ws_frame_count == 1 or ws_frame_count % 30 == 0:
                    logger.info(f"VTON WS received frame #{ws_frame_count}")
                frame_b64 = data.get("image", "")
                if frame_b64.startswith("data:"):
                    frame_b64 = frame_b64.split(",", 1)[1]
                frame_bytes = base64.b64decode(frame_b64)
                frame_img = Image.open(io.BytesIO(frame_bytes))
                await lucy_realtime.push_frame(frame_img)

            elif msg_type == "update":
                # Update clothing mid-session
                prompt = data.get("prompt")
                clothing_path = data.get("clothing")
                image_bytes = None
                if clothing_path:
                    full_path = Path(clothing_path)
                    if not full_path.is_absolute():
                        full_path = CLOTHING_DIR / clothing_path
                    if full_path.exists():
                        image_bytes = full_path.read_bytes()

                await lucy_realtime.update_clothing(prompt=prompt, image_bytes=image_bytes)
                await websocket.send_json({"type": "updated", "message": "Clothing updated"})

            elif msg_type == "stop":
                await lucy_realtime.disconnect()
                await websocket.send_json({"type": "disconnected", "message": "Session ended"})
                break

    except WebSocketDisconnect:
        logger.info("VTON WebSocket client disconnected")
    except Exception as e:
        logger.error(f"VTON WebSocket error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if lucy_realtime.is_connected:
            await lucy_realtime.disconnect()


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
    """Upload a person/clothing image for current try-on (not added to gallery)."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    file_id = str(uuid.uuid4())[:8]
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    filename = f"person_{file_id}.{ext}"
    filepath = UPLOAD_DIR / filename

    content = await file.read()
    filepath.write_bytes(content)

    return {
        "status": "uploaded",
        "filename": filename,
        "path": str(filepath),
        "size": len(content),
    }


# ──────────────────────────────────────────────
# Lucy Real-Time API Endpoints
# ──────────────────────────────────────────────

@app.get("/api/lucy/config")
async def get_lucy_config():
    """Get Lucy API configuration for frontend."""
    return {
        "api_key": os.getenv("LUCY_API_KEY", ""),
        "model": "lucy-latest",
    }


@app.post("/api/lucy/process")
async def lucy_process(request: dict):
    """Process a single frame with Lucy API."""
    import asyncio
    import concurrent.futures

    try:
        frame_b64 = request.get("frame")
        clothing_path = request.get("clothing")
        prompt = request.get("prompt", "")

        if not frame_b64 or not clothing_path:
            return {"error": "Missing frame or clothing"}

        # Decode frame
        if frame_b64.startswith("data:"):
            frame_b64 = frame_b64.split(",", 1)[1]
        frame_bytes = base64.b64decode(frame_b64)
        frame_img = Image.open(io.BytesIO(frame_bytes))

        # Load clothing
        clothing_full_path = str(CLOTHING_DIR / clothing_path)
        if not os.path.exists(clothing_full_path):
            return {"error": f"Clothing not found: {clothing_path}"}
        clothing_img = Image.open(clothing_full_path)

        # Run Lucy API in thread pool
        from lucy_api import lucy_api

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result_img = await loop.run_in_executor(
                pool, lucy_api.transform_image, frame_img, clothing_img, prompt
            )

        if result_img:
            # Convert result to base64
            buffered = io.BytesIO()
            result_img.save(buffered, format="PNG")
            result_b64 = base64.b64encode(buffered.getvalue()).decode()
            return {"image": result_b64}
        else:
            return {"error": "Lucy API returned empty result"}

    except Exception as e:
        logger.error(f"Lucy process error: {e}")
        return {"error": str(e)}


@app.get("/api/clothing/list")
async def list_clothing():
    """List all clothing images."""
    clothing_dir = CLOTHING_DIR
    if not clothing_dir.exists():
        return {"clothing": []}

    images = []
    for f in clothing_dir.iterdir():
        if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
            images.append({
                "filename": f.name,
                "path": str(f),
                "size": f.stat().st_size,
            })

    return {"clothing": images}


@app.get("/lucy")
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

    # Log Lucy VTON realtime status
    try:
        from lucy_realtime import lucy_realtime
        if lucy_realtime.is_configured():
            logger.info("Lucy VTON realtime: READY (decart SDK + API key configured)")
        else:
            logger.warning("Lucy VTON realtime: NOT AVAILABLE (missing SDK or API key)")
    except Exception as e:
        logger.warning(f"Lucy VTON realtime: NOT AVAILABLE ({e})")

    # Try to connect to OBS on startup
    if OBS_AVAILABLE:
        try:
            obs_controller.connect(OBS_HOST, OBS_PORT, OBS_PASSWORD)
        except:
            logger.warning("Could not connect to OBS on startup")


@app.on_event("shutdown")
async def shutdown():
    obs_controller.disconnect()
    try:
        from lucy_realtime import lucy_realtime
        if lucy_realtime.is_connected:
            await lucy_realtime.disconnect()
    except Exception:
        pass
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
