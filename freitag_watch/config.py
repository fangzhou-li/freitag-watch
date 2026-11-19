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
    # F-Archive: discontinued models sold to F-ederation members. Their
    # individual product pages are public (same __NEXT_DATA__ inventory
    # payload as regular models), so no login is needed to monitor them.
    ProductTarget("F52-X", "F52-X", "MIAMI VICE", "f52-x-miami-vice", "F-ARCHIVE"),
    ProductTarget("F201-X", "F201-X", "PETE", "f201-x-pete", "F-ARCHIVE"),
    ProductTarget("F07-X", "F07-X", "CHUCK", "f07-x-chuck", "F-ARCHIVE"),
    ProductTarget("F08-X", "F08-X", "DAN", "f08-x-dan", "F-ARCHIVE"),
    ProductTarget("F729", "F729", "EXTRA+LARGE", "f729-extralarge", "F-ARCHIVE"),
    ProductTarget("RF533", "RF533", "FAY", "rf533-fay", "F-ARCHIVE"),
    ProductTarget("RF555", "RF555", "CAROLINE", "rf555-caroline", "F-ARCHIVE"),
    ProductTarget("F558", "F558", "LEONARD", "f558-leonard", "F-ARCHIVE"),
    ProductTarget("F560", "F560", "STERLING", "f560-sterling", "F-ARCHIVE"),
    ProductTarget("F600", "F600", "CARTER", "f600-carter", "F-ARCHIVE"),
    ProductTarget("F660", "F660", "JIMMY", "f660-jimmy", "F-ARCHIVE"),
    ProductTarget("F733", "F733", "ZIPPELIN", "f733-zippelin", "F-ARCHIVE"),
    ProductTarget("RF725", "RF725", "TRUE BLUE BRANDON", "rf725-true-blue-brandon", "F-ARCHIVE"),
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
