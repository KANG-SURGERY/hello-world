"""Region codes (법정동코드 5-digit prefix, a.k.a. LAWD_CD) and adjacency.

The MOLIT transaction API is queried one 시군구 at a time using the 5-digit
LAWD_CD. Codes below cover Seoul's 25 자치구 and are stable.

To extend beyond Seoul, download the official 법정동코드 list from
https://www.code.go.kr and keep the first 5 digits of rows whose 폐지여부 is
존재. Do not hand-type codes: several 경기 시 have 구-level codes that are easy
to confuse with their 시-level parent.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SEOUL: dict[str, str] = {
    "11110": "종로구",
    "11140": "중구",
    "11170": "용산구",
    "11200": "성동구",
    "11215": "광진구",
    "11230": "동대문구",
    "11260": "중랑구",
    "11290": "성북구",
    "11305": "강북구",
    "11320": "도봉구",
    "11350": "노원구",
    "11380": "은평구",
    "11410": "서대문구",
    "11440": "마포구",
    "11470": "양천구",
    "11500": "강서구",
    "11530": "구로구",
    "11545": "금천구",
    "11560": "영등포구",
    "11590": "동작구",
    "11620": "관악구",
    "11650": "서초구",
    "11680": "강남구",
    "11710": "송파구",
    "11740": "강동구",
}

_ADJACENCY_PATH = Path(__file__).resolve().parents[2] / "config" / "adjacency_seoul.yaml"


def name_of(code: str) -> str:
    return SEOUL.get(code, code)


def load_adjacency(path: Path | None = None) -> dict[str, list[str]]:
    """Land-adjacency between Seoul districts, as {code: [neighbour codes]}.

    Han-river crossings are deliberately excluded: spillover works through
    substitutability for buyers, and a river crossing is a much weaker
    substitute than a shared land border despite the short distance.
    """
    path = path or _ADJACENCY_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    adjacency = {code: sorted(set(neighbours)) for code, neighbours in raw["adjacency"].items()}
    _assert_symmetric(adjacency)
    return adjacency


def _assert_symmetric(adjacency: dict[str, list[str]]) -> None:
    for code, neighbours in adjacency.items():
        for neighbour in neighbours:
            if neighbour not in adjacency:
                raise ValueError(f"{neighbour} appears as a neighbour of {code} but has no entry")
            if code not in adjacency[neighbour]:
                raise ValueError(f"adjacency is not symmetric: {code}-{neighbour}")


def classify_exposure(
    treated: set[str],
    adjacency: dict[str, list[str]],
) -> dict[str, str]:
    """Split every region into treated / adjacent / far.

    'adjacent' regions are untreated but border a treated one, so they are the
    prime suspects for the balloon effect (풍선효과). Using them as controls
    violates SUTVA and biases the estimated treatment effect away from zero,
    which is exactly why they are separated out rather than pooled.
    """
    exposure: dict[str, str] = {}
    for code in adjacency:
        if code in treated:
            exposure[code] = "treated"
        elif any(neighbour in treated for neighbour in adjacency[code]):
            exposure[code] = "adjacent"
        else:
            exposure[code] = "far"
    return exposure
