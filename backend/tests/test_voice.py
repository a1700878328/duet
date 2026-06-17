import ormsgpack
import pytest

from app import rooms as rooms_mod
from app import voice as voice_mod
from app.voice import VoiceClient


class FakeResponse:
    content = b"mp3-bytes"

    def json(self):
        return {}

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    posted = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, headers=None, json=None, content=None):
        self.posted.append((url, headers, json, content))
        return FakeResponse()


def test_design_description_maps_to_stable_placeholder() -> None:
    client = VoiceClient()

    first = client.design_reference_id("成年女性，低沉沙哑，尾音带笑")
    second = client.design_reference_id("成年女性，低沉沙哑，尾音带笑")

    assert first == second
    assert first.startswith(("eleven-design-", "fish-design-", "fish_clone-design-"))


def test_preview_padding_stays_in_dialogue() -> None:
    text = voice_mod._ensure_preview_text("你好，我是林晚。我会认真听你说话。")

    assert 0 < len(text) <= voice_mod.VOICE_PREVIEW_MAX_CHARS
    assert "保持角色本人" not in text
    assert "根据你的情绪" not in text
    assert "语音设计" not in text
    assert "林晚" in text


def test_manual_voice_description_is_used_for_design() -> None:
    manual = "年轻女性，小恶魔法师感，清亮偏低的女声。"

    assert rooms_mod._manual_voice_design(manual) == manual
    assert rooms_mod._manual_voice_design("fish-clone:abcdef123456") is None
    assert rooms_mod._manual_voice_design("eleven:abcdef123456") is None


@pytest.mark.asyncio
async def test_voice_reference_fallback_is_character_line(monkeypatch) -> None:
    class ShortBrain:
        temperature = 0
        max_tokens = 0

        async def complete(self, _messages):
            return "你好。"

    monkeypatch.setattr(rooms_mod, "default_provider", lambda: ShortBrain())

    line = await rooms_mod._voice_reference_text(
        "公会会长",
        "冒险者公会会长，威严的管理者，负责审核新人委托。",
        "银灰色辫发，锐利眼神",
    )

    assert rooms_mod.VOICE_REFERENCE_MIN_CHARS <= len(line)
    assert len(line) <= rooms_mod.VOICE_REFERENCE_MAX_CHARS
    assert "公会会长" in line
    assert "委托" in line
    assert "保持角色本人" not in line
    assert "语音设计" not in line


@pytest.mark.asyncio
async def test_reference_id_is_used_directly() -> None:
    client = VoiceClient()

    assert await client.resolve_voice("fish:model_abcdef123456") == "model_abcdef123456"
    assert await client.resolve_voice("model_abcdef123456") == "model_abcdef123456"


@pytest.mark.asyncio
async def test_synth_calls_fish_s2_pro_with_inline_tags(monkeypatch) -> None:
    FakeAsyncClient.posted = []
    monkeypatch.setattr(voice_mod, "VOICE_PROVIDER", "fish")
    monkeypatch.setattr(voice_mod, "FISH_API_KEY", "test-key")
    monkeypatch.setattr(voice_mod, "FISH_DEFAULT_REFERENCE_ID", "default_ref")
    monkeypatch.setattr(voice_mod.httpx, "AsyncClient", FakeAsyncClient)

    audio = await VoiceClient().synth("等等！", "fish:model_abcdef123456")

    assert audio == b"mp3-bytes"
    _url, headers, payload, content = FakeAsyncClient.posted[0]
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["model"] == "s2-pro"
    assert content is None
    assert payload["reference_id"] == "model_abcdef123456"
    assert payload["model"] == "s2-pro"
    assert payload["text"].startswith("[excited]")
    assert payload["temperature"] == voice_mod.FISH_TEMPERATURE
    assert payload["top_p"] == voice_mod.FISH_TOP_P
    assert payload["prosody"]["speed"] == voice_mod.FISH_SPEED


@pytest.mark.asyncio
async def test_synth_sends_msgpack_references(monkeypatch, tmp_path) -> None:
    FakeAsyncClient.posted = []
    ref = tmp_path / "ref.mp3"
    ref.write_bytes(b"reference-audio")
    monkeypatch.setattr(voice_mod, "VOICE_PROVIDER", "fish")
    monkeypatch.setattr(voice_mod, "FISH_API_KEY", "test-key")
    monkeypatch.setattr(voice_mod.httpx, "AsyncClient", FakeAsyncClient)

    audio = await VoiceClient().synth(
        "你好。",
        "年轻女性，清澈冷静",
        reference_audio_path=ref,
        reference_text="你好，我是测试角色。",
    )

    assert audio == b"mp3-bytes"
    _url, headers, payload, content = FakeAsyncClient.posted[0]
    assert headers["Content-Type"] == "application/msgpack"
    assert payload is None
    decoded = ormsgpack.unpackb(content)
    assert decoded["model"] == "s2-pro"
    assert decoded["references"][0]["audio"] == b"reference-audio"
    assert decoded["references"][0]["text"] == "你好，我是测试角色。"
    assert "reference_id" not in decoded


