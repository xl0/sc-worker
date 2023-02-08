import time
import os

import torch

from models.stable_diffusion.generate import generate
from models.stable_diffusion.constants import (
    SD_MODEL_DEFAULT_KEY,
)
from models.stable_diffusion.helpers import (
    png_image_to_bytes,
)
from models.nllb.translate import translate_text
from models.swinir.upscale import upscale

from typing import List
from .predict import PredictOutput, PredictResult
from lingua import LanguageDetector
from diffusers import StableDiffusionPipeline
from PIL import Image
from typing import Callable, Any
import numpy as np


@torch.inference_mode()
def predict(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    num_outputs: int,
    num_inference_steps: int,
    guidance_scale: float,
    scheduler: str,
    model: str,
    seed: int,
    prompt_flores_200_code: str,
    negative_prompt_flores_200_code: str,
    prompt_prefix: str,
    negative_prompt_prefix: str,
    output_image_extension: str,
    output_image_quality: int,
    image_to_upscale: str,
    process_type: str,
    translator_cog_url: str,
    language_detector_pipe: LanguageDetector,
    txt2img_pipes: dict[str, StableDiffusionPipeline],
    upscaler_pipe: Callable[[np.ndarray | Image.Image, Any, Any], Image.Image],
    upscaler_args: Any,
) -> PredictResult:
    processStart = time.time()
    print("//////////////////////////////////////////////////////////////////")
    print(f"⏳ Process started: {process_type} ⏳")
    output_images = []
    nsfw_count = 0

    if process_type == "generate" or process_type == "generate_and_upscale":
        if translator_cog_url is None:
            translator_cog_url = os.environ.get("TRANSLATOR_COG_URL", None)

        t_prompt = prompt
        t_negative_prompt = negative_prompt
        if translator_cog_url is not None:
            [t_prompt, t_negative_prompt] = translate_text(
                prompt,
                prompt_flores_200_code,
                negative_prompt,
                negative_prompt_flores_200_code,
                translator_cog_url,
                language_detector_pipe,
                "Prompt & Negative Prompt",
            )
        else:
            print("-- Translator cog URL is not set. Skipping translation. --")

        txt2img_pipe = txt2img_pipes[model]
        print(
            f"🖥️ Generating - Model: {model} - Width: {width} - Height: {height} - Steps: {num_inference_steps} - Outputs: {num_outputs} 🖥️"
        )
        startTime = time.time()
        generate_output_images, generate_nsfw_count = generate(
            t_prompt,
            t_negative_prompt,
            prompt_prefix,
            negative_prompt_prefix,
            width,
            height,
            num_outputs,
            num_inference_steps,
            guidance_scale,
            scheduler,
            seed,
            model,
            txt2img_pipe,
        )
        output_images = generate_output_images
        nsfw_count = generate_nsfw_count
        endTime = time.time()
        print(
            f"🖥️ Generated in {round((endTime - startTime) * 1000)} ms - Model: {model} - Width: {width} - Height: {height} - Steps: {num_inference_steps} - Outputs: {num_outputs} 🖥️"
        )

    if process_type == "upscale" or process_type == "generate_and_upscale":
        startTime = time.time()
        if process_type == "upscale":
            upscale_output_image = upscale(
                image_to_upscale, upscaler_pipe, upscaler_args
            )
            output_images = [upscale_output_image]
        else:
            upscale_output_images = []
            for image in output_images:
                upscale_output_image = upscale(image, upscaler_pipe, upscaler_args)
                upscale_output_images.append(upscale_output_image)
            output_images = upscale_output_images
        endTime = time.time()
        print(f"⭐️ Upscaled in: {round((endTime - startTime) * 1000)} ms ⭐️")

    # Prepare output objects
    output_objects = []
    output_len = len(output_images)
    for i, image in enumerate(output_images):
        start_time_save = time.time()
        image_bytes = png_image_to_bytes(image)
        obj = {
            "image_bytes": image_bytes,
            "target_quality": output_image_quality,
            "target_extension": output_image_extension,
        }
        output_objects.append(obj)
        end_time_save = time.time()
        print(
            f"-- Image {i+1}/{output_len} converted to bytes in: {round((end_time_save - start_time_save) * 1000)} ms --"
        )

    result = {
        "outputs": output_objects,
        "nsfw_count": nsfw_count,
    }
    processEnd = time.time()
    print(f"✅ Process completed in: {round((processEnd - processStart) * 1000)} ms ✅")
    print("//////////////////////////////////////////////////////////////////")

    return result
