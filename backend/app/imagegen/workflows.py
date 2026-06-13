"""ComfyUI graph builders — ported from rp_system/image_gen.py.

Single: 832x1216, clip-skip 2, 2-pass KSampler (28 steps cfg5 euler_ancestral
denoise 1.0 -> LatentUpscaleBy bicubic 1.5x -> 12 steps denoise 0.35), VAEDecodeTiled.
Duo: 1216x832, 43-node AttentionCouple ("Attention couple") with left/right SolidMask
split + ConditioningSetMask, dual LoRA 0.70, optional OpenPose ControlNet.

POSIX /tmp writes removed — results are fetched via /view by the client.
"""

from __future__ import annotations

import random
from typing import Any

from .config import (
    CHARACTER_LORAS,
    CHECKPOINT,
    DUO_LORA_STRENGTH,
    MAX_TOKENS,
    NEGATIVE_PROMPT,
    OPENPOSE_CONTROLNET,
    SINGLE_HEIGHT,
    SINGLE_LORA_STRENGTH,
    SINGLE_WIDTH,
    STYLE_PREFIX,
    STYLE_SUFFIX,
)
from .guard import registry_wrong_color_negatives

Graph = dict[str, dict[str, Any]]


def _estimate_tokens(text: str) -> int:
    tags = [t.strip() for t in text.split(",") if t.strip()]
    return max(len(tags), len(text) // 4)


def _check_token_limit(text: str, name: str, max_tokens: int = MAX_TOKENS) -> None:
    t = _estimate_tokens(text)
    if t > max_tokens:
        tags = [x.strip() for x in text.split(",") if x.strip()]
        if len(tags) > 42:  # ~40 tags ~= 75 token, with margin
            raise ValueError(
                f"{name}: ~{t} token ({len(tags)} tags) exceeds {max_tokens} limit"
            )


def build_single_workflow(
    char_name: str,
    scene_desc: str,
    seed: int | None = None,
    nsfw: bool = False,
    output_prefix: str = "DUET_SINGLE",
) -> Graph:
    """Single-char txt2img (2-pass). Iron rule: slot holds trigger only, no colors."""
    if seed is None:
        seed = random.randint(10000, 99999)

    char = CHARACTER_LORAS.get(char_name)
    if not char:
        raise ValueError(f"未知角色: {char_name}")

    nsfw_tag = "(nsfw:1.2), " if nsfw else ""
    trigger = char["trigger"]

    pos = f"{STYLE_PREFIX}, {nsfw_tag}{trigger}, {scene_desc}, {STYLE_SUFFIX}"
    neg = NEGATIVE_PROMPT
    wcn = registry_wrong_color_negatives(char_name)
    if wcn:
        neg = f"{neg}, {wcn}"

    _check_token_limit(pos, "正向提示词")

    s = SINGLE_LORA_STRENGTH
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": char["file"],
                "strength_model": s,
                "strength_clip": s,
            },
        },
        "2c": {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["2", 1], "stop_at_clip_layer": -2},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2c", 0], "text": pos},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2c", 0], "text": neg},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": SINGLE_WIDTH, "height": SINGLE_HEIGHT, "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 28,
                "cfg": 5.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["2", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "LatentUpscaleBy",
            "inputs": {
                "upscale_method": "bicubic",
                "scale_by": 1.5,
                "samples": ["6", 0],
            },
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 12,
                "cfg": 4.5,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 0.35,
                "model": ["2", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["7", 0],
            },
        },
        "9": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["8", 0],
                "vae": ["1", 2],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": output_prefix, "images": ["9", 0]},
        },
    }


def build_raw_single_workflow(
    positive: str,
    negative: str = "",
    *,
    landscape: bool = False,
    seed: int | None = None,
    output_prefix: str = "DUET_RAW_SINGLE",
) -> Graph:
    """LoRA-less single txt2img off the base checkpoint (oneObsession_v18).

    Same quality params as build_single_workflow (clip-skip -2, 2-pass KSampler ->
    bicubic 1.5x upscale -> denoise pass, VAEDecodeTiled) but no LoRA loader — pure
    prompt. The config style prefix/suffix and base negative are folded in.
    """
    if seed is None:
        seed = random.randint(10000, 99999)

    pos = f"{STYLE_PREFIX}, {positive}, {STYLE_SUFFIX}"
    neg = NEGATIVE_PROMPT if not negative else f"{NEGATIVE_PROMPT}, {negative}"

    width, height = (
        (SINGLE_HEIGHT, SINGLE_WIDTH) if landscape else (SINGLE_WIDTH, SINGLE_HEIGHT)
    )

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        "1c": {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1c", 0], "text": pos},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1c", 0], "text": neg},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 28,
                "cfg": 5.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "LatentUpscaleBy",
            "inputs": {
                "upscale_method": "bicubic",
                "scale_by": 1.5,
                "samples": ["6", 0],
            },
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 12,
                "cfg": 4.5,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 0.35,
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["7", 0],
            },
        },
        "9": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["8", 0],
                "vae": ["1", 2],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": output_prefix, "images": ["9", 0]},
        },
    }


