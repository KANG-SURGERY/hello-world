"""Event-study / difference-in-differences estimator on the region × month index.

Specification
-------------
    index_rt = Σ_{k≠-1} β_k · (treated_r · 1[event_time = k])
             [ + Σ_{k≠-1} θ_k · (adjacent_r · 1[event_time = k]) ]
             + μ_r + λ_t + ε_rt

μ_r absorbs the permanent level of each region, λ_t absorbs everything common
to all regions in a calendar month (base rate, national cycle, season). What is
left in β_k is the movement of treated regions relative to controls, month by
month around the event.

k = -1 is the omitted reference, so every β is read as "relative to the month
before the event".

Three things this file takes seriously
--------------------------------------
`include_spillover=True` gives adjacent-but-untreated regions their own path
(θ_k) instead of letting them sit in the control group. If the balloon effect is
real, pooling them makes the control group rise, and the treatment effect is
overstated by exactly that rise. The θ_k series is also the estimate of the
balloon effect itself — a side effect worth quantifying, not just a nuisance.

The ATT is a pre/post contrast, mean(β post) − mean(β pre), NOT the plain
average of the post coefficients. Every β is measured relative to k = -1, so a
single noisy month at k = -1 shifts the entire post path by that month's error.
With only a handful of treated regions that error is not small: on the synthetic
benchmark it moved the ATT by a third of the true effect. Differencing against
the whole pre-period average removes it. For the same reason the reported
coefficient path is re-centred on the pre-period mean rather than on k = -1.

Standard errors are clustered by region, but with ~25 regions the cluster-robust
asymptotics are optimistic. `wild_cluster_bootstrap` is provided for that reason
and should be preferred when reporting.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

DEFAULT_WINDOW = (-24, 24)
REFERENCE_K = -1


@dataclass
class EventStudyResult:
    coefficients: pd.DataFrame
    att: float
    att_se: float
    att_ci: tuple[float, float]
    pretrend_pvalue: float
    pretrend_slope: float
    pretrend_se: float
    post_months: int
    n_obs: int
    n_clusters: int
    include_spillover: bool
    spillover_att: float | None
    _fit: object = None
    _att_weights: np.ndarray | None = None
    _design: pd.DataFrame | None = None
    _groups: np.ndarray | None = None

    @property
    def pretrend_detectable_slope(self) -> float:
        """Smallest pre-trend slope this test would catch at 80% power, 5% size."""
        return 2.80 * self.pretrend_se

    @property
    def pretrend_blind_spot(self) -> float:
        """Confound that an undetectable pre-trend could still produce.

        A pre-trend too small for the test to reject does not stop accumulating
        after the policy. Projected across the post window, this is the size of
        spurious 'effect' the design cannot rule out. If it rivals the estimated
        ATT, the study is not informative no matter how clean the p-value looks.
        """
        return self.pretrend_detectable_slope * (self.post_months / 2.0)

    def summary(self) -> str:
        lines = [
            f"관측치 {self.n_obs}  클러스터(지역) {self.n_clusters}",
            f"평균 처치효과(ATT, 사전대비 사후): {self.att:+.4f} log-pt "
            f"({_pct(self.att)}), 95% CI [{_pct(self.att_ci[0])}, {_pct(self.att_ci[1])}]",
            f"사전추세 기울기 = {self.pretrend_slope:+.5f} log-pt/월, p = {self.pretrend_pvalue:.3f}"
            f"{'  ← 평행추세 위배 의심' if self.pretrend_pvalue < 0.05 else ''}",
            f"  탐지가능 최소 기울기 {self.pretrend_detectable_slope:+.5f}/월 → "
            f"이만한 위배는 못 걸러내며, 사후기간에 누적되면 {self.pretrend_blind_spot:+.4f} log-pt의 "
            f"허위효과를 만듭니다",
        ]
        if abs(self.pretrend_blind_spot) > abs(self.att) * 0.5:
            lines.append(
                "  ⚠️ 이 사각지대가 추정 ATT의 절반을 넘습니다 — 사전추세 검정 통과를 "
                "근거로 인과효과를 주장하지 마세요"
            )
        if self.spillover_att is not None:
            lines.append(f"인접지역 파급효과(풍선효과): {self.spillover_att:+.4f} log-pt ({_pct(self.spillover_att)})")
        return "\n".join(lines)


def run(
    index: pd.DataFrame,
    treated: set[str] | list[str],
    event_month: pd.Period | str,
    adjacent: set[str] | list[str] | None = None,
    include_spillover: bool = True,
    window: tuple[int, int] = DEFAULT_WINDOW,
) -> EventStudyResult:
    """Estimate the event study.

    index must have columns region_code, month (Period[M]), log_index.
    When include_spillover is False, adjacent regions are pooled into the
    control group — the naive specification, kept so the bias is measurable.
    """
    treated = set(treated)
    adjacent = set(adjacent or ())
    event = pd.Period(event_month, freq="M")

    panel = _build_panel(index, treated, adjacent, event, window)
    design, treat_terms, spill_terms = _build_design(panel, include_spillover, window)

    model = sm.OLS(panel["log_index"].to_numpy(), design.to_numpy())
    groups = panel["region_code"].to_numpy()
    fit = model.fit(cov_type="cluster", cov_kwds={"groups": groups})

    coefficients = _collect_coefficients(fit, design.columns, treat_terms, spill_terms)
    att, att_se, weights = _did_contrast(fit, design.columns, treat_terms)
    critical = 1.96
    spillover_att = None
    if spill_terms:
        spillover_att, _, _ = _did_contrast(fit, design.columns, spill_terms)
    pretrend_slope, pretrend_se, pretrend_p = _pretrend_test(fit, design.columns, treat_terms)

    return EventStudyResult(
        coefficients=coefficients,
        att=att,
        att_se=att_se,
        att_ci=(att - critical * att_se, att + critical * att_se),
        pretrend_slope=pretrend_slope,
        pretrend_se=pretrend_se,
        pretrend_pvalue=pretrend_p,
        post_months=int(max(panel["event_time"].max(), 0)) + 1,
        n_obs=len(panel),
        n_clusters=panel["region_code"].nunique(),
        include_spillover=include_spillover,
        spillover_att=spillover_att,
        _fit=fit,
        _att_weights=weights,
        _design=design,
        _groups=groups,
    )


def wild_cluster_bootstrap(
    result: EventStudyResult,
    panel_outcome: np.ndarray | None = None,
    replications: int = 999,
    seed: int = 20260805,
) -> tuple[float, float]:
    """Percentile CI for the ATT via a Rademacher wild cluster bootstrap.

    With 25 clusters the cluster-robust CI is too narrow; resampling residuals
    at the cluster level is the standard correction. This is the unrestricted
    variant (WCU), which is appropriate for an interval — for hypothesis
    testing the null-imposed variant (WCR) has better size.
    """
    if result._fit is None or result._design is None:
        raise ValueError("result does not carry its fit; re-run with run()")

    rng = np.random.default_rng(seed)
    X = result._design.to_numpy()
    fitted = result._fit.fittedvalues
    residuals = result._fit.resid
    groups = result._groups
    weights = result._att_weights
    unique_groups = np.unique(groups)
    xtx_inv = np.linalg.pinv(X.T @ X)

    draws = np.empty(replications)
    for i in range(replications):
        signs = rng.choice((-1.0, 1.0), size=len(unique_groups))
        sign_map = dict(zip(unique_groups, signs))
        perturbed = fitted + residuals * np.array([sign_map[g] for g in groups])
        beta = xtx_inv @ (X.T @ perturbed)
        draws[i] = float(weights @ beta)

    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


# --- internals --------------------------------------------------------------


def _build_panel(
    index: pd.DataFrame,
    treated: set[str],
    adjacent: set[str],
    event: pd.Period,
    window: tuple[int, int],
) -> pd.DataFrame:
    panel = index.copy()
    panel["event_time"] = panel["month"].apply(
        lambda period: (period.year - event.year) * 12 + (period.month - event.month)
    )
    panel = panel.loc[panel["event_time"].between(*window)].copy()
    panel["is_treated"] = panel["region_code"].isin(treated).astype(float)
    panel["is_adjacent"] = panel["region_code"].isin(adjacent).astype(float)
    panel["month_str"] = panel["month"].astype(str)

    if panel["is_treated"].sum() == 0:
        raise ValueError("처치군에 해당하는 지역이 패널에 없습니다")
    if (panel["is_treated"] + panel["is_adjacent"] == 0).sum() == 0:
        raise ValueError("대조군이 비어 있습니다 — 모든 지역이 처치·인접으로 분류되었습니다")
    return panel.reset_index(drop=True)


def _build_design(
    panel: pd.DataFrame,
    include_spillover: bool,
    window: tuple[int, int],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    columns: dict[str, np.ndarray] = {"const": np.ones(len(panel))}
    treat_terms: list[str] = []
    spill_terms: list[str] = []

    present = sorted(set(panel["event_time"]))
    for k in present:
        if k == REFERENCE_K:
            continue
        indicator = (panel["event_time"] == k).to_numpy(dtype=float)
        name = _term_name("tr", k)
        columns[name] = panel["is_treated"].to_numpy() * indicator
        treat_terms.append(name)
        if include_spillover and panel["is_adjacent"].sum() > 0:
            spill_name = _term_name("sp", k)
            columns[spill_name] = panel["is_adjacent"].to_numpy() * indicator
            spill_terms.append(spill_name)

    design = pd.DataFrame(columns, index=panel.index)
    region_dummies = pd.get_dummies(panel["region_code"], prefix="reg", drop_first=True, dtype=float)
    month_dummies = pd.get_dummies(panel["month_str"], prefix="mon", drop_first=True, dtype=float)
    design = pd.concat([design, region_dummies, month_dummies], axis=1)

    # Collinear columns arise when a region-month cell was dropped upstream for
    # thin transaction counts; drop them so the pinv solution stays interpretable.
    keep = _drop_collinear(design)
    design = design[keep]
    treat_terms = [t for t in treat_terms if t in design.columns]
    spill_terms = [t for t in spill_terms if t in design.columns]
    return design, treat_terms, spill_terms


def _drop_collinear(design: pd.DataFrame, tolerance: float = 1e-10) -> list[str]:
    matrix = design.to_numpy(dtype=float)
    _, r = np.linalg.qr(matrix)
    diagonal = np.abs(np.diag(r))
    independent = diagonal > tolerance * max(diagonal.max(), 1.0)
    return [column for column, ok in zip(design.columns, independent) if ok]


def _term_name(prefix: str, k: int) -> str:
    return f"{prefix}_{'m' if k < 0 else 'p'}{abs(k):02d}"


def _term_k(name: str) -> int:
    body = name.split("_")[1]
    return -int(body[1:]) if body[0] == "m" else int(body[1:])


def _collect_coefficients(
    fit, columns: pd.Index, treat_terms: list[str], spill_terms: list[str]
) -> pd.DataFrame:
    """Coefficient paths, re-centred on the pre-period mean.

    Raw coefficients are relative to k = -1. That single month carries its own
    sampling error, which would otherwise appear as a level shift across the
    whole path. Subtracting the pre-period mean puts the baseline on all the
    pre-event information instead of one month of it.
    """
    positions = {name: i for i, name in enumerate(columns)}
    records = []
    for label, terms in (("treated", treat_terms), ("adjacent", spill_terms)):
        if not terms:
            continue
        estimates = {_term_k(t): (fit.params[positions[t]], fit.bse[positions[t]]) for t in terms}
        # The omitted reference period is a structural zero, not missing data.
        estimates[REFERENCE_K] = (0.0, 0.0)

        pre_values = [value for k, (value, _) in estimates.items() if k <= REFERENCE_K]
        baseline = float(np.mean(pre_values)) if pre_values else 0.0

        for k, (value, se) in sorted(estimates.items()):
            centred = value - baseline
            records.append(
                {
                    "series": label,
                    "event_time": k,
                    "estimate": centred,
                    "se": se,
                    "ci_low": centred - 1.96 * se,
                    "ci_high": centred + 1.96 * se,
                }
            )
    return pd.DataFrame(records).sort_values(["series", "event_time"]).reset_index(drop=True)


def _did_contrast(fit, columns: pd.Index, terms: list[str]) -> tuple[float, float, np.ndarray]:
    """mean(post coefficients) − mean(pre coefficients), with its standard error.

    The pre-period mean includes k = -1, whose coefficient is a structural zero;
    it contributes to the denominator but not the numerator. Building the
    estimand as one linear combination means the standard error comes straight
    from the (clustered) covariance matrix and accounts for the correlation
    between the two halves.
    """
    positions = {name: i for i, name in enumerate(columns)}
    post = [t for t in terms if _term_k(t) >= 0]
    pre = [t for t in terms if _term_k(t) < REFERENCE_K]
    weights = np.zeros(len(columns))
    if not post:
        return float("nan"), float("nan"), weights

    for term in post:
        weights[positions[term]] += 1.0 / len(post)
    if pre:
        n_pre = len(pre) + 1  # + the structural zero at k = -1
        for term in pre:
            weights[positions[term]] -= 1.0 / n_pre

    estimate = float(weights @ fit.params)
    variance = float(weights @ fit.cov_params() @ weights)
    return estimate, float(np.sqrt(max(variance, 0.0))), weights


def _pretrend_test(fit, columns: pd.Index, treat_terms: list[str]) -> tuple[float, float, float]:
    """Test for pre-event divergence as a single-df linear slope contrast.

    Returns (slope per month, standard error, p-value).

    The textbook joint Wald test on every pre-period coefficient is not usable
    here: the cluster-robust covariance matrix has rank at most (clusters − 1),
    so with 25 regions a 23-restriction test is rank-deficient and its p-value
    is meaningless. A slope contrast is one restriction, so the rank stays
    valid, and it is the most powerful linear test against the alternative that
    actually threatens the design — a treated group already drifting before the
    policy. Weights sum to zero, so the choice of baseline period drops out.

    Power is still limited. Passing this test is weak evidence for parallel
    trends, never proof; read it next to the plotted path.
    """
    pre_terms = sorted((t for t in treat_terms if _term_k(t) < REFERENCE_K), key=_term_k)
    if len(pre_terms) < 2:
        return float("nan"), float("nan"), float("nan")

    positions = {name: i for i, name in enumerate(columns)}
    # k = -1 is part of the pre-period with a structural zero coefficient: it
    # belongs in the centring and scaling, but contributes no design column.
    pre_ks = [_term_k(t) for t in pre_terms] + [REFERENCE_K]
    mean_k = float(np.mean(pre_ks))
    scale = float(np.sum([(k - mean_k) ** 2 for k in pre_ks]))

    restriction = np.zeros((1, len(columns)))
    for term in pre_terms:
        restriction[0, positions[term]] = (_term_k(term) - mean_k) / scale

    slope = float(restriction[0] @ fit.params)
    se = float(np.sqrt(max(restriction[0] @ fit.cov_params() @ restriction[0], 0.0)))
    return slope, se, float(fit.f_test(restriction).pvalue)


def _pct(value: float) -> str:
    return f"{(np.exp(value) - 1) * 100:+.2f}%"
