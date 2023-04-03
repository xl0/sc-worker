import time

import torch
from models.stable_diffusion.constants import (
    SD_MODEL_CHOICES,
    SD_MODEL_DEFAULT_KEY,
    SD_SCHEDULER_CHOICES,
    SD_SCHEDULER_DEFAULT,
)

from models.stable_diffusion.generate import generate
from models.nllb.translate import translate_prompt_set
from models.swinir.upscale import upscale

from typing import List
from .classes import PredictOutput, PredictResult
from .setup import ModelsPack
from models.open_clip.main import (
    open_clip_get_embeds_of_images,
    open_clip_get_embeds_of_texts,
)
from pydantic import BaseModel, Field, validator
from .helpers import get_value_if_in_list


class PredictInput(BaseModel):
    prompt: str = Field(description="Input prompt.", default="")
    negative_prompt: str = Field(description="Input negative prompt.", default="")
    width: int = Field(
        description="Width of output image.",
        default=512,
    )

    @validator("width")
    def validate_width(cls, v: int):
        return get_value_if_in_list(
            v,
            range(384, 1025, 8),
        )

    height: int = Field(
        description="Height of output image.",
        default=512,
    )

    @validator("height")
    def validate_height(cls, v: int):
        return get_value_if_in_list(
            v,
            range(384, 1025, 8),
        )

    num_outputs: int = Field(
        description="Number of images to output. If the NSFW filter is triggered, you may get fewer outputs than this.",
        ge=1,
        le=10,
        default=1,
    )
    init_image_url: str = Field(
        description="Init image url to be used with img2img.",
        default=None,
    )
    prompt_strength: float = Field(
        description="The strength of the prompt when using img2img, between 0-1. When 1, it'll essentially ignore the image.",
        ge=0,
        le=1,
        default=0.6,
    )
    num_inference_steps: int = Field(
        description="Number of denoising steps", ge=1, le=500, default=30
    )
    guidance_scale: float = Field(
        description="Scale for classifier-free guidance.", ge=1, le=20, default=7.5
    )
    scheduler: str = Field(
        default=SD_SCHEDULER_DEFAULT,
        description=f'Choose a scheduler. Defaults to "{SD_SCHEDULER_DEFAULT}".',
    )

    @validator("scheduler")
    def validate_scheduler(cls, v):
        return get_value_if_in_list(v, SD_SCHEDULER_CHOICES)

    model: str = Field(
        default=SD_MODEL_DEFAULT_KEY,
        description=f'Choose a model. Defaults to "{SD_MODEL_DEFAULT_KEY}".',
    )

    @validator("model")
    def validate_model(cls, v):
        return get_value_if_in_list(v, SD_MODEL_CHOICES)

    seed: int = Field(
        description="Random seed. Leave blank to randomize the seed.", default=None
    )
    prompt_flores_200_code: str = Field(
        description="Prompt language code (FLORES-200). It overrides the language auto-detection.",
        default=None,
    )
    negative_prompt_flores_200_code: str = Field(
        description="Negative prompt language code (FLORES-200). It overrides the language auto-detection.",
        default=None,
    )
    prompt_prefix: str = Field(description="Prompt prefix.", default=None)
    negative_prompt_prefix: str = Field(
        description="Negative prompt prefix.", default=None
    )
    output_image_extension: str = Field(
        description="Output type of the image. Can be 'png' or 'jpeg' or 'webp'.",
        default="jpeg",
    )

    @validator("output_image_extension")
    def validate_output_image_extension(cls, v):
        return get_value_if_in_list(v, ["png", "jpeg", "webp"])

    output_image_quality: int = Field(
        description="Output quality of the image. Can be 1-100.", default=90
    )
    image_to_upscale: str = Field(
        description="Input image for the upscaler (SwinIR).", default=None
    )
    process_type: str = Field(
        description="Choose a process type. Can be 'generate', 'upscale' or 'generate_and_upscale'. Defaults to 'generate'",
        default="generate",
    )

    @validator("process_type")
    def validate_process_type(cls, v):
        return get_value_if_in_list(v, ["generate", "upscale", "generate_and_upscale"])


