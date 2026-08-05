"""Client for the MOLIT apartment sale-transaction API (국토교통부 실거래가).

Endpoint: apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev
Key: issue a 서비스키 at data.go.kr and export it as MOLIT_API_KEY.

Two notes that cost time if missed:

1. The response has been served with Korean tag names (거래금액, 전용면적, …)
   and, on newer revisions, English ones (dealAmount, excluUseAr, …). The
   parser accepts both rather than assuming; check `unmapped_fields()` after a
   first pull to see whether the schema moved again.
2. `거래금액` is in 만원 with thousands separators and leading whitespace.
   It is normalised to KRW here so nothing downstream has to remember.

This module is untested against the live API in the environment it was written
in (outbound access to data.go.kr was blocked by network policy), so treat the
first real pull as a verification step: run scripts/fetch_transactions.py for a
single 구 and month and eyeball the frame before pulling years of history.
"""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import pandas as pd
import requests

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

# Canonical name -> tag names seen in the wild (Korean revision, English revision).
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "deal_amount": ("거래금액", "dealAmount"),
    "build_year": ("건축년도", "buildYear"),
    "deal_year": ("년", "dealYear"),
    "deal_month": ("월", "dealMonth"),
    "deal_day": ("일", "dealDay"),
    "area_m2": ("전용면적", "excluUseAr"),
    "floor": ("층", "floor"),
    "region_code": ("지역코드", "sggCd"),
    "dong": ("법정동", "umdNm"),
    "apt_name": ("아파트", "aptNm"),
}


class MolitError(RuntimeError):
    pass


@dataclass
class FetchResult:
    frame: pd.DataFrame
    unmapped: set[str]


def fetch_month(
    region_code: str,
    year_month: str,
    api_key: str | None = None,
    rows: int = 1000,
    timeout: int = 30,
    max_retries: int = 4,
) -> FetchResult:
    """Fetch one 시군구 × one month of apartment sales.

    year_month is 'YYYYMM'. The API pages, so this walks pages until a short
    page comes back.
    """
    api_key = api_key or os.environ.get("MOLIT_API_KEY")
    if not api_key:
        raise MolitError("MOLIT_API_KEY is not set (issue one at data.go.kr)")

    records: list[dict[str, str]] = []
    unmapped: set[str] = set()
    page = 1
    while True:
        root = _request(
            {
                "serviceKey": api_key,
                "LAWD_CD": region_code,
                "DEAL_YMD": year_month,
                "pageNo": str(page),
                "numOfRows": str(rows),
            },
            timeout=timeout,
            max_retries=max_retries,
        )
        items = root.findall(".//item")
        for item in items:
            record, extra = _parse_item(item)
            records.append(record)
            unmapped |= extra
        if len(items) < rows:
            break
        page += 1

    return FetchResult(frame=_to_frame(records), unmapped=unmapped)


def _request(params: dict[str, str], timeout: int, max_retries: int) -> ET.Element:
    delay = 2.0
    last: Exception | None = None
    for _ in range(max_retries):
        try:
            response = requests.get(ENDPOINT, params=params, timeout=timeout)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            _raise_for_api_error(root)
            return root
        except (requests.RequestException, ET.ParseError) as exc:
            last = exc
            time.sleep(delay)
            delay *= 2
    raise MolitError(f"request failed after {max_retries} attempts: {last}")


def _raise_for_api_error(root: ET.Element) -> None:
    """data.go.kr returns HTTP 200 with an error code in the body."""
    code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
    if code is not None and code.strip() not in {"00", "000"}:
        message = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "unknown"
        raise MolitError(f"API error {code.strip()}: {message.strip()}")


def _parse_item(item: ET.Element) -> tuple[dict[str, str], set[str]]:
    record: dict[str, str] = {}
    seen: set[str] = set()
    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            value = item.findtext(alias)
            if value is not None:
                record[canonical] = value.strip()
                seen.add(alias)
                break
    extra = {child.tag for child in item} - seen
    return record, extra


def _to_frame(records: list[dict[str, str]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(
            columns=["region_code", "month", "price_krw", "area_m2", "floor", "build_year"]
        )

    frame = pd.DataFrame(records)
    # 거래금액 arrives as ' 82,500' meaning 82,500만원.
    frame["price_krw"] = (
        frame["deal_amount"].str.replace(",", "", regex=False).astype("int64") * 10_000
    )
    frame["area_m2"] = frame["area_m2"].astype("float64")
    frame["floor"] = frame["floor"].astype("int64")
    frame["build_year"] = frame["build_year"].astype("int64")
    frame["month"] = pd.PeriodIndex(
        year=frame["deal_year"].astype(int), month=frame["deal_month"].astype(int), freq="M"
    )
    frame["region_code"] = frame["region_code"].astype(str).str.slice(0, 5)

    keep = ["region_code", "month", "price_krw", "area_m2", "floor", "build_year", "apt_name"]
    return frame[[column for column in keep if column in frame.columns]]
