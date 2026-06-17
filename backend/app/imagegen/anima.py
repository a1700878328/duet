"""Anima DiT (AuraFlow-arch anime 2B) image-gen path — multi-person priority.

Why this exists: the SDXL pipeline (workflows.py) needs AttentionCouple +
SolidMask region splitting to place two characters, which is brittle for 2-3
people. Anima is a DiT that handles multi-person composition *natively* from a
single positive prompt, so "2 characters, X on the left, Y on the right" just
works without region masks. SDXL stays as the fallback.

Core graph (reproduced from Anima_Story_FaceID_IPAdapter_v1.json, FaceID/IPAdapter
and LLLite branches stripped — v1 is the reliable core only):

    AnimaBoosterLoader(anima-base-v1.0)            -> MODEL
      -> ModelSamplingAuraFlow(shift=3.0)          -> MODEL
      -> LoraLoaderModelOnly(anima-turbo @0.8)
      -> LoraLoaderModelOnly(ntrmix style @1.0)    -> MODEL ─┐
    CLIPLoader(qwen_3_06b_base, stable_diffusion)  -> CLIP   │
      -> CLIPTextEncode(positive)                  -> COND   │
      -> CLIPTextEncode(negative)                  -> COND   │
    AnimaLatentImage(width,height)                 -> LATENT │
      -> KSampler(steps=12,cfg=1,er_sde,beta57)    <─────────┘
      -> VAEDecode(qwen_image_vae)                 -> IMAGE
      -> VAEEncode -> KSampler(6,cfg=1,euler,kl_optimal,denoise=.45)
      -> VAEDecode(qwen_image_vae)                 -> IMAGE
      -> SaveImage

Node quirks worth knowing:
- AnimaBoosterLoader outputs MODEL **only** (no CLIP/VAE bundled) — CLIP and VAE
  are loaded separately, unlike CheckpointLoaderSimple in the SDXL path.
- CLIP is a Qwen3-0.6B text encoder loaded via CLIPLoader with type
  "stable_diffusion" (the Anima build registers it under that type).
- AuraFlow/DiT wants **low CFG**: turbo LoRA + cfg=1, sampler er_sde,
  scheduler beta57, then a low-denoise second pass (豹豹喵呜 reference).
- ModelSamplingAuraFlow shift=3.0 (reference value; node default is 1.73).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from . import media
from .client import ensure_comfyui
from .config import COMFY_URL

MEDIA_DIR = media.MEDIA_DIR
MEDIA_URL_PREFIX = media.MEDIA_URL_PREFIX
save_png = media.save_png


def char_seed(room_id: int, name: str) -> int:
    """同一角色（房间+名字）恒得同一 seed → 立绘与场景图人物更一致。

    无 LoRA/FaceID 时，固定 seed + 同一外貌 tag 是基模保持人物一致的主要手段。
    """
    h = hashlib.sha1(f"{room_id}\x00{name}".encode()).hexdigest()
    return int(h[:8], 16)


Graph = dict[str, dict[str, Any]]

# === Anima model files (verified present via /object_info) ===
ANIMA_MODEL = "anima-base-v1.0.safetensors"
ANIMA_TURBO_LORA = "anima-turbo-lora-v0.2.safetensors"
ANIMA_NTRMIX_LORA = "ntrmix_style_anima_b1_v1.safetensors"
ANIMA_NTRMIX_TRIGGER = "@ntrmixstyle"
ANIMA_CLIP = "qwen_3_06b_base.safetensors"
ANIMA_CLIP_TYPE = "stable_diffusion"
ANIMA_VAE = "qwen_image_vae.safetensors"

# === Sampler params (high quality — 30 steps CFG 4, no turbo by default) ===
ANIMA_STEPS = 30
ANIMA_CFG = 4.0
ANIMA_SAMPLER = "er_sde"
ANIMA_SCHEDULER = "beta57"
ANIMA_REFINER_STEPS = 8
ANIMA_REFINER_CFG = 4.0
ANIMA_REFINER_SAMPLER = "euler"
ANIMA_REFINER_SCHEDULER = "kl_optimal"
ANIMA_REFINER_DENOISE = 0.4
ANIMA_SHIFT = 3.0
ANIMA_TURBO_STRENGTH = 0.0  # disabled by default
ANIMA_NTRMIX_STRENGTH = 1.0
# Upscale tile refine targets. Keep this aligned with the verified Anima/NTRMix
# tutorial API prompt rather than pushing to an over-large long edge.
ANIMA_UPSCALE_PRE_SIZE = 1024
ANIMA_UPSCALE_TARGET = 1824

# === Default sizes (multiples of 16, AuraFlow requirement) ===
PORTRAIT_WIDTH = 832
PORTRAIT_HEIGHT = 1216
LANDSCAPE_WIDTH = 1216
LANDSCAPE_HEIGHT = 832

# A light default negative; callers may extend it.
DEFAULT_NEGATIVE = (
    "score_1, score_2, score_3, bad anatomy, bad proportions, deformed anatomy, "
    "deformed face, deformed eyes, bad hands, multiple fingers, missing fingers, "
    "extra fingers, fewer digits, cropped, worst quality, low quality, lowres, "
    "jpeg artifacts, watermark, username, signature, sketch, text, speech bubble, "
    "caption, photorealistic, realistic, conjoined, "
    "bad ai-generated, 3d render, cgi, semi-realistic, live action, western comic, "
    "oil painting, painterly, plastic skin, shiny clothes, shiny skin, gold skin, "
    "halo, three hands"
)

BAOBAO_QUALITY_CORE = (
    "best quality, score_9, score_8, score_7, highres, absurdres, 2D anime screenshot, "
    "Japanese TV anime style, clean anime line art, polished cel shading, "
    "flat anime coloring, crisp expressive eyes, official art"
)
BAOBAO_QUALITY_PREFIX = f"{ANIMA_NTRMIX_TRIGGER}, {BAOBAO_QUALITY_CORE}"
_DEFAULT_TEMPLATE_DIR = Path(
    r"C:\Users\a1700\Documents\ComfyUI\user\default\workflows\Active_Strong"
)
ANIMA_NTRMIX_FACE_STYLE_API_PROMPT = (
    Path(settings.anima_workflow_template_path)
    if settings.anima_workflow_template_path
    else _DEFAULT_TEMPLATE_DIR
    / "FINAL_Anima_NTRMix_FaceStyle_Single_UltraTile1824.api-prompt.txt"
)


def _remove_ntrmix_trigger(text: str) -> str:
    return (
        text.replace(f"{ANIMA_NTRMIX_TRIGGER},", "")
        .replace(ANIMA_NTRMIX_TRIGGER, "")
        .strip(" ,")
    )


def _with_anima_style_prefix(positive: str, *, use_ntrmix: bool = True) -> str:
    """Ensure LoRA trigger + quality prefix; pass through if AI already has them."""
    text = positive.strip()
    if not use_ntrmix:
        return _remove_ntrmix_trigger(text)
    if "score_9" in text or "best quality" in text:
        if ANIMA_NTRMIX_TRIGGER in text:
            return text
        return f"{ANIMA_NTRMIX_TRIGGER}, {text}"
    prefix = BAOBAO_QUALITY_PREFIX if use_ntrmix else BAOBAO_QUALITY_CORE
    return f"{prefix}, {text}" if text else prefix


def _load_api_prompt_template(path: Path) -> Graph:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_original_ntrmix_workflow(
    positive: str,
    negative: str = "",
    *,
    width: int = PORTRAIT_WIDTH,
    height: int = PORTRAIT_HEIGHT,
    seed: int | None = None,
    upscale: bool = False,
    tile_refine: bool = True,
    output_prefix: str = "DUET_ANIMA_NTRMIX_ORIGINAL",
) -> Graph:
    """Load the verified Anima/NTRMix API prompt and patch only runtime inputs."""
    if seed is None:
        seed = random.randint(1, 2**32 - 1)
    width = max(64, (width // 8) * 8)
    height = max(64, (height // 8) * 8)
    g = copy.deepcopy(_load_api_prompt_template(ANIMA_NTRMIX_FACE_STYLE_API_PROMPT))
    g["54"]["inputs"]["text"] = _remove_ntrmix_trigger(positive)
    if negative:
        g["62"]["inputs"]["text"] = f"{g['62']['inputs']['text']}, {negative}"
    g["159"]["inputs"]["自定义宽"] = width
    g["159"]["inputs"]["自定义高"] = height
    g["57"]["inputs"]["seed"] = seed
    g["134"]["inputs"]["seed"] = seed + 1000000
    g["180"]["inputs"]["filename_prefix"] = f"{output_prefix}_ULTRASHARP_PRE"
    g["169"]["inputs"]["filename_prefix"] = f"{output_prefix}_REFINED"
    if not upscale:
        for node_id in (
            "164",
            "161",
            "162",
            "165",
            "166",
            "129",
            "130",
            "131",
            "132",
            "141",
            "136",
            "134",
            "137",
            "142",
            "139",
            "180",
        ):
            g.pop(node_id, None)
        g["169"]["inputs"]["images"] = ["64", 0]
        g["169"]["inputs"]["filename_prefix"] = output_prefix
    elif not tile_refine:
        for node_id in (
            "166",
            "129",
            "130",
            "131",
            "132",
            "141",
            "136",
            "134",
            "137",
            "142",
            "139",
        ):
            g.pop(node_id, None)
        g["169"]["inputs"]["images"] = ["165", 0]
    return g


def build_anima_workflow(
    positive: str,
    negative: str = "",
    *,
    width: int = PORTRAIT_WIDTH,
    height: int = PORTRAIT_HEIGHT,
    seed: int | None = None,
    steps: int = ANIMA_STEPS,
    cfg: float = ANIMA_CFG,
    use_turbo: bool = False,
    use_ntrmix: bool = True,
    ntrmix_strength: float = ANIMA_NTRMIX_STRENGTH,
    use_teacache: bool = True,
    second_pass: bool = True,
    upscale: bool = False,
    output_prefix: str = "DUET_ANIMA",
) -> Graph:
    """Build an API-format ComfyUI graph for the core Anima DiT generation chain.

    Multi-person is handled natively by the DiT: just describe several characters
    in ``positive`` (e.g. "2 characters, A on the left, B on the right"). No region
    masks. ``width``/``height`` are snapped to the nearest multiple of 16.
    """
    if seed is None:
        seed = random.randint(1, 2**32 - 1)

    # AuraFlow latents must be multiples of 16.
    width = max(64, (width // 16) * 16)
    height = max(64, (height // 16) * 16)

    positive = _with_anima_style_prefix(positive, use_ntrmix=use_ntrmix)
    neg = DEFAULT_NEGATIVE if not negative else f"{DEFAULT_NEGATIVE}, {negative}"

    g: Graph = {
        # --- Model: Anima base -> AuraFlow shift -> (turbo lora) ---
        "1": {
            "class_type": "AnimaBoosterLoader",
            "inputs": {
                "model_name": ANIMA_MODEL,
                "sage_attention": "auto",
                "torch_compile": False,
            },
        },
        "2": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {
                "model": ["16", 0] if use_teacache else ["1", 0],
                "shift": ANIMA_SHIFT,
            },
        },
        # --- Text encoder (separate from the booster loader) ---
        "4": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": ANIMA_CLIP,
                "type": ANIMA_CLIP_TYPE,
                "device": "default",
            },
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 0], "text": positive},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 0], "text": neg},
        },
        # --- VAE (separate) ---
        "7": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": ANIMA_VAE},
        },
        # --- Latent (DiT-native resolution, multiple of 16) ---
        "8": {
            "class_type": "AnimaLatentImage",
            "inputs": {
                "preset": "Custom",
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        "10": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["9", 0], "vae": ["7", 0]},
        },
        "11": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": output_prefix, "images": ["10", 0]},
        },
    }
    if use_teacache:
        g["16"] = {
            "class_type": "AnimaTeaCache",
            "inputs": {
                "model": ["1", 0],
                "threshold": 0.15,
                "teacache_version": "v1 (Legacy Fast)",
                "adaptive_mode": True,
                "early_steps_factor": 0.4,
                "late_steps_factor": 1.8,
                "start_percent": 0.0,
                "end_percent": 1.0,
                "cache_device": "cuda",
            },
        }

    # Optional turbo LoRA (model-only — booster loader emits no CLIP).
    if use_turbo:
        g["3"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["2", 0],
                "lora_name": ANIMA_TURBO_LORA,
                "strength_model": ANIMA_TURBO_STRENGTH,
            },
        }
        model_ref = ["3", 0]
    else:
        model_ref = ["2", 0]
    if use_ntrmix:
        g["23"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": model_ref,
                "lora_name": ANIMA_NTRMIX_LORA,
                "strength_model": ntrmix_strength,
            },
        }
        model_ref = ["23", 0]

    sampler_model_ref = model_ref

    g["9"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": ANIMA_SAMPLER,
            "scheduler": ANIMA_SCHEDULER,
            "denoise": 1.0,
            "model": sampler_model_ref,
            "positive": ["5", 0],
            "negative": ["6", 0],
            "latent_image": ["8", 0],
        },
    }
    final_image_ref: list[Any] = ["10", 0]
    if second_pass:
        g["17"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["10", 0], "vae": ["7", 0]},
        }
        g["18"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": ANIMA_REFINER_STEPS,
                "cfg": ANIMA_REFINER_CFG,
                "sampler_name": ANIMA_REFINER_SAMPLER,
                "scheduler": ANIMA_REFINER_SCHEDULER,
                "denoise": ANIMA_REFINER_DENOISE,
                "model": model_ref,
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["17", 0],
            },
        }
        g["19"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["18", 0], "vae": ["7", 0]},
        }
        final_image_ref = ["19", 0]

    if upscale:
        g["20"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": "4x-UltraSharp.pth"},
        }
        g["21"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["20", 0], "image": final_image_ref},
        }
        g["22"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["21", 0],
                "upscale_method": "lanczos",
                "width": width * 2,
                "height": height * 2,
                "crop": "disabled",
            },
        }
        g["11"]["inputs"]["images"] = ["22", 0]
    else:
        g["11"]["inputs"]["images"] = final_image_ref
    return g


def build_baobao_anima_workflow(
    positive: str,
    negative: str = "",
    *,
    width: int = PORTRAIT_WIDTH,
    height: int = PORTRAIT_HEIGHT,
    seed: int | None = None,
    use_ntrmix: bool = True,
    ntrmix_strength: float = ANIMA_NTRMIX_STRENGTH,
    use_turbo: bool = False,
    upscale: bool = False,
    tile_refine: bool = True,
    output_prefix: str = "DUET_ANIMA",
) -> Graph:
    """High-quality Anima DiT workflow — 30 steps, CFG 4, ntrmix LoRA, optional
    4x-UltraSharp upscale with tile refine.

    Multi-person is handled natively by the DiT: describe several characters in
    the positive prompt. No region masks needed.

    When ``use_turbo=False`` (default), the turbo LoRA is omitted and the ntrmix
    style LoRA loads directly on the base model. When ``tile_refine=True`` and
    ``upscale=True``, the upscaled image is split into tiles, each tile refined
    via a second KSampler pass, then reassembled for maximum detail.
    """
    if use_ntrmix:
        return build_original_ntrmix_workflow(
            positive,
            negative,
            width=width,
            height=height,
            seed=seed,
            upscale=upscale,
            tile_refine=tile_refine,
            output_prefix=output_prefix,
        )
    if seed is None:
        seed = random.randint(1, 2**32 - 1)
    width = max(64, (width // 8) * 8)
    height = max(64, (height // 8) * 8)
    if not use_ntrmix:
        positive = _remove_ntrmix_trigger(positive)
    neg = DEFAULT_NEGATIVE if not negative else f"{DEFAULT_NEGATIVE}, {negative}"

    g: Graph = {
        "55": {
            "class_type": "AnimaBoosterLoader",
            "inputs": {
                "model_name": ANIMA_MODEL,
                "sage_attention": "auto",
                "torch_compile": False,
            },
        },
        "56": {
            "class_type": "AnimaTeaCache",
            "inputs": {
                "model": ["55", 0],
                "threshold": 0.15,
                "teacache_version": "v1 (Legacy Fast)",
                "adaptive_mode": True,
                "early_steps_factor": 0.4,
                "late_steps_factor": 1.8,
                "start_percent": 0.0,
                "end_percent": 1.0,
                "cache_device": "cuda",
            },
        },
        "60": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["56", 0], "shift": 3},
        },
        # ntrmix LoRA (always on unless use_ntrmix=False)
        "4": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["60", 0] if not use_turbo else ["3", 0],
                "lora_name": ANIMA_NTRMIX_LORA,
                "strength_model": ntrmix_strength,
            },
        },
        "58": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": ANIMA_CLIP,
                "type": ANIMA_CLIP_TYPE,
                "device": "default",
            },
        },
        "59": {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}},
        "69": {"class_type": "CR Text", "inputs": {"text": ""}},
        "68": {
            "class_type": "CR Text",
            "inputs": {
                "text": BAOBAO_QUALITY_PREFIX if use_ntrmix else BAOBAO_QUALITY_CORE
            },
        },
        "54": {"class_type": "CR Text", "inputs": {"text": positive}},
        "73": {
            "class_type": "Text Concatenate",
            "inputs": {
                "text_a": ["69", 0],
                "text_b": ["68", 0],
                "text_c": ["54", 0],
                "delimiter": ", ",
                "clean_whitespace": "false",
            },
        },
        "61": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["58", 0], "text": ["73", 0]},
        },
        "62": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["58", 0], "text": neg},
        },
        "159": {
            "class_type": "WJILatentPreset",
            "inputs": {
                "预设分辨率": "自定义",
                "横竖对调": False,
                "批量大小": 1,
                "自定义宽": width,
                "自定义高": height,
                "缩放倍数": "8",
            },
        },
        "57": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["3", 0],
                "positive": ["61", 0],
                "negative": ["62", 0],
                "latent_image": ["159", 0],
                "seed": seed,
                "steps": ANIMA_STEPS,
                "cfg": ANIMA_CFG,
                "sampler_name": ANIMA_SAMPLER,
                "scheduler": ANIMA_SCHEDULER,
                "denoise": 1.0,
            },
        },
        "64": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["57", 0], "vae": ["59", 0]},
        },
        "168": {
            "class_type": "SaveImage",
            "inputs": {"images": ["64", 0], "filename_prefix": output_prefix},
        },
    }
    base_model_ref: list[Any] = (
        ["4", 0] if use_ntrmix else (["3", 0] if use_turbo else ["60", 0])
    )
    g["57"]["inputs"]["model"] = base_model_ref
    if use_turbo:
        g["3"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["60", 0],
                "lora_name": ANIMA_TURBO_LORA,
                "strength_model": ANIMA_TURBO_STRENGTH,
            },
        }
        g["4"]["inputs"]["model"] = ["3", 0]
    if not use_ntrmix:
        g.pop("4", None)
    model_ref_for_refine = base_model_ref

    if upscale:
        g["164"] = {
            "class_type": "easy imageScaleDownToSize",
            "inputs": {
                "images": ["64", 0],
                "size": ANIMA_UPSCALE_PRE_SIZE,
                "mode": True,
            },
        }
        g["161"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": "4x-UltraSharp.pth"},
        }
        g["162"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["161", 0], "image": ["164", 0]},
        }
        g["165"] = {
            "class_type": "easy imageScaleDownToSize",
            "inputs": {
                "images": ["162", 0],
                "size": ANIMA_UPSCALE_TARGET,
                "mode": True,
            },
        }

        if tile_refine:
            # Tile refine: split upscaled image → VAEEncode each tile → KSampler
            # refine → VAEDecode → assemble
            g["166"] = {
                "class_type": "GetImageSize",
                "inputs": {"image": ["165", 0]},
            }
            g["129"] = {
                "class_type": "MathExpression|pysssss",
                "inputs": {
                    "a": ["166", 0],
                    "expression": "(a+1279)//1280+int(a%1280==0)",
                },
            }
            g["130"] = {
                "class_type": "MathExpression|pysssss",
                "inputs": {
                    "a": ["166", 1],
                    "expression": "(a+1279)//1280+int(a%1280==0)",
                },
            }
            g["131"] = {
                "class_type": "TTP_Tile_image_size",
                "inputs": {
                    "image": ["165", 0],
                    "width_factor": ["129", 0],
                    "height_factor": ["130", 0],
                    "overlap_rate": 0.2,
                },
            }
            g["132"] = {
                "class_type": "TTP_Image_Tile_Batch",
                "inputs": {
                    "image": ["165", 0],
                    "tile_width": ["131", 0],
                    "tile_height": ["131", 1],
                },
            }
            g["141"] = {
                "class_type": "easy imageBatchToImageList",
                "inputs": {"image": ["132", 0]},
            }
            g["136"] = {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["141", 0], "vae": ["59", 0]},
            }
            g["134"] = {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed + 1000000,
                    "steps": ANIMA_REFINER_STEPS,
                    "cfg": ANIMA_REFINER_CFG,
                    "sampler_name": ANIMA_REFINER_SAMPLER,
                    "scheduler": ANIMA_REFINER_SCHEDULER,
                    "denoise": ANIMA_REFINER_DENOISE,
                    "model": model_ref_for_refine,
                    "positive": ["61", 0],
                    "negative": ["62", 0],
                    "latent_image": ["136", 0],
                },
            }
            g["137"] = {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["134", 0], "vae": ["59", 0]},
            }
            g["142"] = {
                "class_type": "ImageListToBatch+",
                "inputs": {"image": ["137", 0]},
            }
            g["139"] = {
                "class_type": "TTP_Image_Assy",
                "inputs": {
                    "tiles": ["142", 0],
                    "positions": ["132", 1],
                    "original_size": ["132", 2],
                    "grid_size": ["132", 3],
                    "padding": 128,
                },
            }
            g["169"] = {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["139", 0],
                    "filename_prefix": (
                        f"{output_prefix}_TILE_REFINED_{ANIMA_UPSCALE_TARGET}"
                    ),
                },
            }
            g["168"]["inputs"]["images"] = ["165", 0]
            g["168"]["inputs"]["filename_prefix"] = (
                f"{output_prefix}_ULTRASHARP_PRE_{ANIMA_UPSCALE_TARGET}"
            )
        else:
            g["168"]["inputs"]["images"] = ["165", 0]
    return g


async def _submit_and_fetch(
    workflow: Graph,
    *,
    timeout_sec: int = 600,
    poll_interval: float = 3.0,
) -> dict[str, Any]:
    """POST /prompt, poll /history, fetch the first output image via /view.

    Replicates client.submit_and_wait but without the SDXL color/named-char guard
    (the Anima path takes free-form prompts). Returns {bytes,filename,prompt_id}
    or {error}. Never raises.
    """
    # ComfyUI 偶尔崩 → 先经 manager 自动拉起，自愈。
    try:
        await ensure_comfyui()
    except Exception:
        pass
    client_id = f"duet-anima-{int(time.time())}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{COMFY_URL}/prompt",
                json={"prompt": workflow, "client_id": client_id},
                timeout=30,
            )
        except Exception as e:
            return {"error": f"提交失败: {e}"}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"提交失败 HTTP {resp.status_code}: {resp.text[:500]}"}
        if result.get("node_errors"):
            return {"error": f"节点错误: {result['node_errors']}"}

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"error": f"无 prompt_id: {result}"}

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            try:
                h = (
                    await client.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10)
                ).json()
            except Exception:
                continue
            if prompt_id not in h:
                continue
            entry = h[prompt_id]
            status = entry.get("status", {}).get("status_str", "")
            if status == "success":
                candidates: list[dict[str, Any]] = []
                for node_id, out in entry.get("outputs", {}).items():
                    for img in out.get("images", []):
                        item = dict(img)
                        item["_node_id"] = str(node_id)
                        candidates.append(item)
                candidates.sort(
                    key=lambda img: (
                        img.get("_node_id") != "169",
                        "REFINED" not in str(img.get("filename", "")).upper(),
                    )
                )
                for img in candidates:
                    img_r = await client.get(
                        f"{COMFY_URL}/view",
                        params={
                            "filename": img["filename"],
                            "type": img.get("type", "output"),
                            "subfolder": img.get("subfolder", ""),
                        },
                        timeout=60,
                    )
                    return {
                        "bytes": img_r.content,
                        "filename": img["filename"],
                        "prompt_id": prompt_id,
                    }
                return {"error": "成功但无输出图片", "prompt_id": prompt_id}
            if status == "error":
                msgs = entry.get("status", {}).get("messages", [])
                for mt, md in msgs:
                    if mt == "execution_error":
                        return {
                            "error": md.get("exception_message", "未知错误"),
                            "prompt_id": prompt_id,
                        }
                return {"error": "执行错误", "prompt_id": prompt_id}
        return {"error": "超时", "prompt_id": prompt_id}



async def generate_anima(
    positive: str,
    negative: str = "",
    *,
    width: int = PORTRAIT_WIDTH,
    height: int = PORTRAIT_HEIGHT,
    seed: int | None = None,
    landscape: bool = False,
    use_turbo: bool = False,
    use_ntrmix: bool = True,
    ntrmix_strength: float = ANIMA_NTRMIX_STRENGTH,
    upscale: bool = False,
    tile_refine: bool = True,
) -> dict[str, Any]:
    """Generate one Anima image. Multi-person = multiple chars in ``positive``.

    Returns {url, path, filename, prompt_id} on success or {error} on any failure.
    Never raises. Pass ``landscape=True`` for the 1216x832 multi-person default
    (good for 2-3 characters side by side), or set width/height explicitly.

    Default is high quality: 30 steps, CFG 4, ntrmix LoRA only (no turbo),
    with 4x-UltraSharp upscale and tile refine.
    """
    if landscape and width == PORTRAIT_WIDTH and height == PORTRAIT_HEIGHT:
        width, height = LANDSCAPE_WIDTH, LANDSCAPE_HEIGHT

    try:
        workflow = build_baobao_anima_workflow(
            positive,
            negative,
            width=width,
            height=height,
            seed=seed,
            use_ntrmix=use_ntrmix,
            ntrmix_strength=ntrmix_strength,
            use_turbo=use_turbo,
            upscale=upscale,
            tile_refine=tile_refine,
        )
    except Exception as e:  # build is pure, but never raise out of the entrypoint
        return {"error": f"构图失败: {e}"}

    result = await _submit_and_fetch(workflow)
    if result.get("error"):
        return {"error": result["error"], "prompt_id": result.get("prompt_id")}

    image_bytes = result.get("bytes")
    if not image_bytes:
        return {"error": "成功但无图片字节"}

    name, path = save_png(image_bytes)
    return {
        "url": f"{MEDIA_URL_PREFIX}/{name}",
        "path": str(path),
        "filename": name,
        "prompt_id": result.get("prompt_id"),
    }