@pytest.mark.asyncio
async def test_fish_tags_use_reference_context(monkeypatch, tmp_path) -> None:
    FakeAsyncClient.posted = []
    ref = tmp_path / "ref.mp3"
    ref.write_bytes(b"reference-audio")
    monkeypatch.setattr(voice_mod, "VOICE_PROVIDER", "fish_clone")
    monkeypatch.setattr(voice_mod, "FISH_API_KEY", "test-key")
    monkeypatch.setattr(voice_mod.httpx, "AsyncClient", FakeAsyncClient)

    await VoiceClient().synth(
        "骑士大人，契约上的小字可不是装饰哦。",
        "fish-clone:test",
        reference_audio_path=ref,
        reference_text="哎呀，缺钱花了对吧？利息嘛，就比上次多那么一丢丢。",
    )

    _url, _headers, _payload, content = FakeAsyncClient.posted[0]
    decoded = ormsgpack.unpackb(content)
    assert decoded["text"].startswith("[happy][chuckling]")
    assert (
        len(decoded["references"][0]["text"])
        <= voice_mod.VOICE_REFERENCE_PAYLOAD_MAX_CHARS
    )


class FakeElevenResponse:
    content = b"eleven-mp3"

    def __init__(self, payload=None):
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeElevenClient:
    posts = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(
        self, url, *, headers=None, params=None, json=None, data=None, files=None
    ):
        self.posts.append((url, headers, params, json, data, files))
        if url.endswith("/v1/text-to-voice/design"):
            return FakeElevenResponse(
                {
                    "previews": [
                        {
                            "audio_base_64": "cmVmZXJlbmNlLW1wMw==",
                            "generated_voice_id": "generated_123",
                            "media_type": "audio/mpeg",
                            "duration_secs": 1.0,
                            "language": "zh",
                        }
                    ],
                    "text": "preview text",
                }
            )
        if url.endswith("/v1/voices/add"):
            raise RuntimeError("ivc unavailable")
        if url.endswith("/v1/text-to-voice"):
            return FakeElevenResponse({"voice_id": "saved_123"})
        return FakeElevenResponse()


@pytest.mark.asyncio
async def test_eleven_design_saves_preview_when_clone_unavailable(monkeypatch) -> None:
    FakeElevenClient.posts = []
    monkeypatch.setattr(voice_mod, "VOICE_PROVIDER", "eleven")
    monkeypatch.setattr(voice_mod, "ELEVEN_API_KEY", "test-eleven-key")
    monkeypatch.setattr(voice_mod.httpx, "AsyncClient", FakeElevenClient)

    designed = await VoiceClient().design_voice(
        name="林晚",
        voice_description="年轻成年女性，温柔低声，节奏舒缓，带一点笑意",
        reference_text="你好，我是林晚。我会认真听你说话。",
    )

    assert designed is not None
    assert designed.voice_id == "eleven:saved_123"
    assert designed.reference_audio == b"reference-mp3"
    design_payload = FakeElevenClient.posts[0][3]
    assert design_payload["model_id"] == "eleven_ttv_v3"
    assert isinstance(design_payload.get("text"), str)
    assert len(design_payload["text"]) >= 100  # ElevenLabs requires >=100 chars
    assert "auto_generate_text" not in design_payload


@pytest.mark.asyncio
async def test_fish_clone_design_uses_eleven_reference_only(monkeypatch) -> None:
    FakeElevenClient.posts = []
    monkeypatch.setattr(voice_mod, "VOICE_PROVIDER", "fish_clone")
    monkeypatch.setattr(voice_mod, "ELEVEN_API_KEY", "test-eleven-key")
    monkeypatch.setattr(voice_mod, "FISH_API_KEY", "test-fish-key")
    monkeypatch.setattr(voice_mod.httpx, "AsyncClient", FakeElevenClient)

    designed = await VoiceClient().design_voice(
        name="林晚",
        voice_description="年轻成年女性，温柔低声，节奏舒缓，带一点笑意",
        reference_text="你好，我是林晚。我会认真听你说话。",
    )

    assert designed is not None
    assert designed.voice_id.startswith("fish-clone:")
    assert designed.provider == "fish"
    assert designed.reference_audio == b"reference-mp3"
    assert len(FakeElevenClient.posts) == 1
    assert FakeElevenClient.posts[0][0].endswith("/v1/text-to-voice/design")


@pytest.mark.asyncio
async def test_eleven_tts_uses_v3_model(monkeypatch) -> None:
    FakeElevenClient.posts = []
    monkeypatch.setattr(voice_mod, "VOICE_PROVIDER", "eleven")
    monkeypatch.setattr(voice_mod, "ELEVEN_API_KEY", "test-eleven-key")
    monkeypatch.setattr(voice_mod.httpx, "AsyncClient", FakeElevenClient)

    audio = await VoiceClient().synth("你好。", "eleven:saved_123")

    assert audio == b"eleven-mp3"
    url, headers, params, payload, _data, _files = FakeElevenClient.posts[0]
    assert url.endswith("/v1/text-to-speech/saved_123")
    assert headers["xi-api-key"] == "test-eleven-key"
    assert params["output_format"] == "mp3_44100_128"
    assert payload["model_id"] == "eleven_v3"
    assert payload["language_code"] == "zh"
