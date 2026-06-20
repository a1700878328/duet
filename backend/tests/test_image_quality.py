from PIL import Image, ImageDraw

from app.imagegen.quality import assess_image_quality


def test_scene_quality_rejects_white_framed_image(tmp_path):
    path = tmp_path / "framed.png"
    img = Image.new("RGB", (800, 1200), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((180, 220, 620, 980), fill=(20, 30, 50))
    img.save(path)

    quality = assess_image_quality(path, kind="scene")

    assert not quality.ok
    assert "white_border_or_frame" in quality.reasons


def test_scene_quality_accepts_full_bleed_scene(tmp_path):
    path = tmp_path / "full_bleed.png"
    img = Image.new("RGB", (800, 1200), (24, 34, 60))
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, 160, 720, 1120), fill=(90, 45, 120))
    draw.ellipse((180, 140, 360, 330), fill=(235, 225, 230))
    draw.ellipse((440, 150, 620, 340), fill=(220, 190, 165))
    img.save(path)

    quality = assess_image_quality(path, kind="scene")

    assert quality.ok


def test_scene_quality_rejects_black_letterbox(tmp_path):
    path = tmp_path / "letterbox.png"
    img = Image.new("RGB", (900, 600), (40, 48, 70))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 900, 90), fill=(0, 0, 0))
    draw.rectangle((0, 510, 900, 600), fill=(0, 0, 0))
    draw.rectangle((120, 130, 780, 470), fill=(80, 90, 140))
    img.save(path)

    quality = assess_image_quality(path, kind="scene")

    assert not quality.ok
    assert "black_border_or_letterbox" in quality.reasons


def test_reference_quality_rejects_black_foreground_occlusion(tmp_path):
    path = tmp_path / "reference_black_occlusion.png"
    img = Image.new("RGB", (832, 1216), (38, 48, 80))
    draw = ImageDraw.Draw(img)
    draw.rectangle((180, 120, 680, 1120), fill=(88, 94, 150))
    draw.polygon(((0, 0), (330, 0), (0, 520)), fill=(0, 0, 0))
    draw.polygon(((832, 1216), (510, 1216), (832, 760)), fill=(0, 0, 0))
    img.save(path)

    quality = assess_image_quality(path, kind="reference")

    assert not quality.ok
    assert "black_border_or_foreground_occlusion" in quality.reasons
