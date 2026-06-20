"""Lightweight generated-image quality gates.

These checks intentionally catch only obvious failures. They are not an aesthetic
judge; they prevent known bad outputs such as white framed scenes, blank white
backgrounds, and tiny subjects from being accepted without a retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageStat

QualityKind = Literal["avatar", "reference", "scene"]


@dataclass(frozen=True)
class ImageQuality:
    ok: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float]


def _non_white_bbox(rgb: Image.Image, *, threshold: int = 242) -> tuple[int, int, int, int] | None:
    width, height = rgb.size
    mask = Image.new("L", rgb.size, 0)
    src = rgb.load()
    dst = mask.load()
    for y in range(height):
        for x in range(width):
            r, g, b = src[x, y]
            if not (r > threshold and g > threshold and b > threshold):
                dst[x, y] = 255
    return mask.getbbox()


def _edge_color_ratios(rgb: Image.Image) -> tuple[float, float]:
    width, height = rgb.size
    band = max(4, min(width, height) // 20)
    crops = (
        rgb.crop((0, 0, width, band)),
        rgb.crop((0, height - band, width, height)),
        rgb.crop((0, 0, band, height)),
        rgb.crop((width - band, 0, width, height)),
    )
    total_pixels = sum(crop.size[0] * crop.size[1] for crop in crops)
    if not total_pixels:
        return 0.0
    white = 0
    black = 0
    for crop in crops:
        raw = crop.tobytes()
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            if r > 242 and g > 242 and b > 242:
                white += 1
            elif r < 12 and g < 12 and b < 12:
                black += 1
    return white / total_pixels, black / total_pixels


def assess_image_quality(path: str | Path, *, kind: QualityKind) -> ImageQuality:
    reasons: list[str] = []
    metrics: dict[str, float] = {}
    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            width, height = rgb.size
            total = float(width * height)
            bbox = _non_white_bbox(rgb)
            edge_white, edge_black = _edge_color_ratios(rgb)
            stat = ImageStat.Stat(rgb)
            mean_brightness = sum(stat.mean) / 3.0
            metrics.update(
                {
                    "width": float(width),
                    "height": float(height),
                    "edge_white_ratio": edge_white,
                    "edge_black_ratio": edge_black,
                    "mean_brightness": mean_brightness,
                }
            )
            if bbox is None:
                return ImageQuality(
                    False,
                    ("blank_or_all_white",),
                    metrics,
                )
            left, top, right, bottom = bbox
            bbox_area = ((right - left) * (bottom - top)) / total
            bbox_width = (right - left) / width
            bbox_height = (bottom - top) / height
            metrics.update(
                {
                    "non_white_bbox_area": bbox_area,
                    "non_white_bbox_width": bbox_width,
                    "non_white_bbox_height": bbox_height,
                }
            )
    except Exception:
        return ImageQuality(False, ("unreadable_image",), metrics)

    if kind == "scene":
        if edge_white > 0.45:
            reasons.append("white_border_or_frame")
        if edge_black > 0.38:
            reasons.append("black_border_or_letterbox")
        if bbox_area < 0.55:
            reasons.append("scene_subject_or_background_too_small")
        if mean_brightness > 238 and bbox_area < 0.72:
            reasons.append("overbright_sparse_scene")
    elif kind == "reference":
        if edge_white > 0.62 and mean_brightness > 232:
            reasons.append("plain_white_reference_background")
        if edge_black > 0.34:
            reasons.append("black_border_or_foreground_occlusion")
        if bbox_area < 0.36:
            reasons.append("reference_character_too_small")
    else:
        if bbox_area < 0.42:
            reasons.append("avatar_face_too_small_or_sparse")
        if edge_black > 0.42:
            reasons.append("black_border_or_foreground_occlusion")
        if edge_white > 0.70 and mean_brightness > 235:
            reasons.append("plain_white_avatar")

    return ImageQuality(not reasons, tuple(reasons), metrics)


def annotate_quality_result(result: dict, *, kind: QualityKind) -> dict:
    path = result.get("path")
    if not path:
        return result
    quality = assess_image_quality(path, kind=kind)
    annotated = dict(result)
    annotated["quality_ok"] = quality.ok
    annotated["quality_reasons"] = list(quality.reasons)
    annotated["quality_metrics"] = quality.metrics
    return annotated
