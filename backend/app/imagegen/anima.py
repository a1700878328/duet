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
      -> LoraLoaderModelOnly(anima-turbo @0.8)     -> MODEL ─┐
    CLIPLoader(qwen_3_06b_base, stable_diffusion)  -> CLIP   │
      -> CLIPTextEncode(positive)                  -> COND   │
      -> CLIPTextEncode(negative)                  -> COND   │
    AnimaLatentImage(width,height)                 -> LATENT │
      -> KSampler(steps=18,cfg=1.15,er_sde,beta57) <─────────┘
      -> VAEDecode(qwen_image_vae)                 -> IMAGE
      -> SaveImage

Node quirks worth knowing:
- AnimaBoosterLoader outputs MODEL **only** (no CLIP/VAE bundled) — CLIP and VAE
  are loaded separately, unlike CheckpointLoaderSimple in the SDXL path.
- CLIP is a Qwen3-0.6B text encoder loaded via CLIPLoader with type
  "stable_diffusion" (the Anima build registers it under that type).
- AuraFlow/DiT wants **low CFG**: turbo LoRA + cfg≈1.15, sampler er_sde,
  scheduler beta57, 18 steps (proven values from the reference workflow).
- ModelSamplingAuraFlow shift=3.0 (reference value; node default is 1.73).
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .client import ensure_comfyui
from .config import COMFY_URL


def char_seed(room_id: int, name: str) -> int:
    """同一角色（房间+名字）恒得同一 seed → 立绘与场景图人物更一致。

    无 LoRA/FaceID 时，固定 seed + 同一外貌 tag 是基模保持人物一致的主要手段。
    """
    h = hashlib.sha1(f"{room_id}\x00{name}".encode()).hexdigest()
    return int(h[:8], 16)


Graph = dict[str, dict[str, Any]]

# === Anima model files (verified present via /object_info) ===
ANIMA_MODEL = "anima-base-v1.0.safetensors"
ANIMA_TURBO_LORA = "anima-turbo-lora-v0.1.safetensors"
ANIMA_CLIP = "qwen_3_06b_base.safetensors"
ANIMA_CLIP_TYPE = "stable_diffusion"
ANIMA_VAE = "qwen_image_vae.safetensors"

# === Sampler params (from the reference workflow's main KSampler, node 57) ===
ANIMA_STEPS = 18
ANIMA_CFG = 1.15
ANIMA_SAMPLER = "er_sde"
ANIMA_SCHEDULER = "beta57"
ANIMA_SHIFT = 3.0
ANIMA_TURBO_STRENGTH = 0.8

# === Default sizes (multiples of 16, AuraFlow requirement) ===
PORTRAIT_WIDTH = 832
PORTRAIT_HEIGHT = 1216
LANDSCAPE_WIDTH = 1216
LANDSCAPE_HEIGHT = 832

# A light default negative; callers may extend it.
DEFAULT_NEGATIVE = (
    "worst quality, low quality, bad anatomy, bad hands, extra fingers, "
    "missing fingers, watermark, text, signature, jpeg artifacts"
)

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media" / "generated"
MEDIA_URL_PREFIX = "/media/generated"


def build_anima_workflow(
    positive: str,
    negative: str = "",
    *,
    width: int = PORTRAIT_WIDTH,
    height: int = PORTRAIT_HEIGHT,
    seed: int | None = None,
    steps: int = ANIMA_STEPS,
    cfg: float = ANIMA_CFG,
    use_turbo: bool = True,
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
            "inputs": {"model": ["1", 0], "shift": ANIMA_SHIFT},
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

    g["9"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": ANIMA_SAMPLER,
            "scheduler": ANIMA_SCHEDULER,
            "denoise": 1.0,
            "model": model_ref,
            "positive": ["5", 0],
            "negative": ["6", 0],
            "latent_image": ["8", 0],
        },
    }
    return g


def _save_png(image_bytes: bytes) -> tuple[str, Path]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    path = MEDIA_DIR / name
    path.write_bytes(image_bytes)
    return name, path


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
                for out in entry.get("outputs", {}).values():
                    for img in out.get("images", []):
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
    use_turbo: bool = True,
) -> dict[str, Any]:
    """Generate one Anima image. Multi-person = multiple chars in ``positive``.

    Returns {url, path, filename, prompt_id} on success or {error} on any failure.
    Never raises. Pass ``landscape=True`` for the 1216x832 multi-person default
    (good for 2-3 characters side by side), or set width/height explicitly.
    """
    if landscape and width == PORTRAIT_WIDTH and height == PORTRAIT_HEIGHT:
        width, height = LANDSCAPE_WIDTH, LANDSCAPE_HEIGHT

    try:
        workflow = build_anima_workflow(
            positive,
            negative,
            width=width,
            height=height,
            seed=seed,
            use_turbo=use_turbo,
        )
    except Exception as e:  # build is pure, but never raise out of the entrypoint
        return {"error": f"构图失败: {e}"}

    result = await _submit_and_fetch(workflow)
    if result.get("error"):
        return {"error": result["error"], "prompt_id": result.get("prompt_id")}

    image_bytes = result.get("bytes")
    if not image_bytes:
        return {"error": "成功但无图片字节"}

    name, path = _save_png(image_bytes)
    return {
        "url": f"{MEDIA_URL_PREFIX}/{name}",
        "path": str(path),
        "filename": name,
        "prompt_id": result.get("prompt_id"),
    }
