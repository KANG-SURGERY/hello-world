"""Load and validate the policy ledger."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import regions

_LEDGER_PATH = Path(__file__).resolve().parents[2] / "config" / "policies.yaml"

# Designs that event_study cannot identify, with the reason. Kept explicit so a
# caller gets a clear error instead of a silently meaningless estimate.
_UNIDENTIFIED = {
    "ALL_SEOUL": (
        "서울 전역이 처치되어 within-Seoul 대조군이 없습니다. "
        "synthetic control 또는 타 광역시 대조군 설계를 쓰세요."
    ),
    "PRICE_BASED": (
        "처치가 지역이 아니라 가격 구간으로 배정되었습니다. "
        "가격 경계를 이용한 regression discontinuity 설계를 쓰세요."
    ),
}


@dataclass(frozen=True)
class Policy:
    id: str
    name: str
    verified: bool
    announced_date: dt.date
    effective_date: dt.date
    treated_regions: list[str]
    levers: dict[str, Any]
    # Set when the design cannot be identified by a region-based event study.
    # Recorded rather than raised at load time, so one unidentifiable entry does
    # not make the rest of the ledger unreadable.
    unidentified_reason: str | None = None

    @property
    def is_identifiable(self) -> bool:
        return self.unidentified_reason is None

    def require_regions(self) -> list[str]:
        """Treated regions, or a clear failure if this design needs another method."""
        if self.unidentified_reason is not None:
            raise ValueError(f"[{self.id}] {self.unidentified_reason}")
        return self.treated_regions

    def event_date(self, basis: str = "announced") -> dt.date:
        """Event reference date.

        'announced' captures the anticipation response, 'effective' the
        mechanical one. They can differ by months and give different
        estimates — run both and report the pair, never just the convenient one.
        """
        if basis == "announced":
            return self.announced_date
        if basis == "effective":
            return self.effective_date
        raise ValueError(f"basis must be 'announced' or 'effective', got {basis!r}")


def load_ledger(path: Path | None = None) -> dict[str, Policy]:
    raw = yaml.safe_load((path or _LEDGER_PATH).read_text(encoding="utf-8"))
    return {entry["id"]: _build(entry) for entry in raw["policies"]}


def load_policy(policy_id: str, path: Path | None = None) -> Policy:
    ledger = load_ledger(path)
    if policy_id not in ledger:
        raise KeyError(f"{policy_id!r} not in ledger. Available: {sorted(ledger)}")
    return ledger[policy_id]


def _build(entry: dict[str, Any]) -> Policy:
    treated = entry["treated_regions"]
    reason: str | None = None
    codes: list[str] = []

    if isinstance(treated, str):
        if treated not in _UNIDENTIFIED:
            raise ValueError(f"[{entry['id']}] unknown treated_regions marker {treated!r}")
        reason = _UNIDENTIFIED[treated]
    else:
        unknown = [code for code in treated if code not in regions.SEOUL]
        if unknown:
            raise ValueError(
                f"[{entry['id']}] treated regions outside the Seoul code table: {unknown}"
            )
        codes = list(treated)

    return Policy(
        id=entry["id"],
        name=entry["name"],
        verified=bool(entry.get("verified", False)),
        announced_date=_as_date(entry["announced_date"]),
        effective_date=_as_date(entry["effective_date"]),
        treated_regions=codes,
        levers=dict(entry.get("levers", {})),
        unidentified_reason=reason,
    )


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))
