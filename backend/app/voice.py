"""Voice provider client for role voice design and TTS.

ElevenLabs can be used to design an audition reference. Fish Audio S2-Pro can
then use that reference audio in its ``references`` payload, which gives this
app a practical "design first, clone on synthesis" role voice workflow.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import ormsgpack

from .config import settings

VOICE_PROVIDER = settings.voice_provider.strip().lower() or "auto"

ELEVEN_API_BASE = settings.eleven_api_base.rstrip("/")
ELEVEN_API_KEY = settings.eleven_api_key.strip()
ELEVEN_API_KEY_FILE = settings.eleven_api_key_file.strip()
ELEVEN_DESIGN_MODEL = (
    settings.eleven_voice_design_model.strip() or "eleven_multilingual_ttv_v2"
)
ELEVEN_TTS_MODEL = settings.eleven_tts_model.strip() or "eleven_v3"
ELEVEN_OUTPUT_FORMAT = settings.eleven_output_format.strip() or "mp3_44100_128"
ELEVEN_DESIGN_LOUDNESS = settings.eleven_design_loudness
ELEVEN_DESIGN_GUIDANCE_SCALE = settings.eleven_design_guidance_scale
ELEVEN_CLONE_DESIGN_PREVIEW = settings.eleven_clone_design_preview
ANIME_VOICE_STYLE_BIAS = settings.anime_voice_style_bias.strip()

FISH_API_BASE = settings.fish_api_base.rstrip("/")
FISH_API_KEY = settings.fish_api_key
FISH_MODEL = settings.fish_tts_model
FISH_DEFAULT_REFERENCE_ID = settings.fish_default_reference_id.strip()
FISH_FEMALE_REFERENCE_ID = settings.fish_female_reference_id.strip()
FISH_MALE_REFERENCE_ID = settings.fish_male_reference_id.strip()
FISH_FORMAT = settings.fish_tts_format.strip().lower() or "mp3"
FISH_TEMPERATURE = settings.fish_tts_temperature
FISH_TOP_P = settings.fish_tts_top_p
FISH_CHUNK_LENGTH = settings.fish_tts_chunk_length
FISH_SPEED = settings.fish_tts_speed
FISH_VOLUME = settings.fish_tts_volume
FISH_PERFORMANCE_TAGS_ENABLED = settings.fish_performance_tags_enabled
VOICE_PREVIEW_MAX_CHARS = 120
VOICE_REFERENCE_PAYLOAD_MAX_CHARS = 120


@dataclass(frozen=True)
class DesignedVoice:
    voice_id: str
    reference_audio: bytes
    reference_text: str
    voice_description: str
    provider: str


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def _log_voice_failure(
    stage: str, exc: Exception | None = None, detail: str = ""
) -> None:
    """Print provider failures without leaking API keys or full payloads."""
    bits = [
        f"[VOICE] stage={stage}",
        f"provider={_active_provider()}",
        f"fish_model={FISH_MODEL}",
        f"eleven_design_model={ELEVEN_DESIGN_MODEL}",
    ]
    if detail:
        bits.append(f"detail={detail[:320]}")
    if exc is not None:
        if isinstance(exc, httpx.HTTPStatusError):
            resp = exc.response
            body = ""
            try:
                body = resp.text[:500]
            except Exception:
                body = "<unreadable>"
            bits.append(f"status={resp.status_code}")
            if body:
                bits.append(f"body={body!r}")
        else:
            bits.append(f"error={type(exc).__name__}: {str(exc)[:500]}")
    print(" ".join(bits), flush=True)


def _read_text_file(path_value: str) -> str:
    if not path_value:
        return ""
    try:
        path = Path(path_value).expanduser()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return ""


def _eleven_key() -> str:
    return ELEVEN_API_KEY or _read_text_file(ELEVEN_API_KEY_FILE)


def _active_provider() -> str:
    if VOICE_PROVIDER in {"eleven", "fish", "fish_clone", "hybrid"}:
        return VOICE_PROVIDER
    if _eleven_key() and FISH_API_KEY:
        return "fish_clone"
    if _eleven_key():
        return "eleven"
    return "fish"


def _looks_like_reference_id(value: str) -> bool:
    if value.startswith(("fish:", "fish-clone:", "reference:", "ref:")):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{10,}", value))


def _strip_reference_prefix(value: str) -> str:
    for prefix in ("fish:", "fish-clone:", "reference:", "ref:", "eleven:"):
        if value.startswith(prefix):
            return value.split(":", 1)[1].strip()
    return value


def _fallback_reference_id(description: str) -> str:
    text = description.lower()
    if re.search(r"(女性|女声|女人|少女|女孩|女|female|woman|girl)", text):
        return FISH_FEMALE_REFERENCE_ID or FISH_DEFAULT_REFERENCE_ID
    if re.search(r"(男性|男声|男人|少年|男孩|男|male|man|boy)", text):
        return FISH_MALE_REFERENCE_ID or FISH_DEFAULT_REFERENCE_ID
    return FISH_DEFAULT_REFERENCE_ID


def _ensure_preview_text(text: str) -> str:
    preview = re.sub(r"\s+", " ", text.strip())
    preview = preview.replace(
        "我会根据你的情绪调整语气，保持自然的停顿和清晰的表达，"
        "让每一句话都像角色本人正在认真回应。",
        "",
    )
    if not preview:
        preview = "你好，我准备好了。"
    # ElevenLabs Voice Design API requires text >= 100 characters.
    if len(preview) < 100:
        core = preview[:80].rstrip("。.!！")
        preview = f"{core}……{core}，我说的你都明白了吧。"
        while len(preview) < 100:
            preview = f"{preview} {core}，明白了吗？"
    return preview[:VOICE_PREVIEW_MAX_CHARS]


def _anime_voice_description(description: str) -> str:
    desc = re.sub(r"\s+", " ", description.strip())
    if not ANIME_VOICE_STYLE_BIAS:
        return desc
    return f"{desc}. Style direction: {ANIME_VOICE_STYLE_BIAS}"[:1000]


def _voice_label(description: str, *needles: str) -> bool:
    text = description.lower()
    return any(n in text for n in needles)


def _eleven_labels(description: str) -> dict[str, str]:
    labels: dict[str, str] = {"language": "zh"}
    if _voice_label(description, "女", "female", "woman", "girl"):
        labels["gender"] = "female"
    elif _voice_label(description, "男", "male", "man", "boy"):
        labels["gender"] = "male"
    if _voice_label(description, "少女", "少年", "young", "teen"):
        labels["age"] = "young"
    elif _voice_label(description, "老", "elderly", "old"):
        labels["age"] = "elderly"
    elif _voice_label(description, "中年", "middle"):
        labels["age"] = "middle-aged"
    else:
        labels["age"] = "adult"
    return labels


class VoiceClient:
    """Small provider-neutral voice client used by room routes."""

    def __init__(self) -> None:
        self._design_cache: dict[str, str] = {}

    @property
    def provider(self) -> str:
        return _active_provider()

    @property
    def extension(self) -> str:
        if self.provider == "eleven":
            return "mp3"
        return "wav" if FISH_FORMAT == "wav" else FISH_FORMAT

    def design_reference_id(self, description: str) -> str:
        desc = re.sub(r"\s+", " ", description.strip())
        cached = self._design_cache.get(desc)
        if cached:
            return cached
        digest = hashlib.sha1(desc.encode("utf-8")).hexdigest()[:20]
        ref = f"{self.provider}-design-{digest}"
        self._design_cache[desc] = ref
        return ref

    async def voices(self) -> set[str]:
        """Return known voice ids when cheap; kept for compatibility."""
        if self.provider != "eleven":
            return set()
        key = _eleven_key()
        if not key:
            return set()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{ELEVEN_API_BASE}/v2/voices",
                    headers={"xi-api-key": key},
                    params={"page_size": 100},
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    v["voice_id"] for v in data.get("voices", []) if v.get("voice_id")
                }
        except Exception as exc:
            _log_voice_failure("eleven_voices", exc)
            return set()

    async def resolve_voice(self, voice_id: str | None) -> str:
        """Resolve card voice field into a provider-native id."""
        vid = re.sub(r"\s+", " ", (voice_id or "").strip())
        if self.provider == "eleven":
            return _strip_reference_prefix(vid)
        if not vid:
            return FISH_DEFAULT_REFERENCE_ID
        if vid.lower().startswith("design:"):
            return _fallback_reference_id(vid.split(":", 1)[1])
        if _looks_like_reference_id(vid):
            return _strip_reference_prefix(vid)
        return _fallback_reference_id(vid)

    async def design_voice(
        self,
        *,
        name: str,
        voice_description: str,
        reference_text: str,
    ) -> DesignedVoice | None:
        """Create a stable voice for a card and return its reference sample."""
        if self.provider in {"fish_clone", "hybrid"}:
            designed = await self._design_eleven_reference(
                voice_description=voice_description,
                reference_text=reference_text,
            )
            if designed:
                digest = hashlib.sha1(designed.reference_audio).hexdigest()[:20]
                return DesignedVoice(
                    voice_id=f"fish-clone:{digest}",
                    reference_audio=designed.reference_audio,
                    reference_text=designed.reference_text,
                    voice_description=voice_description,
                    provider="fish",
                )
        if self.provider != "eleven":
            audio = await self.synth(reference_text, voice_description)
            if not audio:
                return None
            return DesignedVoice(
                voice_id=voice_description,
                reference_audio=audio,
                reference_text=reference_text,
                voice_description=voice_description,
                provider="fish",
            )
        return await self._design_eleven_voice(
            name=name,
            voice_description=voice_description,
            reference_text=reference_text,
        )

    async def _design_eleven_reference(
        self,
        *,
        voice_description: str,
        reference_text: str,
    ) -> DesignedVoice | None:
        key = _eleven_key()
        if not key:
            return None
        # 使用角色特色的参考台词（padded to >=100 chars for ElevenLabs）
        preview_text = _ensure_preview_text(reference_text)
        # Deterministic seed per character description for consistent voice design.
        design_seed = int(hashlib.sha1(voice_description.encode()).hexdigest()[:8], 16)
        payload = {
            "voice_description": _anime_voice_description(voice_description),
            "model_id": ELEVEN_DESIGN_MODEL,
            "text": preview_text,
            "seed": design_seed,
            "loudness": _clamp(ELEVEN_DESIGN_LOUDNESS, -1.0, 1.0),
            "guidance_scale": _clamp(ELEVEN_DESIGN_GUIDANCE_SCALE, 0.0, 100.0),
            "stream_previews": False,
        }
        try:
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post(
                    f"{ELEVEN_API_BASE}/v1/text-to-voice/design",
                    headers={"xi-api-key": key, "Content-Type": "application/json"},
                    params={"output_format": ELEVEN_OUTPUT_FORMAT},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                preview = data["previews"][0]
                gen_text = data.get("text") or ""
                return DesignedVoice(
                    voice_id="",
                    reference_audio=base64.b64decode(preview["audio_base_64"]),
                    reference_text=gen_text,
                    voice_description=voice_description,
                    provider="eleven",
                )
        except Exception as exc:
            _log_voice_failure("eleven_design_reference", exc)
            return None

    async def _design_eleven_voice(
        self,
        *,
        name: str,
        voice_description: str,
        reference_text: str,
    ) -> DesignedVoice | None:
        key = _eleven_key()
        if not key:
            return None
        headers = {"xi-api-key": key, "Content-Type": "application/json"}
        preview_text = _ensure_preview_text(reference_text)
        design_seed = int(hashlib.sha1(voice_description.encode()).hexdigest()[:8], 16)
        payload = {
            "voice_description": _anime_voice_description(voice_description),
            "model_id": ELEVEN_DESIGN_MODEL,
            "text": preview_text,
            "seed": design_seed,
            "loudness": _clamp(ELEVEN_DESIGN_LOUDNESS, -1.0, 1.0),
            "guidance_scale": _clamp(ELEVEN_DESIGN_GUIDANCE_SCALE, 0.0, 100.0),
            "stream_previews": False,
        }
        try:
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post(
                    f"{ELEVEN_API_BASE}/v1/text-to-voice/design",
                    headers=headers,
                    params={"output_format": ELEVEN_OUTPUT_FORMAT},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                preview = data["previews"][0]
                audio = base64.b64decode(preview["audio_base_64"])
                gen_text = data.get("text") or ""
                generated_voice_id = preview["generated_voice_id"]
                native_voice_id = ""
                if ELEVEN_CLONE_DESIGN_PREVIEW:
                    native_voice_id = await self._clone_eleven_preview(
                        client=client,
                        api_key=key,
                        name=name,
                        voice_description=voice_description,
                        audio=audio,
                    )
                if not native_voice_id:
                    native_voice_id = await self._save_eleven_preview(
                        client=client,
                        api_key=key,
                        name=name,
                        voice_description=voice_description,
                        generated_voice_id=generated_voice_id,
                    )
                if not native_voice_id:
                    return None
                return DesignedVoice(
                    voice_id=f"eleven:{native_voice_id}",
                    reference_audio=audio,
                    reference_text=gen_text,
                    voice_description=voice_description,
                    provider="eleven",
                )
        except Exception as exc:
            _log_voice_failure("eleven_design_voice", exc)
            return None

    async def _clone_eleven_preview(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        name: str,
        voice_description: str,
        audio: bytes,
    ) -> str:
        files = [("files", ("voice_design_reference.mp3", audio, "audio/mpeg"))]
        data = {
            "name": f"Duet {name}"[:100],
            "description": voice_description[:1000],
            "labels": json.dumps(_eleven_labels(voice_description)),
            "remove_background_noise": "false",
        }
        try:
            resp = await client.post(
                f"{ELEVEN_API_BASE}/v1/voices/add",
                headers={"xi-api-key": api_key},
                data=data,
                files=files,
            )
            resp.raise_for_status()
            return str(resp.json().get("voice_id") or "")
        except Exception as exc:
            _log_voice_failure("eleven_clone_preview", exc)
            return ""

    async def _save_eleven_preview(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        name: str,
        voice_description: str,
        generated_voice_id: str,
    ) -> str:
        try:
            resp = await client.post(
                f"{ELEVEN_API_BASE}/v1/text-to-voice",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "voice_name": f"Duet {name}"[:100],
                    "voice_description": voice_description,
                    "generated_voice_id": generated_voice_id,
                },
            )
            resp.raise_for_status()
            return str(resp.json().get("voice_id") or generated_voice_id)
        except Exception as exc:
            _log_voice_failure("eleven_save_preview", exc)
            return ""

    def _performance_tags(self, text: str, reference_text: str | None) -> list[str]:
        """Choose Fish S2-Pro style tags from line intent + role reference."""
        if not FISH_PERFORMANCE_TAGS_ENABLED:
            return []
        line = text.strip()
        if not line or re.search(r"\[[^\]]{1,80}\]", line):
            return []
        ctx = f"{reference_text or ''}\n{line}".lower()
        tags: list[str] = []

        def add(tag: str) -> None:
            if tag not in tags and len(tags) < 3:
                tags.append(tag)

        if re.search(r"(哈|呵|嘻|嘿|笑|哎呀|呀|嘛|哦|呢|~|～)", ctx):
            add("happy")
        if re.search(r"(缺钱|利息|契约|账|债|逾期|偿还|客人|商人|骑士大人)", ctx):
            add("chuckling")
        if re.search(r"(小声|悄悄|秘密|靠近|耳边|别告诉|嘘)", ctx):
            add("whispering")
        if re.search(r"(害怕|紧张|糟糕|怎么办|不、不|没、没|危险)", line):
            add("nervous")
        if re.search(r"(生气|够了|闭嘴|不许|混蛋|竟敢|骗我)", line):
            add("angry")
        if re.search(r"(叹|唉|疲惫|难过|哭|抱歉|对不起)", line):
            add("sighing")
        if re.search(r"(等等|快|太好了|真的|？！|!|！)", line):
            add("excited")
        if "…" in line or "..." in line:
            add("soft tone")
        if re.search(r"(冷笑|嘲笑|轻笑|笑)", line):
            add("chuckling")
        if not tags and re.search(r"(可爱|少女|软萌|亲近|温柔|甜)", ctx):
            add("happy")
        return tags

    def _decorate_text(self, text: str, reference_text: str | None = None) -> str:
        """Add Fish S2-Pro inline performance tags when the line has none."""
        line = text.strip()[:1000]
        if not line or re.search(r"\[[^\]]{1,80}\]", line):
            return line
        tags = self._performance_tags(line, reference_text)
        if tags:
            return "".join(f"[{tag}]" for tag in tags) + f" {line}"
        return line

    def _fish_payload(
        self, text: str, reference_id: str, reference_text: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": self._decorate_text(text, reference_text),
            "model": FISH_MODEL,
            "temperature": _clamp(FISH_TEMPERATURE, 0.0, 1.0),
            "top_p": _clamp(FISH_TOP_P, 0.0, 1.0),
            "chunk_length": max(100, min(FISH_CHUNK_LENGTH, 300)),
            "format": FISH_FORMAT,
            "prosody": {
                "speed": _clamp(FISH_SPEED, 0.5, 2.0),
                "volume": _clamp(FISH_VOLUME, -20.0, 20.0),
            },
        }
        if reference_id and not reference_id.startswith("fish-design-"):
            payload["reference_id"] = reference_id
        elif FISH_DEFAULT_REFERENCE_ID:
            payload["reference_id"] = FISH_DEFAULT_REFERENCE_ID
        return payload

    def _fish_reference_payload(
        self, text: str, reference_audio: bytes, reference_text: str
    ) -> dict[str, Any]:
        payload = self._fish_payload(text, "", reference_text)
        ref_text = (reference_text.strip() or "你好，很高兴见到你。")[
            :VOICE_REFERENCE_PAYLOAD_MAX_CHARS
        ]
        payload["references"] = [
            {
                "audio": reference_audio,
                "text": ref_text,
            }
        ]
        payload.pop("reference_id", None)
        return payload

    async def synth(
        self,
        text: str,
        voice_id: str | None,
        *,
        reference_audio_path: str | Path | None = None,
        reference_text: str | None = None,
    ) -> bytes | None:
        """Synthesize audio bytes; failure returns None."""
        clean = (text or "").strip()
        if not clean:
            return None
        if (voice_id or "").startswith(("fish:", "fish-clone:")) or self.provider in {
            "fish_clone",
            "hybrid",
        }:
            return await self._synth_fish(
                clean,
                voice_id,
                reference_audio_path=reference_audio_path,
                reference_text=reference_text,
            )
        if self.provider == "eleven" or (voice_id or "").startswith("eleven:"):
            return await self._synth_eleven(clean, voice_id)
        return await self._synth_fish(
            clean,
            voice_id,
            reference_audio_path=reference_audio_path,
            reference_text=reference_text,
        )

    async def _synth_eleven(self, text: str, voice_id: str | None) -> bytes | None:
        key = _eleven_key()
        native_voice_id = await self.resolve_voice(voice_id)
        if not key or not native_voice_id:
            _log_voice_failure(
                "eleven_synth",
                detail=f"missing {'api_key' if not key else 'voice_id'}",
            )
            return None
        payload = {
            "text": text[:5000],
            "model_id": ELEVEN_TTS_MODEL,
            "language_code": "zh",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.85,
                "style": 0.35,
                "use_speaker_boost": True,
                "speed": 1.0,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    f"{ELEVEN_API_BASE}/v1/text-to-speech/{native_voice_id}",
                    headers={"xi-api-key": key, "Content-Type": "application/json"},
                    params={"output_format": ELEVEN_OUTPUT_FORMAT},
                    json=payload,
                )
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            _log_voice_failure("eleven_synth", exc)
            return None

    async def _synth_fish(
        self,
        text: str,
        voice_id: str | None,
        *,
        reference_audio_path: str | Path | None = None,
        reference_text: str | None = None,
    ) -> bytes | None:
        if not FISH_API_KEY:
            _log_voice_failure("fish_synth", detail="missing FISH_API_KEY")
            return None
        reference_id = await self.resolve_voice(voice_id)
        headers: dict[str, str] = {
            "Authorization": f"Bearer {FISH_API_KEY}",
            "Content-Type": "application/json",
            "model": FISH_MODEL,
        }
        try:
            payload: dict[str, Any]
            content: bytes | None = None
            ref_path = Path(reference_audio_path) if reference_audio_path else None
            if ref_path and ref_path.exists():
                headers["Content-Type"] = "application/msgpack"
                payload = self._fish_reference_payload(
                    text,
                    ref_path.read_bytes(),
                    reference_text or "你好，很高兴见到你。",
                )
                content = ormsgpack.packb(payload)
            else:
                payload = self._fish_payload(text, reference_id)
            async with httpx.AsyncClient(timeout=180) as client:
                kwargs: dict[str, Any] = {"headers": headers}
                if content is not None:
                    kwargs["content"] = content
                else:
                    kwargs["json"] = payload
                resp = await client.post(f"{FISH_API_BASE}/v1/tts", **kwargs)
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            ref_kind = "audio_reference" if reference_audio_path else "reference_id"
            _log_voice_failure(
                "fish_synth",
                exc,
                detail=f"ref_kind={ref_kind} has_reference_id={bool(reference_id)}",
            )
            return None


store = VoiceClient()
