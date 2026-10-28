from __future__ import annotations

import io
import math
import re
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageFilter, ImageStat

from .config import USER_AGENT


REFERENCE_PROFILE_VERSION = "2026-10-28-user-reference-v2"


def _longest_run(values: Sequence[bool]) -> Optional[Tuple[int, int]]:
    best: Optional[Tuple[int, int]] = None
    start: Optional[int] = None
    for index, value in enumerate([*values, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if best is None or index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    return best


def _prepare_analysis_image(image: Image.Image) -> Image.Image:
    """Isolate the printable bag body from transparent official cutouts.

    FREITAG's PNGs use transparency around the product. Converting those files
    directly to RGB turns the empty area black, overwhelms all metrics, and can
    make seams look like OCR text. Dense alpha rows reliably remove handles and
    straps while retaining the main printed body for every monitored model.
    """
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] == 255:
        return image.convert("RGB")
    bbox = alpha.getbbox()
    if not bbox:
        return image.convert("RGB")
    rgba = rgba.crop(bbox)
    alpha = rgba.getchannel("A")

    sample_width = min(240, rgba.width)
    sample_height = max(1, round(rgba.height * sample_width / max(1, rgba.width)))
    sampled = alpha.resize((sample_width, sample_height), Image.Resampling.BILINEAR)
    pixels = list(sampled.getdata())
    dense_rows = []
    for row in range(sample_height):
        values = pixels[row * sample_width:(row + 1) * sample_width]
        coverage = sum(1 for value in values if value >= 96) / sample_width
        dense_rows.append(coverage >= 0.30)
    run = _longest_run(dense_rows)
    if run and run[1] - run[0] >= max(3, round(sample_height * 0.12)):
        top = max(0, round(run[0] * rgba.height / sample_height) - round(rgba.height * 0.03))
        bottom = min(rgba.height, round(run[1] * rgba.height / sample_height) + round(rgba.height * 0.03))
        rgba = rgba.crop((0, top, rgba.width, bottom))
        alpha = rgba.getchannel("A")

    content_bbox = alpha.getbbox()
    if content_bbox:
        rgba = rgba.crop(content_bbox)
    inset_x = round(rgba.width * 0.04)
    inset_y = round(rgba.height * 0.04)
    if rgba.width > inset_x * 2 + 10 and rgba.height > inset_y * 2 + 10:
        rgba = rgba.crop((inset_x, inset_y, rgba.width - inset_x, rgba.height - inset_y))
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _entropy(image: Image.Image) -> float:
    histogram = image.histogram()
    total = float(sum(histogram)) or 1.0
    return -sum((count / total) * math.log2(count / total) for count in histogram if count)


def _average_hash(image: Image.Image) -> str:
    small = image.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
    values = list(small.getdata())
    mean = sum(values) / len(values)
    bits = "".join("1" if value >= mean else "0" for value in values)
    return f"{int(bits, 2):064x}"


def _hash_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (ValueError, AttributeError):
        # Python 3.9 compatibility.
        try:
            return bin(int(left, 16) ^ int(right, 16)).count("1")
        except ValueError:
            return 0


def _ocr(image: Image.Image) -> Tuple[str, bool]:
    executable = shutil.which("tesseract")
    if not executable:
        return "", False
    stream = io.BytesIO()
    image.convert("RGB").save(stream, format="PNG")
    try:
        completed = subprocess.run(
            [executable, "stdin", "stdout", "-l", "eng", "--psm", "11"],
            input=stream.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", True
    text = completed.stdout.decode("utf-8", errors="ignore")
    text = " ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9&+._-]*", text))
    return text[:160], True


