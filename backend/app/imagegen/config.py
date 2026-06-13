"""Image-gen constants ported from .102 rp_system/config.py.

Local ComfyUI on THIS Windows machine. Prompt/style/size constants and the
CHARACTER_LORAS map are copied verbatim from the source so the ported registry
and guard stay byte-faithful to the authoritative appearance rules.
"""

from __future__ import annotations

from typing import TypedDict

# === Local ComfyUI ===
COMFY_HOST = "127.0.0.1"
COMFY_PORT = 52188
COMFY_MANAGER = 52189
COMFY_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"
MANAGER_URL = f"http://{COMFY_HOST}:{COMFY_MANAGER}"

# === Default sizes / checkpoint ===
DEFAULT_WIDTH = 1216
DEFAULT_HEIGHT = 832
SINGLE_WIDTH = 832  # single-char portrait — Illustrious best practice
SINGLE_HEIGHT = 1216
CHECKPOINT = "oneObsession_v18.safetensors"

STYLE_PREFIX = (
    "masterpiece, best quality, anime screencap, anime coloring, official style, "
    "fake screenshot, classroom of the elite"
)
STYLE_SUFFIX = (
    "cinematic composition, soft lighting, clean lineart, flat anime shading, "
    "detailed eyes"
)
NEGATIVE_PROMPT = (
    "worst quality, low quality, bad anatomy, bad hands, extra fingers, "
    "missing fingers, watermark, text, signature, artist name, painting (medium), "
    "watercolor (medium), thick outlines"
)

# === Duo / single LoRA strengths ===
DUO_LORA_STRENGTH = 0.70  # manual: dual LoRA 0.68-0.72, midpoint
SINGLE_LORA_STRENGTH = 0.85  # single char 0.8-0.9
MAX_TOKENS = 75  # per positive segment token cap

# === ControlNet model used by the duo workflow (verified present locally) ===
OPENPOSE_CONTROLNET = "xinsir_openpose_sdxl.safetensors"


class LoraEntry(TypedDict):
    file: str
    trigger: str
    appearance: str
    voice: str | None


