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
    return {
        "entropy": round(entropy, 3),
        "edge_density": round(edge_density, 4),
        "meaningful_colors": float(meaningful_colors),
        "dominant_color_ratio": round(dominant_ratio, 4),
        "row_jump_ratio": round(row_jumps, 4),
        "column_jump_ratio": round(col_jumps, 4),
        "saturation": round(saturation, 4),
    }


def analyze_image(
    image: Image.Image,
    historical_hashes: Sequence[str] = (),
) -> Dict[str, Any]:
    """Conservative, explainable, no-paid-API pattern analysis.

    Brightness/saturation alone never awards points. Category C is deliberately
    reported as an icon/illustration candidate, not a definitive object claim.
    """
    metrics = _visual_metrics(image)
    ocr_text, ocr_available = _ocr(image)
    phash = _average_hash(image)
    score = 0
    categories: List[str] = []
    reasons: List[str] = []
    strong_signals = 0

    compact_text = re.sub(r"[^A-Za-z0-9]", "", ocr_text)
    if len(compact_text) >= 3:
        text_points = min(55, 30 + len(compact_text) * 2)
        score += text_points
        categories.append("A 文字与印刷标志")
        reasons.append(f"OCR 识别到可辨认字符“{ocr_text[:60]}”")
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

    score = min(100, score)
    if score >= 65 and strong_signals >= 1:
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
        "worth_email": level == "疑似稀有",
        "ocr_text": ocr_text,
        "ocr_available": ocr_available,
        "perceptual_hash": phash,
        "metrics": metrics,
        "method": "本地可解释规则（OCR、边缘、色块、历史感知哈希），未使用付费视觉 API",
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