@torch.inference_mode()
def predict(
    input: PredictInput,
    models_pack: ModelsPack,
) -> PredictResult:
    print(input.model)
    process_start = time.time()
    print("//////////////////////////////////////////////////////////////////")
    print(f"⏳ Process started: {input.process_type} ⏳")
    output_images = []
    nsfw_count = 0
    open_clip_embeds_of_images = None
    open_clip_embed_of_prompt = None

    if input.process_type == "generate" or input.process_type == "generate_and_upscale":
        t_prompt = input.prompt
        t_negative_prompt = input.negative_prompt
        [t_prompt, t_negative_prompt] = translate_prompt_set(
            text_1=input.prompt,
            flores_200_1=input.prompt_flores_200_code,
            text_2=input.negative_prompt,
            flored_200_2=input.negative_prompt_flores_200_code,
            translator=models_pack.translator,
            label="Prompt & Negative Prompt",
        )

        sd_pipe = models_pack.sd_pipes[input.model]
        settings_log_str = f"Model: {input.model} - Width: {input.width} - Height: {input.height} - Steps: {input.num_inference_steps} - Outputs: {input.num_outputs}"
        if input.init_image_url is not None:
            settings_log_str += f" - Init image: {input.init_image_url}"
        if input.prompt_strength is not None:
            settings_log_str += f" - Prompt strength: {input.prompt_strength}"
        print(f"🖥️ Generating - {settings_log_str} 🖥️")
        startTime = time.time()
        generate_output_images, generate_nsfw_count = generate(
            t_prompt,
            t_negative_prompt,
            input.prompt_prefix,
            input.negative_prompt_prefix,
            input.width,
            input.height,
            input.num_outputs,
            input.num_inference_steps,
            input.guidance_scale,
            input.init_image_url,
            input.prompt_strength,
            input.scheduler,
            input.seed,
            input.model,
            sd_pipe,
        )
        output_images = generate_output_images
        nsfw_count = generate_nsfw_count
        endTime = time.time()
        print(
            f"🖥️ Generated in {round((endTime - startTime) * 1000)} ms - {settings_log_str} 🖥️"
        )

        start_open_clip_prompt = time.time()
        open_clip_embed_of_prompt = open_clip_get_embeds_of_texts(
            [t_prompt],
            models_pack.open_clip["model"],
            models_pack.open_clip["tokenizer"],
        )[0]
        end_open_clip_prompt = time.time()
        print(
            f"📜 Open CLIP prompt embedding in: {round((end_open_clip_prompt - start_open_clip_prompt) * 1000)} ms 📜"
        )

        if len(output_images) > 0:
            start_open_clip_image = time.time()
            open_clip_embeds_of_images = open_clip_get_embeds_of_images(
                output_images,
                models_pack.open_clip["model"],
                models_pack.open_clip["processor"],
            )
            end_open_clip_image = time.time()
            print(
                f"🖼️ Open CLIP image embeddings in: {round((end_open_clip_image - start_open_clip_image) * 1000)} ms - {len(output_images)} images 🖼️"
            )
        else:
            open_clip_embeds_of_images = []
            print(
                "🖼️ No non-NSFW images generated. Skipping Open CLIP image embeddings. 🖼️"
            )

    if input.process_type == "upscale" or input.process_type == "generate_and_upscale":
        startTime = time.time()
        if input.process_type == "upscale":
            upscale_output_image = upscale(input.image_to_upscale, models_pack.upscaler)
            output_images = [upscale_output_image]
        else:
            upscale_output_images = []
            for image in output_images:
                upscale_output_image = upscale(image, models_pack.upscaler)
                upscale_output_images.append(upscale_output_image)
            output_images = upscale_output_images
        endTime = time.time()
        print(f"⭐️ Upscaled in: {round((endTime - startTime) * 1000)} ms ⭐️")

    # Prepare output objects
    output_objects: List[PredictOutput] = []
    for i, image in enumerate(output_images):
        obj = PredictOutput(
            pil_image=image,
            target_quality=input.output_image_quality,
            target_extension=input.output_image_extension,
            open_clip_image_embed=open_clip_embeds_of_images[i]
            if open_clip_embeds_of_images is not None
            else None,
            open_clip_prompt_embed=open_clip_embed_of_prompt
            if open_clip_embed_of_prompt is not None
            else None,
        )
        output_objects.append(obj)

    result = PredictResult(
        outputs=output_objects,
        nsfw_count=nsfw_count,
    )
    process_end = time.time()
    print(f"✅ Process completed in: {round((process_end - process_start) * 1000)} ms ✅")
    print("//////////////////////////////////////////////////////////////////")

    return result
