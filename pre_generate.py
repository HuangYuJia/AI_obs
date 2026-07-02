"""
Pre-generate virtual try-on results using IDM-VTON
Run this script overnight to generate multiple clothing try-on results
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from PIL import Image

# Add IDM-VTON to path
IDM_VTON_DIR = Path(__file__).parent / "IDM-VTON"
sys.path.insert(0, str(IDM_VTON_DIR))
sys.path.insert(0, str(IDM_VTON_DIR / "gradio_demo"))
os.chdir(IDM_VTON_DIR)  # Change working directory for relative imports

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pre_generate.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
IDM_VTON_DIR = BASE_DIR / "IDM-VTON"
PERSON_DIR = BASE_DIR / "uploads"
CLOTHING_DIR = BASE_DIR / "clothing"
OUTPUT_DIR = BASE_DIR / "outputs" / "pre_generated"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# IDM-VTON settings
DENOISE_STEPS = 15  # Reduced from 30 to save time
SEED = 42

# Model paths - use local cache
HOME = Path.home()
CACHE_DIR = HOME / ".cache" / "huggingface" / "hub"
MODEL_DIR = CACHE_DIR / "models--yisol--IDM-VTON" / "snapshots"

# Find the latest snapshot
def find_model_snapshot():
    if MODEL_DIR.exists():
        snapshots = list(MODEL_DIR.iterdir())
        if snapshots:
            return str(snapshots[0])
    # Fallback to direct path
    return str(CACHE_DIR / "models--yisol--IDM-VTON")

# ──────────────────────────────────────────────
# Load IDM-VTON Model
# ──────────────────────────────────────────────
logger.info("Loading IDM-VTON model...")

import torch
import numpy as np
from torchvision import transforms
from torchvision.transforms.functional import to_pil_image

device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
logger.info(f"Using device: {device}")

from src.tryon_pipeline import StableDiffusionXLInpaintPipeline as TryonPipeline
from src.unet_hacked_garmnet import UNet2DConditionModel as UNet2DConditionModel_ref
from src.unet_hacked_tryon import UNet2DConditionModel
from transformers import (
    CLIPImageProcessor,
    CLIPVisionModelWithProjection,
    CLIPTextModel,
    CLIPTextModelWithProjection,
    AutoTokenizer,
)
from diffusers import DDPMScheduler, AutoencoderKL
from preprocess.humanparsing.run_parsing import Parsing
from preprocess.openpose.run_openpose import OpenPose
from utils_mask import get_mask_location
import apply_net
from detectron2.data.detection_utils import convert_PIL_to_numpy, _apply_exif_orientation

# Model paths - use local cache
BASE_PATH = find_model_snapshot()
logger.info(f"Using model from: {BASE_PATH}")

# Load models
logger.info("Loading UNet...")
unet = UNet2DConditionModel.from_pretrained(BASE_PATH, subfolder="unet", torch_dtype=torch.float16)
unet.requires_grad_(False)

logger.info("Loading tokenizers...")
tokenizer_one = AutoTokenizer.from_pretrained(BASE_PATH, subfolder="tokenizer", use_fast=False)
tokenizer_two = AutoTokenizer.from_pretrained(BASE_PATH, subfolder="tokenizer_2", use_fast=False)

logger.info("Loading scheduler...")
noise_scheduler = DDPMScheduler.from_pretrained(BASE_PATH, subfolder="scheduler")

logger.info("Loading text encoders...")
text_encoder_one = CLIPTextModel.from_pretrained(BASE_PATH, subfolder="text_encoder", torch_dtype=torch.float16)
text_encoder_two = CLIPTextModelWithProjection.from_pretrained(BASE_PATH, subfolder="text_encoder_2", torch_dtype=torch.float16)

logger.info("Loading image encoder...")
image_encoder = CLIPVisionModelWithProjection.from_pretrained(BASE_PATH, subfolder="image_encoder", torch_dtype=torch.float16)

logger.info("Loading VAE...")
vae = AutoencoderKL.from_pretrained(BASE_PATH, subfolder="vae", torch_dtype=torch.float16)

logger.info("Loading UNet encoder...")
UNet_Encoder = UNet2DConditionModel_ref.from_pretrained(BASE_PATH, subfolder="unet_encoder", torch_dtype=torch.float16)

logger.info("Loading pipeline...")
pipe = TryonPipeline.from_pretrained(
    BASE_PATH,
    unet=unet,
    vae=vae,
    feature_extractor=CLIPImageProcessor(),
    text_encoder=text_encoder_one,
    text_encoder_2=text_encoder_two,
    tokenizer=tokenizer_one,
    tokenizer_2=tokenizer_two,
    scheduler=noise_scheduler,
    image_encoder=image_encoder,
    torch_dtype=torch.float16,
)
pipe.unet_encoder = UNet_Encoder

logger.info("Loading preprocessing models...")
parsing_model = Parsing(0)
openpose_model = OpenPose(0)

# Set models to eval mode
UNet_Encoder.requires_grad_(False)
image_encoder.requires_grad_(False)
vae.requires_grad_(False)
unet.requires_grad_(False)
text_encoder_one.requires_grad_(False)
text_encoder_two.requires_grad_(False)

tensor_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize([0.5], [0.5]),
])

logger.info("All models loaded successfully!")


def pil_to_binary_mask(pil_image, threshold=0):
    np_image = np.array(pil_image)
    grayscale_image = Image.fromarray(np_image).convert("L")
    binary_mask = np.array(grayscale_image) > threshold
    mask = np.zeros(binary_mask.shape, dtype=np.uint8)
    for i in range(binary_mask.shape[0]):
        for j in range(binary_mask.shape[1]):
            if binary_mask[i, j]:
                mask[i, j] = 1
    mask = (mask * 255).astype(np.uint8)
    return Image.fromarray(mask)


def tryon(person_image: Image.Image, clothing_image: Image.Image,
          garment_des: str = "a photo of clothing") -> Image.Image:
    """Apply virtual try-on."""
    try:
        # Move models to device
        openpose_model.preprocessor.body_estimation.model.to(device)
        pipe.to(device)
        pipe.unet_encoder.to(device)

        # Prepare images
        garm_img = clothing_image.convert("RGB").resize((768, 1024))
        human_img = person_image.convert("RGB").resize((768, 1024))

        logger.info(f"Processing: person={human_img.size}, clothing={garm_img.size}")

        # Generate mask
        logger.info("Generating keypoints and parsing...")
        keypoints = openpose_model(human_img.resize((384, 512)))
        model_parse, _ = parsing_model(human_img.resize((384, 512)))
        mask, mask_gray = get_mask_location('hd', "upper_body", model_parse, keypoints)
        mask = mask.resize((768, 1024))

        mask_gray = (1 - tensor_transform(mask)) * tensor_transform(human_img)
        mask_gray = to_pil_image((mask_gray + 1.0) / 2.0)

        # Generate densepose
        logger.info("Generating densepose...")
        human_img_arg = _apply_exif_orientation(human_img.resize((384, 512)))
        human_img_arg = convert_PIL_to_numpy(human_img_arg, format="BGR")

        args = apply_net.create_argument_parser().parse_args((
            'show', './configs/densepose_rcnn_R_50_FPN_s1x.yaml',
            './ckpt/densepose/model_final_162be9.pkl', 'dp_segm', '-v',
            '--opts', 'MODEL.DEVICE', 'cuda'
        ))
        pose_img = args.func(args, human_img_arg)
        pose_img = pose_img[:, :, ::-1]
        pose_img = Image.fromarray(pose_img).resize((768, 1024))

        logger.info("Running inference...")
        # Run inference
        with torch.no_grad():
            with torch.amp.autocast('cuda'):
                with torch.inference_mode():
                    prompt = "model is wearing " + garment_des
                    negative_prompt = "monochrome, lowres, bad anatomy, worst quality, low quality"

                    (
                        prompt_embeds,
                        negative_prompt_embeds,
                        pooled_prompt_embeds,
                        negative_pooled_prompt_embeds,
                    ) = pipe.encode_prompt(
                        prompt,
                        num_images_per_prompt=1,
                        do_classifier_free_guidance=True,
                        negative_prompt=negative_prompt,
                    )

                    prompt = "a photo of " + garment_des
                    negative_prompt = "monochrome, lowres, bad anatomy, worst quality, low quality"
                    if not isinstance(prompt, list):
                        prompt = [prompt]
                    if not isinstance(negative_prompt, list):
                        negative_prompt = [negative_prompt]
                    with torch.inference_mode():
                        (
                            prompt_embeds_c,
                            _,
                            _,
                            _,
                        ) = pipe.encode_prompt(
                            prompt,
                            num_images_per_prompt=1,
                            do_classifier_free_guidance=False,
                            negative_prompt=negative_prompt,
                        )

                    # Convert to tensors
                    pose_tensor = tensor_transform(pose_img).unsqueeze(0).to(device, torch.float16)
                    garm_tensor = tensor_transform(garm_img).unsqueeze(0).to(device, torch.float16)
                    generator = torch.Generator(device).manual_seed(SEED)

                    image = pipe(
                        prompt_embeds=prompt_embeds.to(device, torch.float16),
                        negative_prompt_embeds=negative_prompt_embeds.to(device, torch.float16),
                        pooled_prompt_embeds=pooled_prompt_embeds.to(device, torch.float16),
                        negative_pooled_prompt_embeds=negative_pooled_prompt_embeds.to(device, torch.float16),
                        num_inference_steps=DENOISE_STEPS,
                        generator=generator,
                        strength=1.0,
                        pose_img=pose_tensor.to(device, torch.float16),
                        text_embeds_cloth=prompt_embeds_c.to(device, torch.float16),
                        cloth=garm_tensor.to(device, torch.float16),
                        mask_image=mask,
                        image=human_img,
                        height=1024,
                        width=768,
                        ip_adapter_image=garm_img.resize((768, 1024)),
                        guidance_scale=2.0,
                    )[0]

        logger.info("Inference complete")
        return image[0]
    except Exception as e:
        logger.error(f"Error in tryon: {e}")
        import traceback
        traceback.print_exc()
        raise


def find_person_image():
    """Find a suitable person image."""
    # Look for person images in uploads
    for ext in ['*.png', '*.jpg', '*.jpeg']:
        images = list(PERSON_DIR.glob(ext))
        if images:
            # Filter out temp and test images
            real_images = [img for img in images if not img.name.startswith(('temp_', 'test_'))]
            if real_images:
                return real_images[0]
            return images[0]
    return None


def find_clothing_images():
    """Find all clothing images."""
    clothing_images = []
    for ext in ['*.png', '*.jpg', '*.jpeg']:
        clothing_images.extend(CLOTHING_DIR.glob(ext))
    # Filter out temp and test images
    real_images = [img for img in clothing_images if not img.name.startswith(('temp_', 'test_'))]
    # For testing: only return first image
    return real_images[:1] if real_images else []


def main():
    """Main function to pre-generate try-on results."""
    # Find person image
    person_path = find_person_image()
    if not person_path:
        logger.error("No person image found in uploads directory!")
        return

    logger.info(f"Using person image: {person_path}")
    person_image = Image.open(person_path)

    # Find clothing images
    clothing_paths = find_clothing_images()
    if not clothing_paths:
        logger.error("No clothing images found in clothing directory!")
        return

    logger.info(f"Found {len(clothing_paths)} clothing images")

    # Create output directory for this person
    person_output_dir = OUTPUT_DIR / person_path.stem
    person_output_dir.mkdir(exist_ok=True)

    # Generate try-on for each clothing
    results = []
    total = len(clothing_paths)

    for i, clothing_path in enumerate(clothing_paths, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {i}/{total}: {clothing_path.name}")
        logger.info(f"{'='*60}")

        # Check if already generated
        output_path = person_output_dir / f"{clothing_path.stem}_tryon.png"
        if output_path.exists():
            logger.info(f"Already exists, skipping: {output_path}")
            results.append({
                "clothing": clothing_path.name,
                "output": output_path.name,
                "status": "skipped"
            })
            continue

        try:
            start_time = time.time()

            # Load clothing image
            clothing_image = Image.open(clothing_path)

            # Generate try-on
            result_image = tryon(person_image, clothing_image)

            # Save result
            result_image.save(output_path)

            elapsed = time.time() - start_time
            logger.info(f"Generated in {elapsed:.1f}s: {output_path}")

            results.append({
                "clothing": clothing_path.name,
                "output": output_path.name,
                "status": "success",
                "time": elapsed
            })

        except Exception as e:
            logger.error(f"Failed to process {clothing_path.name}: {e}")
            results.append({
                "clothing": clothing_path.name,
                "output": None,
                "status": "error",
                "error": str(e)
            })

    # Save results summary
    summary_path = person_output_dir / "results.json"
    with open(summary_path, 'w') as f:
        json.dump({
            "person": person_path.name,
            "total": total,
            "results": results,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }, f, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"Generation complete!")
    logger.info(f"Results saved to: {person_output_dir}")
    logger.info(f"Summary: {summary_path}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