def _visual_metrics(image: Image.Image) -> Dict[str, float]:
    rgb = image.convert("RGB")
    rgb.thumbnail((320, 320), Image.Resampling.LANCZOS)
    gray = rgb.convert("L")
    entropy = _entropy(gray)

    edges = gray.filter(ImageFilter.FIND_EDGES)
    pixels = list(edges.getdata())
    edge_density = sum(1 for value in pixels if value > 48) / max(1, len(pixels))

    # Remove tarp grain, seams and lighting noise before measuring semantic
    # structure. Large printed figures remain after this blur; ordinary tarp
    # texture and compression noise mostly disappear.
    coarse = rgb.filter(ImageFilter.GaussianBlur(radius=max(2.0, min(rgb.size) / 70.0)))
    coarse_gray = coarse.convert("L")
    coarse_entropy = _entropy(coarse_gray)
    coarse_edges = coarse_gray.filter(ImageFilter.FIND_EDGES)
    coarse_pixels = list(coarse_edges.getdata())
    width, height = coarse_edges.size
    interior = [
        coarse_pixels[y * width + x]
        for y in range(2, max(2, height - 2))
        for x in range(2, max(2, width - 2))
    ]
    coarse_edge_density = sum(1 for value in interior if value > 18) / max(1, len(interior))

    quantized = rgb.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    counts = sorted(quantized.getcolors(maxcolors=256) or [], reverse=True)
    total = sum(count for count, _ in counts) or 1
    meaningful_colors = sum(1 for count, _ in counts if count / total >= 0.025)
    dominant_ratio = (counts[0][0] / total) if counts else 1.0

    profile = gray.resize((64, 64), Image.Resampling.BILINEAR)
    profile_pixels = list(profile.getdata())
    rows = [sum(profile_pixels[row * 64:(row + 1) * 64]) / 64 for row in range(64)]
    cols = [sum(profile_pixels[row * 64 + col] for row in range(64)) / 64 for col in range(64)]
    row_jumps = sum(1 for a, b in zip(rows, rows[1:]) if abs(a - b) > 14) / 63
    col_jumps = sum(1 for a, b in zip(cols, cols[1:]) if abs(a - b) > 14) / 63

    saturation = ImageStat.Stat(rgb.convert("HSV")).mean[1] / 255.0
    hsv_pixels = list(rgb.convert("HSV").resize((96, 96), Image.Resampling.BILINEAR).getdata())
    hue_bins = [0] * 12
    chromatic = 0
    for hue, sat, value in hsv_pixels:
        if sat >= 60 and value >= 35:
            hue_bins[min(11, hue * 12 // 256)] += 1
            chromatic += 1
    meaningful_hues = sum(1 for count in hue_bins if count >= max(8, chromatic * 0.025))
    return {
        "entropy": round(entropy, 3),
        "edge_density": round(edge_density, 4),
        "coarse_entropy": round(coarse_entropy, 3),
        "coarse_edge_density": round(coarse_edge_density, 4),
        "meaningful_colors": float(meaningful_colors),
        "meaningful_hues": float(meaningful_hues),
        "dominant_color_ratio": round(dominant_ratio, 4),
        "row_jump_ratio": round(row_jumps, 4),
        "column_jump_ratio": round(col_jumps, 4),
        "saturation": round(saturation, 4),
    }


def _coherent_ocr_text(text: str) -> str:
    tokens = [token for token in re.findall(r"[A-Za-z0-9]+", text) if token.upper() != "FREITAG"]
    meaningful = []
    for token in tokens:
        letters = re.sub(r"[^A-Za-z]", "", token)
        if len(letters) >= 4 and re.search(r"[AEIOUYaeiouy]", letters):
            meaningful.append(token)
    if len(meaningful) >= 1 or sum(len(token) for token in tokens) >= 14:
        return " ".join(tokens)[:160]
    return ""


def _reference_similarity(metrics: Mapping[str, float], ocr_text: str) -> Dict[str, Any]:
    """Match the user's local reference collection by visual type, not color.

    The private source images are intentionally not embedded in the public
    repository. This profile records only the five visual traits summarized
    from them. A single bright color or ordinary two-color split cannot match.
    """
    entropy = metrics["entropy"]
    edge = metrics["edge_density"]
    hues = metrics.get("meaningful_hues", 0.0)
    dominant = metrics["dominant_color_ratio"]
    saturation = metrics["saturation"]
    directional = max(metrics["row_jump_ratio"], metrics["column_jump_ratio"])
    categories: List[str] = []
    reasons: List[str] = []
    email_scores: List[int] = []
    candidate_scores: List[int] = []

    coherent_text = _coherent_ocr_text(ocr_text)
    if coherent_text and entropy >= 4.5 and edge >= 0.05:
        categories.append("R1 完整文字/印刷主题")
        reasons.append(f"检测到与参考图相似的完整印刷文字“{coherent_text[:60]}”")
        email_scores.append(72)

    # The reference set contains two kinds of structurally rich prints: a
    # limited-palette drawing with many real contours, or a multi-hue image.
    # Requiring hue diversity here is important: tarp grain can create many
    # quantized shades but it remains one hue and must not trigger an email.
    limited_palette_illustration = (
        hues >= 2 and edge >= 0.145 and 0.16 <= saturation <= 0.55
    )
    multihue_illustration = hues >= 3 and edge >= 0.10
    if (
        entropy >= 5.8
        and (limited_palette_illustration or multihue_illustration)
        and dominant <= 0.48
    ):
        categories.append("R2 人物、脸部或具象插画候选")
        reasons.append("细节、轮廓和色块复杂度接近参考图中的人物/漫画/徽章式大幅印花")
        email_scores.append(78)

    subtle_photo_texture = (
        hues >= 3 and saturation <= 0.15 and entropy >= 5.2 and edge >= 0.05
    )
    if subtle_photo_texture and dominant <= 0.46:
        categories.append("R3 摄影场景、物件或复杂纹理候选")
        reasons.append("连续细节与多层次色调接近参考图中的摄影场景、物件或纹理印花")
        # Generic photo-like texture is useful as a review hint, but is too
        # easy for tarp grain, shadows, and studio backgrounds to imitate.
        candidate_scores.append(62)

    if hues >= 3 and saturation <= 0.18 and entropy >= 5.8 and edge >= 0.085 and dominant <= 0.46:
        categories.append("R4 高对比黑白图像")
        reasons.append("低饱和但轮廓与细节丰富，接近参考图中的黑白人物/眼睛图像")
        # Keep monochrome detail as a candidate only; it often describes
        # ordinary tarp texture rather than a distinctive print.
        candidate_scores.append(70)

    spectrum_print = hues >= 8 and entropy >= 4.7
    directional_rainbow = hues >= 3 and saturation >= 0.24 and directional >= 0.15 and edge >= 0.09
    if (spectrum_print or directional_rainbow) and dominant <= 0.48:
        categories.append("R5 彩虹、虹彩或光束图案")
        reasons.append("检测到丰富色相或方向性光束特征，接近参考图中的彩虹/虹彩皮")
        email_scores.append(74)

    score = max(email_scores + candidate_scores, default=0)
    return {
        "version": REFERENCE_PROFILE_VERSION,
        "source_count": 16,
        # Email is intentionally precision-first: require readable print,
        # strongly structured illustration, or a clear spectrum/rainbow.
        # Photo/monochrome texture alone remains visible as a candidate but
        # must not trigger a rare-skin email.
        "matched": bool(email_scores),
        "email_eligible": bool(email_scores),
        "score": score,
        "categories": categories,
        "reason": "；".join(reasons) if reasons else "未命中用户参考稀有皮的主题特征",
    }


def analyze_image(
    image: Image.Image,
    historical_hashes: Sequence[str] = (),
) -> Dict[str, Any]:
    """Conservative, explainable, no-paid-API pattern analysis.

    Brightness/saturation alone never awards points. Category C is deliberately
    reported as an icon/illustration candidate, not a definitive object claim.
    """
    analysis_image = _prepare_analysis_image(image)
    metrics = _visual_metrics(analysis_image)
    ocr_text, ocr_available = _ocr(analysis_image)
    phash = _average_hash(analysis_image)
    score = 0
    categories: List[str] = []
    reasons: List[str] = []
    strong_signals = 0

    coherent_text = _coherent_ocr_text(ocr_text)
    if coherent_text:
        text_points = min(55, 30 + len(coherent_text) * 2)
        score += text_points
        categories.append("A 文字与印刷标志")
        reasons.append(f"OCR 识别到较完整字符“{coherent_text[:60]}”")
        strong_signals += 1

    directional = max(metrics["row_jump_ratio"], metrics["column_jump_ratio"])
    if metrics["edge_density"] >= 0.18 and directional >= 0.08:
        score += 24
        categories.append("B 特殊几何图案")
        reasons.append("检测到高密度边缘和成方向的大面积明暗分割")
        strong_signals += 1
    elif metrics["edge_density"] >= 0.14 or directional >= 0.12:
        score += 14
        categories.append("B 特殊几何图案")
        reasons.append("检测到较明显的条纹/几何边界候选")

    if metrics["meaningful_colors"] >= 5 and metrics["dominant_color_ratio"] <= 0.52:
        score += 12
        if "B 特殊几何图案" not in categories:
            categories.append("B 特殊几何图案")
        reasons.append("多个大面积色块并存，且没有单一颜色占绝对主导")

    # A bounded high-edge, low-palette region is a conservative pictogram
    # candidate. It is never described as a person/animal without a vision model.
    if not ocr_text and 0.20 <= metrics["edge_density"] <= 0.48 and metrics["meaningful_colors"] <= 4:
        score += 15
        categories.append("C 具象/图标候选")
        reasons.append("存在少色、高轮廓密度的图标或插画候选；免费规则无法确认具体对象")

    valid_history = [value for value in historical_hashes if isinstance(value, str) and len(value) == 64]
    if len(valid_history) >= 10:
        nearest = min(_hash_distance(phash, old) for old in valid_history)
        metrics["nearest_history_hash_distance"] = float(nearest)
        if nearest >= 92:
            score += 14
            categories.append("D 历史视觉差异")
            reasons.append(f"与 {len(valid_history)} 件历史样本的感知特征差异较大；这不等同于市场稀缺")
            strong_signals += 1

    # High entropy contributes only together with a structural/text signal, so
    # a bright or noisy colorway alone cannot become rare.
    if metrics["entropy"] >= 7.0 and categories:
        score += 7
        reasons.append("图像细节复杂度高，作为已有印刷/结构信号的辅助证据")

    reference_match = _reference_similarity(metrics, ocr_text)
    if reference_match["matched"]:
        score = max(score, reference_match["score"])
        categories.extend(category for category in reference_match["categories"] if category not in categories)
        reasons.append(reference_match["reason"])
        strong_signals += 1
    elif reference_match["categories"]:
        categories.extend(category for category in reference_match["categories"] if category not in categories)
        reasons.append(reference_match["reason"] + "；仅列为人工复核候选，不触发稀有邮件")

    score = min(100, score)
    if reference_match["matched"]:
        level = "疑似稀有"
    elif score >= 32:
        level = "值得关注"
    else:
        level = "普通"
    if not reasons:
        reasons.append("未检测到稳定文字、显著印刷轮廓或强几何结构；鲜艳颜色不会单独加分")
    confidence = min(0.95, 0.45 + 0.12 * strong_signals + (0.08 if ocr_available else 0.0))
    if level == "普通":
        confidence = max(0.45, confidence - 0.08)
    return {
        "score": score,
        "level": level,
        "categories": categories or ["普通拼色"],
        "reason": "；".join(reasons),
        "confidence": round(confidence, 2),
        "worth_email": bool(reference_match["matched"]),
        "ocr_text": ocr_text,
        "ocr_available": ocr_available,
        "perceptual_hash": phash,
        "metrics": metrics,
        "reference_match": reference_match,
        "method": "用户参考稀有皮特征 v1（文字、具象/摄影、黑白图像、虹彩）+ 本地可解释规则，未使用付费视觉 API",
    }


def analyze_product(product: Mapping[str, Any], historical_hashes: Iterable[str]) -> Dict[str, Any]:
    images = product.get("images") or []
    if not images:
        return {
            "score": 0, "level": "未知", "categories": ["无法分析"],
            "reason": "官方页面没有可用商品图片", "confidence": 0.0,
            "worth_email": False, "method": "未运行", "error": "no_image",
        }
    try:
        response = requests.get(
            images[0], headers={"User-Agent": USER_AGENT}, timeout=30, stream=True
        )
        response.raise_for_status()
        limit = 12 * 1024 * 1024
        payload = response.raw.read(limit + 1, decode_content=True)
        if len(payload) > limit:
            raise ValueError("图片超过 12MB 安全限制")
        image = Image.open(io.BytesIO(payload))
        image.load()
        return analyze_image(image, list(historical_hashes))
    except Exception as exc:  # Keep one image failure from breaking other models.
        return {
            "score": 0, "level": "未知", "categories": ["无法分析"],
            "reason": f"图片分析失败：{exc}", "confidence": 0.0,
            "worth_email": False, "method": "本地可解释规则", "error": str(exc),
        }
