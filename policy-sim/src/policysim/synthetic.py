"""Synthetic transaction generator with a known ground truth.

Purpose: validate the estimators before pointing them at real data. The DGP
deliberately plants the three traps this project exists to handle, so a correct
pipeline must recover TRUE_EFFECT and a naive one must visibly fail:

  1. Composition shift — after the policy, treated regions trade relatively
     older units. A raw mean-price index therefore falls by more than the
     true constant-quality effect. Hedonic adjustment is what removes this.
  2. Spillover — untreated neighbours rise (풍선효과). Using them as controls
     double-counts the gap and overstates the effect magnitude.
  3. Volume collapse — treated post-period transaction counts drop (매물 잠김),
     which widens standard errors exactly where the signal is needed.

The generated frame has the same columns as molit.fetch_month, so downstream
code cannot tell the two apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- ground truth -----------------------------------------------------------
TRUE_EFFECT = -0.040        # log-point effect on treated, constant quality
TRUE_SPILLOVER = 0.025      # log-point effect on untreated neighbours
RAMP_MONTHS = 6             # effects phase in linearly over this many months

# --- hedonic surface used to generate prices --------------------------------
BETA_LOG_AREA = -0.15       # larger units carry a lower price per m2
BETA_FLOOR_RATIO = 0.08
BETA_AGE = -0.006           # per year of building age
NOISE_SD = 0.12


@dataclass
class SyntheticTruth:
    effect: float = TRUE_EFFECT
    spillover: float = TRUE_SPILLOVER
    ramp_months: int = RAMP_MONTHS
    treated: list[str] = field(default_factory=list)
    adjacent: list[str] = field(default_factory=list)
    far: list[str] = field(default_factory=list)
    event_month: pd.Period | None = None
    parallel_trends: bool = True

    def average_effect(self, max_k: int, series: str = "treated") -> float:
        """True ATT averaged over post-event months k = 0..max_k.

        Not the same as `effect`: the effect phases in over ramp_months, so an
        estimator averaging the whole post window is targeting this smaller
        number. Comparing an ATT estimate against the fully-ramped effect makes
        an unbiased estimator look biased.
        """
        size = self.effect if series == "treated" else self.spillover
        return float(np.mean([size * _ramp(k, self.ramp_months) for k in range(max_k + 1)]))


def simulate(
    exposure: dict[str, str],
    event_month: str = "2018-08",
    start: str = "2015-01",
    end: str = "2021-12",
    base_transactions: int = 80,
    seed: int = 20260805,
    parallel_trends: bool = True,
) -> tuple[pd.DataFrame, SyntheticTruth]:
    """Generate transaction-level data for the given region exposure map.

    parallel_trends=True makes the identifying assumption hold *in this
    realised sample*, not merely in expectation, which is what an estimator
    validation needs. With only a handful of treated regions, an independent
    draw of region drifts leaves a sizeable differential trend by chance, and
    the resulting bias would be wrongly read as a defect of the estimator.

    parallel_trends=False deliberately gives treated regions their own extra
    trend, so the pre-trend diagnostic can be checked for power.
    """
    rng = np.random.default_rng(seed)
    months = pd.period_range(start=start, end=end, freq="M")
    event = pd.Period(event_month, freq="M")
    codes = sorted(exposure)

    # Region-level heterogeneity: a permanent level and a private drift, so
    # regions are not on identical paths by construction.
    base_level = dict(zip(codes, rng.normal(np.log(9_000_000), 0.25, size=len(codes))))
    drift = dict(zip(codes, rng.normal(0.0015, 0.0010, size=len(codes))))
    if parallel_trends:
        drift = _balance_group_trends(drift, exposure)
    else:
        for code in codes:
            if exposure[code] == "treated":
                drift[code] += 0.0012  # ~2.9 log-pt divergence over 24 months

    # Common macro path shared by every region (rates, cycle) — absorbed by the
    # month fixed effect in estimation.
    macro = np.cumsum(rng.normal(0.0025, 0.006, size=len(months)))

    rows: list[pd.DataFrame] = []
    for month_index, month in enumerate(months):
        months_since = (month - event).n
        ramp = _ramp(months_since, RAMP_MONTHS)

        for code in codes:
            status = exposure[code]
            effect = 0.0
            if status == "treated":
                effect = TRUE_EFFECT * ramp
            elif status == "adjacent":
                effect = TRUE_SPILLOVER * ramp

            # Trap 3: volume collapses in treated regions after the policy.
            intensity = base_transactions
            if status == "treated" and months_since >= 0:
                intensity *= 1.0 - 0.40 * ramp
            count = rng.poisson(intensity)
            if count == 0:
                continue

            area = np.clip(rng.lognormal(np.log(78), 0.32, size=count), 20, 260)
            floor_ratio = rng.uniform(0.05, 1.0, size=count)

            # Trap 1: post-policy treated transactions skew towards older stock.
            age_shift = 8.0 * ramp if (status == "treated" and months_since >= 0) else 0.0
            age = np.clip(rng.gamma(shape=3.0, scale=5.0, size=count) + age_shift, 0, 55)

            log_price_per_m2 = (
                base_level[code]
                + drift[code] * month_index
                + macro[month_index]
                + effect
                + BETA_LOG_AREA * np.log(area / 85.0)
                + BETA_FLOOR_RATIO * floor_ratio
                + BETA_AGE * age
                + rng.normal(0.0, NOISE_SD, size=count)
            )

            rows.append(
                pd.DataFrame(
                    {
                        "region_code": code,
                        "month": month,
                        "price_krw": np.exp(log_price_per_m2) * area,
                        "area_m2": area,
                        "floor_ratio": floor_ratio,
                        "build_year": month.year - age.round().astype(int),
                        "floor": np.maximum(1, (floor_ratio * 20).round().astype(int)),
                    }
                )
            )

    frame = pd.concat(rows, ignore_index=True)
    truth = SyntheticTruth(
        treated=[c for c in codes if exposure[c] == "treated"],
        adjacent=[c for c in codes if exposure[c] == "adjacent"],
        far=[c for c in codes if exposure[c] == "far"],
        event_month=event,
        parallel_trends=parallel_trends,
    )
    return frame, truth


def _balance_group_trends(
    drift: dict[str, float], exposure: dict[str, str]
) -> dict[str, float]:
    """Shift drifts so every exposure group shares the same mean trend.

    Within-group heterogeneity is preserved; only the between-group difference
    that would violate parallel trends is removed.
    """
    overall = float(np.mean(list(drift.values())))
    groups: dict[str, list[str]] = {}
    for code, status in exposure.items():
        groups.setdefault(status, []).append(code)

    balanced = dict(drift)
    for members in groups.values():
        group_mean = float(np.mean([drift[code] for code in members]))
        for code in members:
            balanced[code] += overall - group_mean
    return balanced


def _ramp(months_since: int, ramp_months: int) -> float:
    if months_since < 0:
        return 0.0
    return min(1.0, (months_since + 1) / ramp_months)
