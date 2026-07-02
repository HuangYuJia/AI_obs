"""
CatVTON Local API Server
Fast virtual try-on using CatVTON model
"""

import os
import sys
import io
import json
import time
import logging
import base64
from pathlib import Path
from typing import Optional

import torch
import numpy as np
from PIL import Image

# Add CatVTON to path
CATVTON_DIR = Path(__file__).parent / "CatVTON"
sys.path.insert(0, str(CATVTON_DIR))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Device
device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
logger.info(f"Using device: {device}")

# ──────────────────────────────────────────────
# Load CatVTON Model
# ──────────────────────────────────────────────
logger.info("Loading CatVTON model...")

# Patch accelerate to avoid device_map issue
import accelerate.utils.modeling as accel_modeling
original_get_device = accel_modeling._get_param_device
def patched_get_param_device(param, device_map):
    if device_map is None:
        return "cpu"
    return original_get_device(param, device_map)
accel_modeling._get_param_device = patched_get_param_device

original_check = accel_modeling.check_tied_parameters_on_same_device
def patched_check(tied_params, device_map):
    if device_map is None:
        return
    original_check(tied_params, device_map)
accel_modeling.check_tied_parameters_on_same_device = patched_check

from diffusers.image_processor import VaeImageProcessor
from huggingface_hub import snapshot_download

from model.pipeline import CatVTONPipeline
from model.cloth_masker import AutoMasker, vis_mask
from utils import init_weight_dtype, resize_and_crop, resize_and_padding

# Model paths
BASE_MODEL = "booksforcharlie/stable-diffusion-inpainting"
RESUME_PATH = "zhengchong/CatVTON"

# Download model if not exists
logger.info("Downloading model weights...")
repo_path = snapshot_download(repo_id=RESUME_PATH)

# Initialize pipeline
logger.info("Initializing pipeline...")
pipeline = CatVTONPipeline(
    base_ckpt=BASE_MODEL,
    attn_ckpt=repo_path,
    attn_ckpt_version="mix",
    weight_dtype=init_weight_dtype("fp16"),
    use_tf32=True,
    device=device,
    skip_safety_check=True  # Skip NSFW check to avoid false positives
)

# Initialize mask processor
mask_processor = VaeImageProcessor(vae_scale_factor=8, do_normalize=False, do_binarize=True, do_convert_grayscale=True)

# Initialize automasker
logger.info("Initializing AutoMasker...")
automasker = AutoMasker(
    densepose_ckpt=os.path.join(repo_path, "DensePose"),
    schp_ckpt=os.path.join(repo_path, "SCHP"),
    device=device,
)

logger.info("CatVTON model loaded successfully!")

# ──────────────────────────────────────────────
# FastAPI Server
# ──────────────────────────────────────────────
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="CatVTON Local API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "device": device, "model": "CatVTON"}


@app.post("/tryon")
async def tryon(
    person: UploadFile = File(...),
    clothing: UploadFile = File(...),
    cloth_type: str = Form("upper"),
    num_inference_steps: int = Form(30),
    guidance_scale: float = Form(2.0),
    seed: int = Form(42),
):
    """Apply virtual try-on using CatVTON."""
    try:
        start_time = time.time()

        # Read images
        person_bytes = await person.read()
        clothing_bytes = await clothing.read()

        person_img = Image.open(io.BytesIO(person_bytes)).convert("RGB")
        clothing_img = Image.open(io.BytesIO(clothing_bytes)).convert("RGB")

        logger.info(f"Processing: person={person_img.size}, clothing={clothing_img.size}")

        # Resize images
        person_img = resize_and_crop(person_img, (768, 1024))
        clothing_img = resize_and_padding(clothing_img, (768, 1024))

        # Generate mask using AutoMasker
        logger.info("Generating mask...")
        mask = automasker(person_img, cloth_type)['mask']
        mask = mask_processor.blur(mask, blur_factor=9)

        # Set generator
        generator = None
        if seed != -1:
            generator = torch.Generator(device=device).manual_seed(seed)

        # Run inference
        logger.info("Running CatVTON inference...")
        result_image = pipeline(
            image=person_img,
            condition_image=clothing_img,
            mask=mask,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=generator
        )[0]

        elapsed = time.time() - start_time
        logger.info(f"CatVTON inference completed in {elapsed:.1f}s")

        # Return result
        buf = io.BytesIO()
        result_image.save(buf, format='PNG')
        buf.seek(0)

        return StreamingResponse(buf, media_type="image/png")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8446)
