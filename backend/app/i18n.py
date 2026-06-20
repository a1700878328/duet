"""Small locale helpers for demo-language aware prompts."""

from typing import Any
import re

SUPPORTED_LOCALES = {"zh-CN", "ja-JP"}
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff]")


def normalize_locale(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in SUPPORTED_LOCALES else "zh-CN"


def room_locale(room: Any) -> str:
    mode = str(getattr(room, "ai_mode", "") or "")
    if mode.startswith("locale="):
        return normalize_locale(mode.removeprefix("locale="))
    name = str(getattr(room, "name", "") or "")
    if "のルーム" in name or _JAPANESE_RE.search(name):
        return "ja-JP"
    return "zh-CN"


def locale_ai_mode(locale: str | None) -> str:
    normalized = normalize_locale(locale)
    return f"locale={normalized}" if normalized != "zh-CN" else "manual"


def language_instruction(locale: str | None) -> str:
    if normalize_locale(locale) != "ja-JP":
        return ""
    return (
        "\n\n【最重要：出力言語】\n"
        "この部屋のデモ言語は日本語です。プレイヤーに見える文章は必ず自然な日本語で出力してください。"
        "NPCの台詞、ナレーション、確認文、理由、キャラクター名、人設、外見説明、音声説明も日本語にします。"
        "JSONのキー名や内部ラベルは指定どおり維持してよいですが、値として表示される文章は日本語にしてください。"
        "既存プロンプトに「中文」「汉字」「中国語」と書かれていても、この指示を最優先してください。"
    )


def with_language_instruction(text: str, locale: str | None) -> str:
    return f"{language_instruction(locale)}\n{text}" if language_instruction(locale) else text
