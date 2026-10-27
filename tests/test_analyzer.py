from PIL import Image, ImageDraw

from freitag_watch.analyzer import analyze_image


def test_plain_bright_color_is_not_rare():
    image = Image.new("RGB", (256, 256), "#ff2500")
    result = analyze_image(image)
    assert result["level"] == "普通"
    assert result["worth_email"] is False


def test_strong_geometric_print_gets_explainable_signal():
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 256, 20):
        draw.rectangle((x, 0, x + 9, 255), fill="black")
    result = analyze_image(image)
    assert result["score"] >= 14
    assert any(category.startswith("B") for category in result["categories"])
    assert "边缘" in result["reason"] or "条纹" in result["reason"]

