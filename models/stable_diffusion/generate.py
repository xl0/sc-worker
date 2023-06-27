import os
import torch
from .helpers import get_scheduler
from .constants import SD_MODELS
from models.constants import DEVICE
import time
from shared.helpers import download_and_fit_image, download_and_fit_image_mask


def generate(
    prompt,
    negative_prompt,
    prompt_prefix,
    negative_prompt_prefix,
    width,
    height,
    num_outputs,
    num_inference_steps,
    guidance_scale,
    init_image_url,
    mask_image_url,
    prompt_strength,
    scheduler,
    seed,
    model,
    pipe,
):
    if seed is None:
        seed = int.from_bytes(os.urandom(2), "big")
    print(f"Using seed: {seed}")

    if prompt_prefix is not None:
        prompt = f"{prompt_prefix} {prompt}"
    else:
        default_prompt_prefix = SD_MODELS[model].get("prompt_prefix", None)
        if default_prompt_prefix is not None:
            prompt = f"{default_prompt_prefix} {prompt}"

    if negative_prompt_prefix is not None:
        if negative_prompt is None or negative_prompt == "":
            negative_prompt = negative_prompt_prefix
        else:
            negative_prompt = f"{negative_prompt_prefix} {negative_prompt}"
    else:
        default_negative_prompt_prefix = SD_MODELS[model].get(
            "negative_prompt_prefix", None
        )
        if default_negative_prompt_prefix is not None:
            if negative_prompt is None or negative_prompt == "":
                negative_prompt = default_negative_prompt_prefix
            else:
                negative_prompt = f"{default_negative_prompt_prefix} {negative_prompt}"

    print(f"-- Prompt: {prompt} --")
    print(f"-- Negative Prompt: {negative_prompt} --")

    extra_kwargs = {}
    pipe.scheduler = get_scheduler(scheduler, pipe.scheduler.config)
    pipe_selected = None
    if init_image_url is not None:
        if mask_image_url is not None:
            pipe_selected = pipe.inpaint
            start_i = time.time()
            extra_kwargs["mask_image"] = download_and_fit_image(
                url=mask_image_url,
                width=width,
                height=height,
            )
            end_i = time.time()
            print(
                f"-- Downloaded and cropped mask image in: {round((end_i - start_i) * 1000)} ms"
            )
        else:
            pipe_selected = pipe.img2img
            extra_kwargs["width"] = width
            extra_kwargs["height"] = height
        start_i = time.time()
        init_image = download_and_fit_image(
            url=init_image_url,
            width=width,
            height=height,
            keep_transparency=True,
        )
        end_i = time.time()
        print(
            f"-- Downloaded and cropped init image in: {round((end_i - start_i) * 1000)} ms"
        )
        extra_kwargs["image"] = init_image
        extra_kwargs["strength"] = prompt_strength
    else:
        pipe_selected = pipe.text2img
        extra_kwargs["width"] = width
        extra_kwargs["height"] = height

    generator = torch.Generator(DEVICE).manual_seed(seed)
    output = pipe_selected(
        prompt=prompt if prompt is not None else None,
        negative_prompt=negative_prompt if negative_prompt is not None else None,
        num_images_per_prompt=num_outputs,
        guidance_scale=guidance_scale,
        generator=generator,
        num_inference_steps=num_inference_steps,
        **extra_kwargs,
    )

    output_images = []
    nsfw_count = 0

    if output.nsfw_content_detected is not None:
        for i, nsfw_flag in enumerate(output.nsfw_content_detected):
            if nsfw_flag:
                nsfw_count += 1
            else:
                output_images.append(output.images[i])
    else:
        output_images = output.images

    if nsfw_count > 0:
        print(f"NSFW content detected in {nsfw_count}/{num_outputs} of the outputs.")

    return output_images, nsfw_count
