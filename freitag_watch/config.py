from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
PUBLIC_DIR = ROOT / "public"
SITE_SOURCE_DIR = ROOT / "site"


@dataclass(frozen=True)
class ProductTarget:
    key: str
    model: str
    name: str
    slug: str
    family: str
    legacy: bool = False


# F640 and RF640 are intentionally separate sources. A 404 from the legacy
# F640 page is recorded as source-unavailable, never as proof of sell-out.
TARGETS: Tuple[ProductTarget, ...] = (
    ProductTarget("F171", "F171", "LAURA", "f171-laura", "F171"),
    ProductTarget("F705", "F705", "SECRID X FREITAG", "f705-secrid-x-freitag", "F705"),
    ProductTarget("F141", "F141", "BERYL", "f141-beryl", "F141"),
    ProductTarget("F640", "F640", "ROLLIN", "f640-rollin", "F640", legacy=True),
    ProductTarget("RF640", "RF640", "ROLLIN", "rf640-rollin", "F640"),
    ProductTarget("F41", "F41", "HAWAII FIVE-0", "f41-hawaii-five-0", "F41"),
)


def locale() -> str:
    return os.getenv("FREITAG_LOCALE", "en_US")


def product_url(target: ProductTarget) -> str:
    return f"https://freitag.ch/{locale()}/products/{target.slug}"


def website_url() -> str:
    explicit = os.getenv("WEBSITE_URL", "").rstrip("/")
    if explicit:
        return explicit
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}"
    return ""


USER_AGENT = "FreitagWatch/0.1 (personal inventory monitor; hourly; public product pages only)"
