"""
Lucy 2.1 Real-Time API Integration
Uses WebRTC for live video processing
"""

import os
import io
import json
import logging
import asyncio
import threading
from pathlib import Path
from typing import Optional, Callable

from PIL import Image
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class LucyRealtimeAPI:
    """Lucy 2.1 Real-Time API client using WebRTC."""

    def __init__(self):
        self.api_key = os.getenv("LUCY_API_KEY")
        self.client = None
        self.session = None
        self.is_connected = False
        self.on_result_callback = None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "YOUR_API_KEY_HERE")

    def connect(self, on_result: Callable = None) -> bool:
        """Connect to Lucy real-time API."""
        if not self.is_configured():
            logger.error("Lucy API key not configured")
            return False

        try:
            from decart import DecartClient, models

            logger.info("Connecting to Lucy real-time API...")
            self.client = DecartClient(api_key=self.api_key)
            self.on_result_callback = on_result

            logger.info("Lucy real-time API client created")
            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            import traceback
            traceback.print_exc()
            return False

    def transform_image(self, person_image: Image.Image, reference_image: Image.Image, prompt: str = "") -> Optional[Image.Image]:
        """Transform image using real-time API."""
        if not self.client:
            if not self.connect():
                return None

        try:
            from decart import models, process

            logger.info("Processing image with Lucy real-time API...")

            # Convert images to bytes
            person_buf = io.BytesIO()
            person_image.save(person_buf, format='PNG')
            person_bytes = person_buf.getvalue()

            ref_buf = io.BytesIO()
            reference_image.save(ref_buf, format='PNG')
            ref_bytes = ref_buf.getvalue()

            # Use the queue API for single image processing
            result = process(
                client=self.client,
                model=models.video("lucy-latest"),
                input_data={
                    "data": person_bytes,
                    "reference_image": ref_bytes,
                    "prompt": prompt or "Transform the person to wear the clothing from the reference image",
                }
            )

            if result and hasattr(result, 'output'):
                # Extract image from result
                output = result.output
                if isinstance(output, bytes):
                    return Image.open(io.BytesIO(output))
                elif isinstance(output, str) and output.startswith('http'):
                    import requests
                    r = requests.get(output, verify=False, timeout=60)
                    if r.status_code == 200:
                        return Image.open(io.BytesIO(r.content))

            logger.warning(f"Unexpected result format: {result}")
            return None

        except Exception as e:
            logger.error(f"Transform error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def disconnect(self):
        """Disconnect from real-time API."""
        self.client = None
        self.session = None
        self.is_connected = False
        logger.info("Disconnected from Lucy real-time API")


# Global instance
lucy_realtime = LucyRealtimeAPI()
