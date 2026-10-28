from PIL import Image, ImageDraw

from freitag_watch.analyzer import analyze_image


def test_plain_bright_color_is_not_rare():
    image = Image.new("RGB", (256, 256), "#ff2500")
    result = analyze_image(image)
    assert result["level"] == "普通"
    assert result["worth_email"] is False


def test_solid_color_with_busy_photo_background_is_not_email_worthy():
    image = Image.new("RGB", (300, 300), "#e6e2d8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 299, 54), fill="#252525")
    draw.rectangle((0, 245, 299, 299), fill="#252525")
    draw.line((0, 80, 299, 170), fill="#4d718f", width=18)
    draw.line((0, 210, 299, 100), fill="#96744b", width=12)
    draw.rectangle((65, 70, 235, 235), fill="#e02a22")
    result = analyze_image(image)
    assert result["worth_email"] is False
    assert result["reference_match"]["matched"] is False


def test_strong_geometric_print_gets_explainable_signal():
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 256, 20):
        draw.rectangle((x, 0, x + 9, 255), fill="black")
    result = analyze_image(image)
    assert result["score"] >= 14
    assert any(category.startswith("B") for category in result["categories"])
    assert "边缘" in result["reason"] or "条纹" in result["reason"]


def _transparent_bag(fill="white"):
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 170, 442, 430), fill=fill)
    return image


def test_transparent_background_does_not_turn_plain_bag_into_rare_email():
    image = _transparent_bag("#ffe145")
    draw = ImageDraw.Draw(image)
    draw.rectangle((230, 170, 285, 430), fill="#d54b45")
    result = analyze_image(image)
    assert result["worth_email"] is False
    assert result["reference_match"]["matched"] is False


def test_reference_like_complex_illustration_is_email_worthy():
    image = _transparent_bag("#f4ead0")
    draw = ImageDraw.Draw(image)
    for y in range(180, 425, 18):
        draw.line((75, y, 435, 430 - (y - 180) // 2), fill="black", width=5)
    for x in range(90, 430, 45):
        draw.ellipse((x, 220, x + 30, 300), outline="#7b194f", width=6)
        draw.rectangle((x + 8, 300, x + 22, 395), fill="#174d91")
    result = analyze_image(image)
    assert result["worth_email"] is True
    assert result["reference_match"]["matched"] is True
    assert any(category.startswith("R") for category in result["categories"])


def test_photo_like_texture_alone_is_candidate_not_email():
    image = Image.new("RGB", (256, 256), "#777777")
    draw = ImageDraw.Draw(image)
    for x in range(0, 256, 6):
        shade = 85 + (x * 7 % 100)
        draw.line((x, 0, 255 - x // 2, 255), fill=(shade, shade, shade), width=2)
    result = analyze_image(image)
    assert result["worth_email"] is False
    assert result["reference_match"]["matched"] is False