def build_duo_workflow(
    char_a_name: str,
    char_b_name: str,
    scene_global: str = "",
    scene_left: str = "",
    scene_right: str = "",
    seed: int | None = None,
    nsfw: bool = False,
    pose_image: str | None = None,
    output_prefix: str = "DUET_DUO",
) -> Graph:
    """Dual-char AttentionCouple workflow with left/right mask split.

    Prompt discipline: global = style+scene only (no colors); left/right = trigger
    + action only. When no pose image is provided, ControlNet nodes are omitted and
    AttentionCouple wires directly to the combined conditioning (no placeholder file).
    """
    if seed is None:
        seed = random.randint(10000, 99999)

    char_a = CHARACTER_LORAS.get(char_a_name)
    char_b = CHARACTER_LORAS.get(char_b_name)
    if not char_a:
        raise ValueError(f"未知角色A: {char_a_name}")
    if not char_b:
        raise ValueError(f"未知角色B: {char_b_name}")

    lora_strength = DUO_LORA_STRENGTH
    nsfw_tag = "(nsfw:1.2), " if nsfw else ""

    global_pos = (
        f"{STYLE_PREFIX}, {nsfw_tag}2girls, multiple girls, {scene_global}, "
        f"{STYLE_SUFFIX}"
    )
    left_pos = f"left, {scene_left}, {char_a['trigger']}"
    right_pos = f"right, {scene_right}, {char_b['trigger']}"
    neg = NEGATIVE_PROMPT

    _check_token_limit(global_pos, "Global 段")
    _check_token_limit(left_pos, "Left 段")
    _check_token_limit(right_pos, "Right 段")

    wf: Graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": char_a["file"],
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            },
        },
        "3": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["2", 0],
                "clip": ["2", 1],
                "lora_name": char_b["file"],
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            },
        },
        "3c": {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["3", 1], "stop_at_clip_layer": -2},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["3c", 0], "text": global_pos},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["3c", 0], "text": left_pos},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["3c", 0], "text": right_pos},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["3c", 0], "text": neg},
        },
        # --- Base stage masks (left/right split at x=608) ---
        "900": {
            "class_type": "SolidMask",
            "inputs": {"value": 0.0, "width": 1216, "height": 832},
        },
        "901": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 608, "height": 832},
        },
        "902": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 608, "height": 832},
        },
        "903": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["900", 0],
                "source": ["901", 0],
                "x": 0,
                "y": 0,
                "operation": "add",
            },
        },
        "904": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["900", 0],
                "source": ["902", 0],
                "x": 608,
                "y": 0,
                "operation": "add",
            },
        },
        "905": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 1216, "height": 832},
        },
        # --- ConditioningSetMask x4 ---
        "906": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["4", 0],
                "mask": ["905", 0],
                "strength": 0.45,
                "set_cond_area": "default",
            },
        },
        "907": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["7", 0],
                "mask": ["905", 0],
                "strength": 1.0,
                "set_cond_area": "default",
            },
        },
        "8": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["5", 0],
                "mask": ["903", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        "9": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["6", 0],
                "mask": ["904", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        # --- ConditioningCombine ---
        "10": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["906", 0], "conditioning_2": ["8", 0]},
        },
        "11": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["10", 0], "conditioning_2": ["9", 0]},
        },
        # --- EmptyLatent + base KSampler ---
        "20": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1216, "height": 832, "batch_size": 1},
        },
        # --- Hires masks (1824x1248, split at x=912) ---
        "910": {
            "class_type": "SolidMask",
            "inputs": {"value": 0.0, "width": 1824, "height": 1248},
        },
        "911": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 912, "height": 1248},
        },
        "912": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 912, "height": 1248},
        },
        "913": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["910", 0],
                "source": ["911", 0],
                "x": 0,
                "y": 0,
                "operation": "add",
            },
        },
        "914": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["910", 0],
                "source": ["912", 0],
                "x": 912,
                "y": 0,
                "operation": "add",
            },
        },
        "915": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 1824, "height": 1248},
        },
        "916": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["4", 0],
                "mask": ["915", 0],
                "strength": 0.45,
                "set_cond_area": "default",
            },
        },
        "917": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["7", 0],
                "mask": ["915", 0],
                "strength": 1.0,
                "set_cond_area": "default",
            },
        },
        "14": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["5", 0],
                "mask": ["913", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        "15": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["6", 0],
                "mask": ["914", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        "16": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["916", 0], "conditioning_2": ["14", 0]},
        },
        "17": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["16", 0], "conditioning_2": ["15", 0]},
        },
        "22": {
            "class_type": "LatentUpscaleBy",
            "inputs": {
                "upscale_method": "bicubic",
                "scale_by": 1.5,
                "samples": ["21", 0],
            },
        },
        "24": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["23", 0],
                "vae": ["1", 2],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        },
        "25": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": output_prefix, "images": ["24", 0]},
        },
    }

    if pose_image:
        # ControlNet path: OpenPose with active strength.
        wf["800"] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": OPENPOSE_CONTROLNET},
        }
        wf["801"] = {"class_type": "LoadImage", "inputs": {"image": pose_image}}
        wf["12"] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["11", 0],
                "negative": ["907", 0],
                "control_net": ["800", 0],
                "image": ["801", 0],
                "strength": 0.85,
                "start_percent": 0.0,
                "end_percent": 0.7,
            },
        }
        wf["13"] = {
            "class_type": "Attention couple",
            "inputs": {
                "model": ["3", 0],
                "positive": ["12", 0],
                "negative": ["12", 1],
                "mode": "Attention",
            },
        }
        wf["18"] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["17", 0],
                "negative": ["917", 0],
                "control_net": ["800", 0],
                "image": ["801", 0],
                "strength": 0.45,
                "start_percent": 0.0,
                "end_percent": 0.5,
            },
        }
        wf["19"] = {
            "class_type": "Attention couple",
            "inputs": {
                "model": ["3", 0],
                "positive": ["18", 0],
                "negative": ["18", 1],
                "mode": "Attention",
            },
        }
    else:
        # No pose: skip ControlNet, wire AttentionCouple straight to combined cond.
        wf["13"] = {
            "class_type": "Attention couple",
            "inputs": {
                "model": ["3", 0],
                "positive": ["11", 0],
                "negative": ["907", 0],
                "mode": "Attention",
            },
        }
        wf["19"] = {
            "class_type": "Attention couple",
            "inputs": {
                "model": ["3", 0],
                "positive": ["17", 0],
                "negative": ["917", 0],
                "mode": "Attention",
            },
        }

    # Samplers reference AttentionCouple outputs (same wiring for both paths).
    wf["21"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": 28,
            "cfg": 5.0,
            "sampler_name": "euler_ancestral",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["13", 0],
            "positive": ["13", 1],
            "negative": ["13", 2],
            "latent_image": ["20", 0],
        },
    }
    wf["23"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": 12,
            "cfg": 4.5,
            "sampler_name": "euler_ancestral",
            "scheduler": "normal",
            "denoise": 0.35,
            "model": ["19", 0],
            "positive": ["19", 1],
            "negative": ["19", 2],
            "latent_image": ["22", 0],
        },
    }
    return wf


