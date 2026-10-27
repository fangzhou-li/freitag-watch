from __future__ import annotations

from urllib.robotparser import RobotFileParser

import requests

from .config import TARGETS, USER_AGENT, product_url


ROBOTS_URL = "https://freitag.ch/robots.txt"


def verify_access_policy(timeout: float = 20.0) -> str:
    """Fail closed if the current robots policy cannot be checked or disallows products."""
    response = requests.get(ROBOTS_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    parser = RobotFileParser()
    parser.set_url(ROBOTS_URL)
    parser.parse(response.text.splitlines())
    denied = [product_url(target) for target in TARGETS if not parser.can_fetch(USER_AGENT, product_url(target))]
    if denied:
        raise RuntimeError(f"FREITAG robots.txt 当前不允许采集商品页：{denied}")
    if not any(line.strip().lower() == "disallow: /api" for line in response.text.splitlines()):
        # This is informational: the monitor never calls /api regardless.
        return "商品页允许访问；/api 规则与首次核验时不同，但本项目仍不访问 /api"
    return "商品页允许访问；/api 禁止访问且本项目未使用该路径"

