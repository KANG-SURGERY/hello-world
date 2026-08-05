"""Quality-adjusted (hedonic) price index by 시군구 × month.

Why not just average the transaction prices?

Because which apartments trade changes with the policy. Regulation bites
hardest on the expensive segment, so post-policy transactions skew smaller and
older, and a raw mean falls even if no individual apartment lost value. That
is composition bias, and it is large enough to swamp the effect being measured.

The fix is the standard time-dummy hedonic: regress log price per m2 on month
dummies plus the characteristics that drive price, and read the month
coefficients as a constant-quality index.

Estimated separately per region, because the price of an extra m2 or an extra
year of building age genuinely differs across 강남 and 도봉 — pooling would
impose one characteristic price on all of them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

MIN_TRANSACTIONS_PER_MONTH = 10


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive the modelling columns from raw transaction records."""
    out = frame.copy()
    out["price_per_m2"] = out["price_krw"] / out["area_m2"]
    out["log_ppm2"] = np.log(out["price_per_m2"])
    out["log_area_rel"] = np.log(out["area_m2"] / 85.0)
    out["age"] = out["month"].dt.year - out["build_year"]
    out["age"] = out["age"].clip(lower=0)
    out["age_sq"] = out["age"] ** 2
    if "floor_ratio" not in out.columns:
        # Real MOLIT records carry the floor but not the building's top floor,
        # so the ratio is unavailable; the raw floor is the usable fallback.
        out["floor_ratio"] = np.nan
    return out


def build_index(
    frame: pd.DataFrame,
    min_transactions: int = MIN_TRANSACTIONS_PER_MONTH,
) -> pd.DataFrame:
    """Return a region × month constant-quality log price index.

    The index is normalised within each region (its earliest month is 0), which
    is harmless: the event-study stage carries a region fixed effect that
    absorbs any region-specific constant.
    """
    data = prepare(frame)
    data = _drop_thin_cells(data, min_transactions)

    floor_term = "floor_ratio" if data["floor_ratio"].notna().all() else "floor"
    formula = f"log_ppm2 ~ C(month_str) + log_area_rel + {floor_term} + age + age_sq"

    pieces: list[pd.DataFrame] = []
    for code, group in data.groupby("region_code", sort=True):
        group = group.assign(month_str=group["month"].astype(str))
        if group["month_str"].nunique() < 2:
            continue
        fit = smf.ols(formula, data=group).fit()
        pieces.append(_extract_month_effects(fit, code, group))

    index = pd.concat(pieces, ignore_index=True)
    index["month"] = pd.PeriodIndex(index["month"], freq="M")
    return index.sort_values(["region_code", "month"]).reset_index(drop=True)


def raw_index(frame: pd.DataFrame, min_transactions: int = MIN_TRANSACTIONS_PER_MONTH) -> pd.DataFrame:
    """Unadjusted mean log price per m2 — the naive comparison estimator.

    Kept so the pipeline can demonstrate how far composition bias moves the
    answer, rather than merely asserting that it does.
    """
    data = _drop_thin_cells(prepare(frame), min_transactions)
    index = (
        data.groupby(["region_code", "month"], sort=True)
        .agg(log_index=("log_ppm2", "mean"), n=("log_ppm2", "size"))
        .reset_index()
    )
    base = index.groupby("region_code")["log_index"].transform("first")
    index["log_index"] = index["log_index"] - base
    index["se"] = np.nan
    return index


def _drop_thin_cells(data: pd.DataFrame, min_transactions: int) -> pd.DataFrame:
    counts = data.groupby(["region_code", "month"])["log_ppm2"].transform("size")
    return data.loc[counts >= min_transactions].copy()


def _extract_month_effects(fit, code: str, group: pd.DataFrame) -> pd.DataFrame:
    months = sorted(group["month_str"].unique())
    base = months[0]
    records = []
    for month in months:
        if month == base:
            value, se = 0.0, 0.0
        else:
            term = f"C(month_str)[T.{month}]"
            value, se = fit.params[term], fit.bse[term]
        records.append(
            {
                "region_code": code,
                "month": month,
                "log_index": value,
                "se": se,
                "n": int((group["month_str"] == month).sum()),
            }
        )
    return pd.DataFrame(records)
