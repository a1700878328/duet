"""High-level image-gen service: registry -> guard -> workflow -> client.

generate_single / generate_duo never raise out: registry/guard/Comfy failures
return {"error": ...}. On success the PNG is saved to app/media/generated/<uuid>.png
and a dict {url, path, filename, prompt_id} is returned for static serving.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .client import ensure_comfyui, restart_comfyui, submit_and_wait
from .guard import (
    PoisonedPromptError,
    UnverifiedNamedCharacter,
    assert_no_poisoned_colors,
)
from .registry import UnverifiedCharacter
from .workflows import (
    build_duo_workflow,
    build_raw_duo_workflow,
    build_raw_single_workflow,
    build_single_workflow,
)

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media" / "generated"
MEDIA_URL_PREFIX = "/media/generated"


def _save_png(image_bytes: bytes) -> tuple[str, Path]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    path = MEDIA_DIR / name
    path.write_bytes(image_bytes)
    return name, path


async def _run(workflow: dict[str, Any]) -> dict[str, Any]:
    await ensure_comfyui()
    result = await submit_and_wait(workflow)
    if result.get("cuda_sticky"):
        await restart_comfyui()
        orig = result.get("error")
        return {"error": f"CUDA 粘性错误，ComfyUI 已重启，请重试。原始: {orig}"}
    if result.get("error"):
        return {"error": result["error"]}

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


async def generate_single(
    char_name: str,
    scene: str,
    *,
    nsfw: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one single-char image. Returns {url,path,filename,prompt_id}|{error}."""
    try:
        workflow = build_single_workflow(char_name, scene, seed=seed, nsfw=nsfw)
    except (UnverifiedCharacter, ValueError) as e:
        return {"error": str(e)}
    try:
        return await _run(workflow)
    except (PoisonedPromptError, UnverifiedNamedCharacter) as e:
        return {"error": str(e)}


async def generate_raw_single(
    positive: str,
    negative: str = "",
    *,
    nsfw: bool = False,
    landscape: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """LoRA-less raw single. Returns {url,path,filename,prompt_id}|{error}."""
    body = f"(nsfw:1.2), {positive}" if nsfw else positive
    try:
        assert_no_poisoned_colors([body])
        workflow = build_raw_single_workflow(
            body, negative, landscape=landscape, seed=seed
        )
    except (PoisonedPromptError, UnverifiedNamedCharacter, ValueError) as e:
        return {"error": str(e)}
    try:
        return await _run(workflow)
    except (PoisonedPromptError, UnverifiedNamedCharacter) as e:
        return {"error": str(e)}


async def generate_raw_duo(
    positive_global: str,
    positive_left: str,
    positive_right: str,
    negative: str = "",
    *,
    nsfw: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """LoRA-less raw duo. Returns {url,path,filename,prompt_id}|{error}."""
    g = f"(nsfw:1.2), {positive_global}" if nsfw else positive_global
    try:
        assert_no_poisoned_colors([g, positive_left, positive_right])
        workflow = build_raw_duo_workflow(
            g, positive_left, positive_right, negative, seed=seed
        )
    except (PoisonedPromptError, UnverifiedNamedCharacter, ValueError) as e:
        return {"error": str(e)}
    try:
        return await _run(workflow)
    except (PoisonedPromptError, UnverifiedNamedCharacter) as e:
        return {"error": str(e)}


async def generate_duo(
    char_a: str,
    char_b: str,
    *,
    scene_global: str = "",
    scene_left: str = "",
    scene_right: str = "",
    nsfw: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one dual-char image. Returns {url,path,filename,prompt_id}|{error}."""
    try:
        workflow = build_duo_workflow(
            char_a,
            char_b,
            scene_global=scene_global,
            scene_left=scene_left,
            scene_right=scene_right,
            seed=seed,
            nsfw=nsfw,
        )
    except (UnverifiedCharacter, ValueError) as e:
        return {"error": str(e)}
    try:
        return await _run(workflow)
    except (PoisonedPromptError, UnverifiedNamedCharacter) as e:
        return {"error": str(e)}
