"""
Real-Time Virtual Try-On Server
Uses MediaPipe for body segmentation + clothing overlay
Target: < 100ms latency, 20+ FPS
"""

import os
import io
import json
import time
import logging
import base64
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image
import mediapipe as mp
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# App initialization
# ──────────────────────────────────────────────
app = FastAPI(title="Real-Time Virtual Try-On", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Directories
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
CLOTHING_DIR = BASE_DIR / "clothing"
OUTPUT_DIR = BASE_DIR / "outputs"

for d in [UPLOAD_DIR, CLOTHING_DIR, OUTPUT_DIR]:
    d.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# MediaPipe Setup
# ──────────────────────────────────────────────
mp_selfie_segmentation = mp.solutions.selfie_segmentation
mp_pose = mp.solutions.pose

# Initialize models
segmentation = mp_selfie_segmentation.SelfieSegmentation(model_selection=1)
pose_estimator = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    smooth_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

logger.info("MediaPipe models loaded")


# ──────────────────────────────────────────────
# Real-Time Try-On Class
# ──────────────────────────────────────────────
class RealTimeTryOn:
    def __init__(self):
        self.current_clothing = None
        self.clothing_mask = None
        self.clothing_resized = None

    def load_clothing(self, clothing_path: str) -> bool:
        """Load and preprocess clothing image."""
        try:
            clothing_img = cv2.imread(clothing_path)
            if clothing_img is None:
                return False

            self.current_clothing = clothing_img

            # Create clothing mask (white background removal)
            gray = cv2.cvtColor(clothing_img, cv2.COLOR_BGR2GRAY)
            _, self.clothing_mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)

            logger.info(f"Loaded clothing: {clothing_img.shape}")
            return True
        except Exception as e:
            logger.error(f"Failed to load clothing: {e}")
            return False

    def apply_tryon(self, person_frame: np.ndarray) -> np.ndarray:
        """Apply virtual try-on to person frame in real-time."""
        if self.current_clothing is None:
            return person_frame

        try:
            # Convert to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(person_frame, cv2.COLOR_BGR2RGB)

            # Get segmentation mask
            results = segmentation.process(rgb_frame)
            mask = results.segmentation_mask

            # Get pose landmarks
            pose_results = pose_estimator.process(rgb_frame)

            if pose_results.pose_landmarks:
                h, w, _ = person_frame.shape
                landmarks = pose_results.pose_landmarks.landmark

                # Get shoulder and hip positions for clothing placement
                left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
                right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
                left_hip = landmarks[mp_pose.PoseLandmark.LEFT_HIP]
                right_hip = landmarks[mp_pose.PoseLandmark.RIGHT_HIP]

                # Calculate clothing region
                shoulder_y = int(min(left_shoulder.y, right_shoulder.y) * h)
                hip_y = int(max(left_hip.y, right_hip.y) * h)
                left_x = int(min(left_shoulder.x, right_shoulder.x, left_hip.x, right_hip.x) * w)
                right_x = int(max(left_shoulder.x, right_shoulder.x, left_hip.x, right_hip.x) * w)

                # Add padding
                padding = 20
                shoulder_y = max(0, shoulder_y - padding)
                hip_y = min(h, hip_y + padding)
                left_x = max(0, left_x - padding)
                right_x = min(w, right_x + padding)

                # Calculate clothing size
                clothing_width = right_x - left_x
                clothing_height = hip_y - shoulder_y

                if clothing_width > 0 and clothing_height > 0:
                    # Resize clothing to fit
                    clothing_resized = cv2.resize(
                        self.current_clothing,
                        (clothing_width, clothing_height),
                        interpolation=cv2.INTER_AREA
                    )

                    # Resize mask
                    mask_resized = cv2.resize(
                        self.clothing_mask,
                        (clothing_width, clothing_height),
                        interpolation=cv2.INTER_AREA
                    )

                    # Create 3-channel mask
                    mask_3ch = cv2.merge([mask_resized, mask_resized, mask_resized])

                    # Blend clothing with person
                    roi = person_frame[shoulder_y:hip_y, left_x:right_x]

                    # Apply mask
                    mask_float = mask_3ch.astype(float) / 255
                    clothing_float = clothing_resized.astype(float)
                    roi_float = roi.astype(float)

                    # Blend
                    blended = (clothing_float * mask_float + roi_float * (1 - mask_float)).astype(np.uint8)

                    # Apply segmentation mask for person
                    seg_mask = mask[shoulder_y:hip_y, left_x:right_x]
                    seg_mask_3ch = cv2.merge([seg_mask, seg_mask, seg_mask])

                    # Final blend
                    final = (blended.astype(float) * seg_mask_3ch + roi_float * (1 - seg_mask_3ch)).astype(np.uint8)
                    person_frame[shoulder_y:hip_y, left_x:right_x] = final

            return person_frame

        except Exception as e:
            logger.error(f"Try-on error: {e}")
            return person_frame


# Global instance
tryon_engine = RealTimeTryOn()


# ──────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "mode": "real-time"}


@app.post("/clothing/upload")
async def upload_clothing(file: UploadFile = File(...)):
    """Upload clothing image for try-on."""
    try:
        # Save file
        file_ext = Path(file.filename).suffix or ".png"
        filename = f"clothing_{int(time.time())}{file_ext}"
        file_path = CLOTHING_DIR / filename

        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        # Load into engine
        if tryon_engine.load_clothing(str(file_path)):
            return {
                "status": "success",
                "filename": filename,
                "message": "Clothing loaded for real-time try-on"
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to process clothing image")

    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tryon")
async def tryon(
    person: UploadFile = File(...),
    clothing: UploadFile = File(None),
):
    """Apply real-time virtual try-on."""
    try:
        # Read person image
        person_bytes = await person.read()
        person_img = cv2.imdecode(
            np.frombuffer(person_bytes, np.uint8),
            cv2.IMREAD_COLOR
        )

        # Load clothing if provided
        if clothing:
            clothing_bytes = await clothing.read()
            clothing_path = str(CLOTHING_DIR / "temp_clothing.png")
            with open(clothing_path, "wb") as f:
                f.write(clothing_bytes)
            tryon_engine.load_clothing(clothing_path)

        # Apply try-on
        start_time = time.time()
        result = tryon_engine.apply_tryon(person_img)
        processing_time = time.time() - start_time

        # Encode result
        _, buffer = cv2.imencode('.png', result)
        io_buf = io.BytesIO(buffer.tobytes())

        logger.info(f"Try-on completed in {processing_time*1000:.1f}ms")

        return StreamingResponse(io_buf, media_type="image/png")

    except Exception as e:
        logger.error(f"Try-on error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/tryon")
async def websocket_tryon(websocket: WebSocket):
    """WebSocket for real-time video try-on."""
    await websocket.accept()
    logger.info("WebSocket connected for real-time try-on")

    try:
        while True:
            # Receive frame
            data = await websocket.receive_bytes()

            # Decode frame
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is not None:
                # Apply try-on
                result = tryon_engine.apply_tryon(frame)

                # Encode and send back
                _, buffer = cv2.imencode('.jpg', result, [cv2.IMWRITE_JPEG_QUALITY, 80])
                await websocket.send_bytes(buffer.tobytes())

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


# ──────────────────────────────────────────────
# Serve static files
# ──────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8445)
