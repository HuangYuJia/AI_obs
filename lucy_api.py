"""
Lucy 2.1 API Integration
Real-time virtual try-on using Decart Lucy model
"""

import os
import io
import json
import logging
import base64
import hashlib
import tempfile
from pathlib import Path
from typing import Optional

import requests
import cv2
import numpy as np
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class LucyAPI:
    """Lucy 2.1 API client for virtual try-on."""

    def __init__(self):
        self.api_key = os.getenv("LUCY_API_KEY")
        self.base_url = "https://api.decart.ai"
        self.endpoint = "/v1/jobs/lucy-2.1"
        self.cache = {}  # Simple result cache
        self.max_cache_size = 50

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "YOUR_API_KEY_HERE")

    def _get_cache_key(self, person: Image.Image, clothing: Image.Image, prompt: str) -> str:
        """Generate cache key from images and prompt."""
        # Use image sizes and prompt as cache key (fast)
        key = f"{person.size}_{clothing.size}_{prompt}"
        return hashlib.md5(key.encode()).hexdigest()

    def _compress_image(self, image: Image.Image, max_size: int = 1024) -> bytes:
        """Compress image for faster upload."""
        # Resize if too large
        img = image.copy()
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # Convert to JPEG for smaller size
        if img.mode == 'RGBA':
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        return buf.getvalue()

    def _image_to_video(self, image: Image.Image, duration_frames: int = 5) -> bytes:
        """Convert a single image to a short video clip (optimized)."""
        # Resize for faster processing
        img = image.copy()
        img.thumbnail((720, 720), Image.Resampling.LANCZOS)

        img_np = np.array(img)

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp_path = tmp.name

        h, w = img_np.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(tmp_path, fourcc, 10, (w, h))

        for _ in range(duration_frames):
            out.write(cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
        out.release()

        with open(tmp_path, 'rb') as f:
            video_bytes = f.read()

        os.unlink(tmp_path)
        return video_bytes

    def transform_image(self, person_image: Image.Image, reference_image: Image.Image, prompt: str = "") -> Optional[Image.Image]:
        """Transform a person image using Lucy API."""
        if not self.is_configured():
            logger.error("Lucy API key not configured")
            return None

        try:
            # Compress images for faster upload
            logger.info("Compressing images...")
            person_video = self._image_to_video(person_image)
            ref_bytes = self._compress_image(reference_image, max_size=512)

            logger.info(f"Upload sizes: person_video={len(person_video)//1024}KB, reference={len(ref_bytes)//1024}KB")

            # Call Lucy API
            headers = {"x-api-key": self.api_key}

            files = {
                'data': ('person.mp4', person_video, 'video/mp4'),
                'reference_image': ('clothing.jpg', ref_bytes, 'image/jpeg'),
            }

            data = {
                'prompt': prompt or "Transform the person to wear the clothing from the reference image",
                'seed': '42',
                'resolution': '720p',
                'enhance_prompt': 'true',
            }

            logger.info("Calling Lucy API...")
            r = requests.post(
                f"{self.base_url}{self.endpoint}",
                headers=headers,
                files=files,
                data=data,
                verify=False,
                timeout=60
            )

            logger.info(f"Lucy API response: {r.status_code}")

            if r.status_code == 200:
                result = r.json()

                # Check if it's an async job
                if "job_id" in result and result.get("status") == "pending":
                    job_id = result["job_id"]
                    logger.info(f"Async job: {job_id}")
                    return self._poll_job(job_id)
                else:
                    img = self._extract_image(result)
                    return img
            else:
                logger.error(f"Lucy API error: {r.status_code} - {r.text[:300]}")
                return None

        except Exception as e:
            logger.error(f"Lucy API error: {e}")
            return None

    def _poll_job(self, job_id: str, max_wait: int = 120) -> Optional[Image.Image]:
        """Poll for async job completion and download result."""
        import time

        headers = {"x-api-key": self.api_key}
        start = time.time()
        poll_interval = 2  # Start with 2 second intervals

        while time.time() - start < max_wait:
            try:
                r = requests.get(
                    f"{self.base_url}/v1/jobs/{job_id}",
                    headers=headers,
                    verify=False,
                    timeout=10
                )

                if r.status_code == 200:
                    result = r.json()
                    status = result.get("status", "")

                    if status == "completed":
                        logger.info(f"Job completed in {time.time()-start:.1f}s")
                        content_r = requests.get(
                            f"{self.base_url}/v1/jobs/{job_id}/content",
                            headers=headers,
                            verify=False,
                            timeout=60
                        )

                        if content_r.status_code == 200:
                            content_type = content_r.headers.get('content-type', '')
                            if 'video' in content_type:
                                img = self._extract_frame_from_video(content_r.content)
                            else:
                                img = Image.open(io.BytesIO(content_r.content))

                            if img:
                                return img
                        else:
                            logger.error(f"Download failed: {content_r.status_code}")
                            return None

                    elif status == "failed":
                        logger.error(f"Job failed: {result}")
                        return None
                    else:
                        time.sleep(poll_interval)
                        poll_interval = min(poll_interval * 1.2, 5)  # Gradually increase interval
                else:
                    time.sleep(poll_interval)

            except Exception as e:
                logger.warning(f"Poll error: {e}")
                time.sleep(poll_interval)

        logger.error("Job timed out")
        return None

    def _cache_result(self, key: str, image: Image.Image):
        """Cache result for future use."""
        if len(self.cache) >= self.max_cache_size:
            # Remove oldest entry
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = image.copy()

    def clear_cache(self):
        """Clear all cached results."""
        self.cache.clear()

    def _extract_image(self, result: dict) -> Optional[Image.Image]:
        """Extract image from API response."""
        for key in ["output", "result_url", "video_url", "image_url"]:
            if key in result:
                value = result[key]
                if isinstance(value, str):
                    if value.startswith("http"):
                        img_r = requests.get(value, verify=False, timeout=60)
                        if img_r.status_code == 200:
                            if key == "video_url":
                                return self._extract_frame_from_video(img_r.content)
                            return Image.open(io.BytesIO(img_r.content))
                    elif value.startswith("data:"):
                        img_data = value.split(",", 1)[1]
                        img_bytes = base64.b64decode(img_data)
                        return Image.open(io.BytesIO(img_bytes))
        return None

    def _extract_frame_from_video(self, video_bytes: bytes) -> Optional[Image.Image]:
        """Extract first frame from video bytes."""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        try:
            cap = cv2.VideoCapture(tmp_path)
            ret, frame = cap.read()
            cap.release()
            if ret:
                return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        finally:
            os.unlink(tmp_path)

        return None


# Global instance
lucy_api = LucyAPI()
