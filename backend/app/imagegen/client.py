"""Async ComfyUI client — ported from rp_system/image_gen.py (requests -> httpx).

submit_and_wait: POST /prompt, poll /history/{id}, fetch bytes via /view.
ensure_comfyui / restart via the manager sidecar (:52189). CUDA-sticky errors
trigger a restart, mirroring the original.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import COMFY_URL, MANAGER_URL


async def ensure_comfyui(timeout: float = 180.0) -> bool:
    """Ensure ComfyUI is running via the manager sidecar."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{MANAGER_URL}/status", timeout=10)
            if r.json().get("comfyui_running"):
                return True
        except Exception:
            pass
        try:
            r = await client.post(f"{MANAGER_URL}/start", timeout=timeout)
            return bool(r.json().get("comfyui_running", False))
        except Exception:
            return False


async def stop_comfyui() -> bool:
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{MANAGER_URL}/stop", timeout=10)
            return True
        except Exception:
            return False


async def restart_comfyui() -> bool:
    """Restart ComfyUI (required after a sticky CUDA error)."""
    await stop_comfyui()
    await asyncio.sleep(3)
    return await ensure_comfyui()


async def submit_and_wait(
    workflow: dict[str, Any],
    timeout_sec: int = 300,
    poll_interval: float = 3.0,
) -> dict[str, Any]:
    """Submit a graph and wait for the resulting image bytes.

    Returns {filename, path(None), bytes, prompt_id} on success, else {error: ...}.
    """
    client_id = f"duet-{int(time.time())}"

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
                        fn = img["filename"]
                        img_r = await client.get(
                            f"{COMFY_URL}/view",
                            params={
                                "filename": fn,
                                "type": img.get("type", "output"),
                                "subfolder": img.get("subfolder", ""),
                            },
                            timeout=30,
                        )
                        return {
                            "filename": fn,
                            "path": None,
                            "bytes": img_r.content,
                            "prompt_id": prompt_id,
                        }
                return {"error": "成功但无输出图片", "prompt_id": prompt_id}
            if status == "error":
                msgs = entry.get("status", {}).get("messages", [])
                for mt, md in msgs:
                    if mt == "execution_error":
                        err_msg = md.get("exception_message", "未知错误")
                        if "CUDA" in err_msg:
                            return {
                                "error": err_msg,
                                "cuda_sticky": True,
                                "prompt_id": prompt_id,
                            }
                        return {"error": err_msg, "prompt_id": prompt_id}
                return {"error": "执行错误", "prompt_id": prompt_id}
        return {"error": "超时", "prompt_id": prompt_id}