# === Character LoRA map (copied verbatim from rp_system/config.py) ===
CHARACTER_LORAS: dict[str, LoraEntry] = {
    "天泽一夏": {
        "file": "ichika_amasawa-youkoso_jitsuryoku_s4-v2-ixl-anime-soralz.safetensors",
        "trigger": "ichika amasawa (youkoso jitsuryoku)",
        "appearance": "pink hair, twintails, yellow eyes",
        "voice": "amasawa_v9",
    },
    "坂柳有栖": {
        "file": "arisu_sakayanagi-youkoso_jitsuryoku_s4-ixl-anime-soralz.safetensors",
        "trigger": "arisu sakayanagi (youkoso jitsuryoku)",
        "appearance": "grey hair, french braid, purple eyes",
        "voice": "amasawa_v9",
    },
    "堀北铃音": {
        "file": "suzune_horikita-youkoso_jitsuryoku_s4-ixl-anime-soralz.safetensors",
        "trigger": "suzune horikita (youkoso jitsuryoku)",
        "appearance": "black hair, red eyes, hair ribbon",
        "voice": "amasawa_v9",
    },
    "轻井泽惠": {
        "file": "kei_karuizawa-youkoso_jitsuryoku_s4-ixl-anime-soralz.safetensors",
        "trigger": "kei karuizawa (youkoso jitsuryoku)",
        "appearance": "blonde hair, high ponytail, blue eyes",
        "voice": "amasawa_v9",
    },
    "栉田桔梗": {
        "file": "kikyou-kushida-s2-illustriousxl-lora-nochekaiser.safetensors",
        "trigger": "kikyou kushida",
        "appearance": "short hair, blonde hair, red eyes, hairband",
        "voice": "amasawa_v9",
    },
    "一之濑帆波": {
        "file": "Ichinose_Honami_7-outfits_IL.safetensors",
        "trigger": "very long hair, blonde hair, purple eyes, red jacket",
        "appearance": "",
        "voice": "amasawa_v9",
    },
    "鬼龙院枫花": {
        "file": "fuuka_kiryuuin-youkoso_jitsuryoku_s4-ixl-anime-soralz.safetensors",
        "trigger": "fuuka kiryuuin (youkoso jitsuryoku)",
        "appearance": "grey hair, purple eyes",
        "voice": "amasawa_v9",
    },
    "七濑翼": {
        "file": "tsubasa_nanase-youkoso_jitsuryoku_s4-v2-ixl-anime-soralz.safetensors",
        "trigger": "tsubasa nanase (youkoso jitsuryoku)",
        "appearance": "blonde hair, white hair bow",
        "voice": "amasawa_v9",
    },
    "佐仓爱里": {
        "file": "YJSAiri_ILXL_V1.safetensors",
        "trigger": "YJSAiri",
        "appearance": "pink hair, twintails, glasses",
        "voice": "amasawa_v9",
    },
    "松下千秋": {
        "file": "YJSChiaki_ILXL_V1.safetensors",
        "trigger": "YJSChiaki",
        "appearance": "brown hair, wavy hair",
        "voice": "amasawa_v9",
    },
    "王美雨": {
        "file": "ClassroomOfTheElite_WangMei-Yui_IlluXL.safetensors",
        "trigger": "short twintails, blue hair",
        "appearance": "blue hair, short twintails",
        "voice": "amasawa_v9",
    },
    "佐藤麻耶": {
        "file": "ClassroomOfTheElite_SatoMaya_IlluXL.safetensors",
        "trigger": "wavy hair, multicolored hair",
        "appearance": "wavy hair, multicolored hair",
        "voice": "amasawa_v9",
    },
    "白波千寻": {
        "file": "YJSChihiro_ILXL_V1.safetensors",
        "trigger": "YJSChihiro",
        "appearance": "green hair, bob cut, hair flower",
        "voice": "amasawa_v9",
    },
    "橘茜": {
        "file": "YJSAkane_ILXL_V1.safetensors",
        "trigger": "YJSAkane",
        "appearance": "double bun, purple eyes, orange eyes",
        "voice": "amasawa_v9",
    },
    "伊吹澪": {
        "file": "Classroom of the Elite - Mio Ibuki (Morpholi).safetensors",
        "trigger": "MioIbuki",
        "appearance": "short hair, black hair, green eyes",
        "voice": "amasawa_v9",
    },
    "椎名日和": {
        "file": "Hiyori_Shiinai_3-outfits_IL.safetensors",
        "trigger": "long hair, light blue hair, purple eyes, purple ribbon",
        "appearance": "long hair, light blue hair, purple eyes, purple ribbon",
        "voice": "amasawa_v9",
    },
    "茶柱佐枝": {
        "file": "ClassroomOfTheElite_ChabashiraSae_IlluXL.safetensors",
        "trigger": "high ponytail, brown hair, business suit",
        "appearance": "high ponytail, brown hair, business suit",
        "voice": "amasawa_v9",
    },
    "星之宫知惠": {
        "file": "YJSChie_ILXL_V1.safetensors",
        "trigger": "YJSChie",
        "appearance": "twin drills, brown hair",
        "voice": "amasawa_v9",
    },
    "须藤健": {
        "file": "ken_sudou.safetensors",
        "trigger": "ken, red hair, yellow eyes, short hair, 1boy",
        "appearance": "red hair, yellow eyes, short hair",
        "voice": None,
    },
    "绫小路清隆": {
        "file": "Kiyotaka_Ayanokouji.safetensors",
        "trigger": "ayanokouji",
        "appearance": "brown hair, brown eyes, short hair",
        "voice": None,
    },
    "平田洋介": {
        "file": "yousuke_hirata_ilxl.safetensors",
        "trigger": "yousuke_hirata, 1boy",
        "appearance": "brown hair, purple eyes, short hair",
        "voice": None,
    },
}