def build_raw_duo_workflow(
    positive_global: str,
    positive_left: str,
    positive_right: str,
    negative: str = "",
    *,
    seed: int | None = None,
    output_prefix: str = "DUET_RAW_DUO",
) -> Graph:
    """LoRA-less AttentionCouple duo graph (prompt-only left/right regions).

    Same SolidMask split + ConditioningSetMask + AttentionCouple wiring as
    build_duo_workflow, but no character LoRA loaders and no ControlNet (pose-less).
    The checkpoint's MODEL/CLIP feed the graph directly. The config style prefix/
    suffix wrap the global segment and the base negative is folded in.
    """
    if seed is None:
        seed = random.randint(10000, 99999)

    global_pos = f"{STYLE_PREFIX}, {positive_global}, {STYLE_SUFFIX}"
    neg = NEGATIVE_PROMPT if not negative else f"{NEGATIVE_PROMPT}, {negative}"

    _check_token_limit(global_pos, "Global 段")
    _check_token_limit(positive_left, "Left 段")
    _check_token_limit(positive_right, "Right 段")

    wf: Graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        "1c": {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1c", 0], "text": global_pos},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1c", 0], "text": positive_left},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1c", 0], "text": positive_right},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1c", 0], "text": neg},
        },
        # --- Base stage masks (left/right split at x=608) ---
        "900": {
            "class_type": "SolidMask",
            "inputs": {"value": 0.0, "width": 1216, "height": 832},
        },
        "901": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 608, "height": 832},
        },
        "902": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 608, "height": 832},
        },
        "903": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["900", 0],
                "source": ["901", 0],
                "x": 0,
                "y": 0,
                "operation": "add",
            },
        },
        "904": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["900", 0],
                "source": ["902", 0],
                "x": 608,
                "y": 0,
                "operation": "add",
            },
        },
        "905": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 1216, "height": 832},
        },
        # --- ConditioningSetMask x4 ---
        "906": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["4", 0],
                "mask": ["905", 0],
                "strength": 0.45,
                "set_cond_area": "default",
            },
        },
        "907": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["7", 0],
                "mask": ["905", 0],
                "strength": 1.0,
                "set_cond_area": "default",
            },
        },
        "8": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["5", 0],
                "mask": ["903", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        "9": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["6", 0],
                "mask": ["904", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        # --- ConditioningCombine ---
        "10": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["906", 0], "conditioning_2": ["8", 0]},
        },
        "11": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["10", 0], "conditioning_2": ["9", 0]},
        },
        # --- EmptyLatent + base KSampler ---
        "20": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1216, "height": 832, "batch_size": 1},
        },
        # --- Hires masks (1824x1248, split at x=912) ---
        "910": {
            "class_type": "SolidMask",
            "inputs": {"value": 0.0, "width": 1824, "height": 1248},
        },
        "911": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 912, "height": 1248},
        },
        "912": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 912, "height": 1248},
        },
        "913": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["910", 0],
                "source": ["911", 0],
                "x": 0,
                "y": 0,
                "operation": "add",
            },
        },
        "914": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["910", 0],
                "source": ["912", 0],
                "x": 912,
                "y": 0,
                "operation": "add",
            },
        },
        "915": {
            "class_type": "SolidMask",
            "inputs": {"value": 1.0, "width": 1824, "height": 1248},
        },
        "916": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["4", 0],
                "mask": ["915", 0],
                "strength": 0.45,
                "set_cond_area": "default",
            },
        },
        "917": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["7", 0],
                "mask": ["915", 0],
                "strength": 1.0,
                "set_cond_area": "default",
            },
        },
        "14": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["5", 0],
                "mask": ["913", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        "15": {
            "class_type": "ConditioningSetMask",
            "inputs": {
                "conditioning": ["6", 0],
                "mask": ["914", 0],
                "strength": 1.0,
                "set_cond_area": "mask bounds",
            },
        },
        "16": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["916", 0], "conditioning_2": ["14", 0]},
        },
        "17": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["16", 0], "conditioning_2": ["15", 0]},
        },
        # --- AttentionCouple (no ControlNet, pose-less) ---
        "13": {
            "class_type": "Attention couple",
            "inputs": {
                "model": ["1", 0],
                "positive": ["11", 0],
                "negative": ["907", 0],
                "mode": "Attention",
            },
        },
        "19": {
            "class_type": "Attention couple",
            "inputs": {
                "model": ["1", 0],
                "positive": ["17", 0],
                "negative": ["917", 0],
                "mode": "Attention",
            },
        },
        "21": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 28,
                "cfg": 5.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["13", 0],
                "positive": ["13", 1],
                "negative": ["13", 2],
                "latent_image": ["20", 0],
            },
        },
        "22": {
            "class_type": "LatentUpscaleBy",
            "inputs": {
                "upscale_method": "bicubic",
                "scale_by": 1.5,
                "samples": ["21", 0],
            },
        },
        "23": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 12,
                "cfg": 4.5,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 0.35,
                "model": ["19", 0],
                "positive": ["19", 1],
                "negative": ["19", 2],
                "latent_image": ["22", 0],
            },
        },
        "24": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["23", 0],
                "vae": ["1", 2],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        },
        "25": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": output_prefix, "images": ["24", 0]},
        },
    }
    return wf
