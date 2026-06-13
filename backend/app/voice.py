"""VoxCPM TTS 客户端（Phase E 语音）。

本机 VoxCPM：TTS 服务 127.0.0.1:9233（懒加载），管理进程 :9234（POST /ensure 拉起）。
合成失败/服务未起时优雅降级（返回 None），不挡聊天主路。
"""

import os
from typing import Any

import httpx

VOXCPM_BASE = os.environ.get("VOXCPM_BASE", "http://127.0.0.1:9233")
VOXCPM_MANAGER = os.environ.get("VOXCPM_MANAGER", "http://127.0.0.1:9234")
DEFAULT_VOICE = os.environ.get("VOXCPM_DEFAULT_VOICE", "onee")
MODEL = "voxcpm2"


class VoiceClient:
    """瘦客户端：列声音（缓存）+ 合成。懒确保服务起着。"""

    def __init__(self) -> None:
        self._voices: set[str] | None = None

    async def _ensure_up(self, client: httpx.AsyncClient) -> None:
        """服务没起时让管理进程拉起（best-effort）。"""
        try:
            await client.post(f"{VOXCPM_MANAGER}/ensure", timeout=130)
        except Exception:
            pass

    async def voices(self) -> set[str]:
        if self._voices is not None:
            return self._voices
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.get(f"{VOXCPM_BASE}/v1/voices")
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                return set()
        names: set[str] = set()
        items: Any = data.get("voices", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            names = {str(k) for k in items}
        elif isinstance(items, list):
            for it in items:
                if isinstance(it, str):
                    names.add(it)
                elif isinstance(it, dict) and it.get("name"):
                    names.add(str(it["name"]))
        if names:
            self._voices = names
        return names

    async def resolve_voice(self, voice_id: str | None) -> str:
        """解析卡上的 voice_id 成 VoxCPM 的 voice 参数：

        - 空 → 默认预设；
        - 已是 ``design:...`` → 原样（即兴声音设计）；
        - 命中预设/克隆名 → 原样；
        - 其他非空（= 一段声音描述）→ ``design:<描述>``，每个 NPC 一把独有新声音。
        """
        vid = (voice_id or "").strip()
        if not vid:
            return DEFAULT_VOICE
        if vid.lower().startswith("design:"):
            return vid
        available = await self.voices()
        if vid in available:
            return vid
        return f"design:{vid}"

    async def synth(self, text: str, voice_id: str | None) -> bytes | None:
        """合成 wav 字节；失败返回 None。会在服务未起时尝试拉起一次。"""
        text = (text or "").strip()
        if not text:
            return None
        voice = await self.resolve_voice(voice_id)
        payload = {
            "model": MODEL,
            "input": text[:1000],
            "voice": voice,
            "response_format": "wav",
        }
        async with httpx.AsyncClient(timeout=180) as client:
            for attempt in range(2):
                try:
                    resp = await client.post(
                        f"{VOXCPM_BASE}/v1/audio/speech", json=payload
                    )
                    resp.raise_for_status()
                    return resp.content
                except httpx.HTTPStatusError:
                    return None
                except Exception:
                    if attempt == 0:
                        await self._ensure_up(client)
                        continue
                    return None
        return None


store = VoiceClient()
