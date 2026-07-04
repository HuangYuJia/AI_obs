"""
Lucy VTON Real-Time API Integration
Uses Decart SDK with WebRTC (LiveKit) for live virtual try-on streaming.
Model: lucy-vton-latest
"""

import os
import io
import asyncio
import logging
import threading
from typing import Optional, Callable, Awaitable, Union
from pathlib import Path

from PIL import Image
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Check if decart SDK is available
try:
    from decart import DecartClient, SetInput, models
    from decart.realtime import RealtimeClient, RealtimeConnectOptions
    from livekit import rtc
    DECART_SDK_AVAILABLE = True
except ImportError:
    DECART_SDK_AVAILABLE = False
    logger.warning("decart SDK not installed. Run: pip install decart[realtime]")


class LucyRealtimeAPI:
    """Lucy VTON real-time client using WebRTC via Decart SDK."""

    def __init__(self):
        self.api_key = os.getenv("LUCY_API_KEY")
        self._client = None           # DecartClient
        self._realtime = None         # RealtimeClient (WebRTC session)
        self._source = None           # rtc.VideoSource
        self._model = None            # model descriptor
        self._loop = None             # asyncio event loop
        self._on_frame = None         # user callback for processed frames
        self.is_connected = False
        self._frame_count = 0         # debug: track frames pushed

    def is_configured(self) -> bool:
        return bool(DECART_SDK_AVAILABLE and self.api_key and self.api_key != "YOUR_API_KEY_HERE")

    async def connect(
        self,
        on_frame: Callable[[Image.Image], Union[None, Awaitable[None]]],
        prompt: str = "",
        image_bytes: Optional[bytes] = None,
        model_name: str = "lucy-vton-latest",
    ) -> bool:
        """
        Establish WebRTC session with Lucy real-time model.

        Args:
            on_frame: Callback receiving processed PIL Images.
            prompt: Initial prompt (clothing try-on or person transform).
            image_bytes: Initial reference image bytes (clothing or person).
            model_name: Model to use - "lucy-vton-latest" or "lucy-2.1".

        Returns:
            True if connected successfully.
        """
        if not self.is_configured():
            logger.error("Lucy realtime API not configured (missing SDK or API key)")
            return False

        if self.is_connected:
            logger.warning("Already connected, disconnecting first")
            await self.disconnect()

        try:
            self._loop = asyncio.get_running_loop()
            self._on_frame = on_frame
            self._client = DecartClient(api_key=self.api_key)
            self._model = models.realtime(model_name)

            logger.info(
                f"Connecting to Lucy realtime (model={model_name}, "
                f"resolution={self._model.width}x{self._model.height})"
            )

            # Create video source for pushing frames
            self._source = rtc.VideoSource(self._model.width, self._model.height)
            local_track = rtc.LocalVideoTrack.create_video_track("obs-input", self._source)

            # Handle transformed output frames from Decart
            def on_remote_stream(track: rtc.RemoteVideoTrack):
                logger.info("on_remote_stream callback fired - receiving processed track")
                asyncio.create_task(self._consume_remote_track(track))

            # Connect via WebRTC (without initial_state, set clothing after)
            self._realtime = await RealtimeClient.connect(
                base_url=self._client.realtime_base_url,
                api_key=self._client.api_key,
                local_track=local_track,
                options=RealtimeConnectOptions(
                    model=self._model,
                    on_remote_stream=on_remote_stream,
                ),
            )

            # Add connection state listener for debugging
            def on_connection_change(state):
                logger.info(f"WebRTC connection state: {state}")
            self._realtime.on("connection_change", on_connection_change)

            def on_error(error):
                logger.error(f"WebRTC error: {error}")
            self._realtime.on("error", on_error)

            self.is_connected = True
            self._frame_count = 0
            logger.info(f"Lucy realtime session connected (model={model_name}, session_id={self._realtime.session_id})")

            # Set reference (clothing or person) after connection
            if prompt or image_bytes:
                logger.info(f"Setting reference: prompt={'set' if prompt else 'none'}, image={'set' if image_bytes else 'none'}")
                await self._realtime.set(SetInput(
                    prompt=prompt or "try on",
                    image=image_bytes,
                ))

            return True

        except Exception as e:
            logger.error(f"Failed to connect to Lucy VTON realtime: {e}")
            import traceback
            traceback.print_exc()
            await self.disconnect()
            return False

    async def _consume_remote_track(self, track: rtc.RemoteVideoTrack):
        """Consume processed frames from the remote WebRTC track."""
        logger.info("_consume_remote_track started")
        # Wait for connection to be fully established
        for _ in range(50):  # max 5 seconds
            if self.is_connected:
                break
            await asyncio.sleep(0.1)
        if not self.is_connected:
            logger.warning("_consume_remote_track: connection not established, aborting")
            return
        frame_count = 0
        try:
            async for event in rtc.VideoStream(track):
                if not self.is_connected:
                    logger.info("_consume_remote_track: not connected, stopping")
                    break
                frame = event.frame
                frame_count += 1
                if frame_count == 1 or frame_count % 30 == 0:
                    logger.info(f"Remote track received frame #{frame_count}")
                pil_image = self._frame_to_pil(frame)
                if pil_image and self._on_frame:
                    try:
                        result = self._on_frame(pil_image)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error(f"Error in on_frame callback: {e}")
            logger.info(f"_consume_remote_track ended after {frame_count} frames")
        except Exception as e:
            if self.is_connected:
                logger.error(f"Error consuming remote track: {e}")
                import traceback
                traceback.print_exc()

    @staticmethod
    def _frame_to_pil(frame) -> Optional[Image.Image]:
        """Convert a LiveKit VideoFrame to PIL Image."""
        try:
            # Get raw bytes from the frame
            argb_frame = frame.convert(rtc.VideoBufferType.ARGB)
            w, h = argb_frame.width, argb_frame.height
            data = argb_frame.data
            # ARGB -> RGB: skip alpha byte
            rgb = bytearray(w * h * 3)
            for i in range(w * h):
                rgb[i*3] = data[i*4+1]
                rgb[i*3+1] = data[i*4+2]
                rgb[i*3+2] = data[i*4+3]
            return Image.frombytes("RGB", (w, h), bytes(rgb))
        except Exception as e:
            logger.error(f"Error converting frame to PIL: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def push_frame(self, image: Image.Image):
        """
        Push an OBS frame into the WebRTC stream for processing.

        Args:
            image: PIL Image from OBS screenshot.
        """
        if not self.is_connected or not self._source:
            logger.warning("Cannot push frame: not connected")
            return

        try:
            # Resize to model dimensions
            target_size = (self._model.width, self._model.height)
            if image.size != target_size:
                image = image.resize(target_size, Image.LANCZOS)

            # Convert to RGB if needed
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Get raw RGB bytes
            rgb_bytes = image.tobytes()

            # Create LiveKit VideoFrame and push
            video_frame = rtc.VideoFrame(
                width=self._model.width,
                height=self._model.height,
                type=rtc.VideoBufferType.RGB24,
                data=rgb_bytes,
            )
            self._source.capture_frame(video_frame)
            self._frame_count += 1
            if self._frame_count == 1 or self._frame_count % 30 == 0:
                logger.info(f"Pushed frame #{self._frame_count} to WebRTC stream")

        except Exception as e:
            logger.error(f"Error pushing frame: {e}")

    async def update_clothing(
        self,
        prompt: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
    ):
        """
        Change clothing reference mid-session. Uses atomic set() to avoid
        intermediate rendering artifacts.

        Args:
            prompt: New clothing prompt. Pass None to keep current.
            image_bytes: New clothing image bytes. Pass None to keep current.
        """
        if not self.is_connected or not self._realtime:
            logger.warning("Cannot update clothing: not connected")
            return

        try:
            kwargs = {}
            if prompt is not None:
                kwargs["prompt"] = prompt
            if image_bytes is not None:
                kwargs["image"] = image_bytes

            if kwargs:
                await self._realtime.set(SetInput(**kwargs))
                logger.info(f"Updated clothing: prompt={'set' if prompt else 'kept'}, image={'set' if image_bytes else 'kept'}")

        except Exception as e:
            logger.error(f"Error updating clothing: {e}")

    async def disconnect(self):
        """Clean up WebRTC session."""
        self.is_connected = False

        if self._realtime:
            try:
                await self._realtime.disconnect()
            except Exception as e:
                logger.debug(f"Error disconnecting realtime: {e}")
            self._realtime = None

        self._source = None
        self._model = None
        self._client = None
        self._on_frame = None
        self._loop = None

        logger.info("Lucy VTON realtime session disconnected")


# Global instance
lucy_realtime = LucyRealtimeAPI()
