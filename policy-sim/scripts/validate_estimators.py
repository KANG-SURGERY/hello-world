"""Validate the estimators against synthetic data with a known effect.

Run this before trusting any number the pipeline produces on real transactions.
It is the same discipline as a simulation study before an observational
analysis: if an estimator cannot recover an effect that was planted by hand,
its estimate on real data means nothing.

Three specifications are compared against the same ground truth:

  A. hedonic index + far-region controls + spillover modelled   (correct)
  B. hedonic index + adjacent regions pooled into the control   (SUTVA violated)
  C. raw mean index + far-region controls + spillover modelled  (composition bias)

Expected: A recovers the truth, B overstates the magnitude by roughly the
balloon effect, C overstates it by the composition shift.

Usage: python scripts/validate_estimators.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from policysim import event_study, hedonic, plotting, policies, regions, synthetic  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
POLICY_ID = "2018-08-27"


def main() -> int:
    policy = policies.load_policy(POLICY_ID)
    adjacency = regions.load_adjacency()
    exposure = regions.classify_exposure(set(policy.require_regions()), adjacency)

    treated = {c for c, s in exposure.items() if s == "treated"}
    adjacent = {c for c, s in exposure.items() if s == "adjacent"}
    far = {c for c, s in exposure.items() if s == "far"}

    print(f"정책: {policy.name} ({policy.id})")
    print(f"  처치 {len(treated)}개 {_names(treated)}")
    print(f"  인접 {len(adjacent)}개 {_names(adjacent)}")
    print(f"  원거리 {len(far)}개 (대조군)")
    if not policy.verified:
        print("  ⚠️ 이 정책 항목은 원문 대조 전(verified: false)입니다 — 합성데이터 검증에만 사용")

    event_month = pd.Period(policy.event_date("announced"), freq="M")
    print(f"\n합성 데이터 생성 (참값: 처치 {synthetic.TRUE_EFFECT:+.3f}, "
          f"파급 {synthetic.TRUE_SPILLOVER:+.3f} log-pt)")
    transactions, truth = synthetic.simulate(exposure, event_month=str(event_month))
    print(f"  거래 {len(transactions):,}건, {transactions['month'].nunique()}개월, "
          f"{transactions['region_code'].nunique()}개 지역")

    adjusted = hedonic.build_index(transactions)
    unadjusted = hedonic.raw_index(transactions)

    specs = {
        "A. 헤도닉 + 파급효과 분리 (정상)": dict(index=adjusted, include_spillover=True),
        "B. 헤도닉 + 인접지역을 대조군에 포함 (SUTVA 위반)": dict(index=adjusted, include_spillover=False),
        "C. 원시 평균가 + 파급효과 분리 (구성편의)": dict(index=unadjusted, include_spillover=True),
    }

    # The effect phases in over ramp_months, so an ATT averaged across the whole
    # post window targets a smaller number than the fully-ramped effect.
    max_k = event_study.DEFAULT_WINDOW[1]
    target_att = truth.average_effect(max_k)
    target_spillover = truth.average_effect(max_k, series="adjacent")

    rows = []
    results: dict[str, event_study.EventStudyResult] = {}
    for label, spec in specs.items():
        result = event_study.run(
            index=spec["index"],
            treated=treated,
            adjacent=adjacent,
            event_month=event_month,
            include_spillover=spec["include_spillover"],
        )
        results[label] = result
        rows.append(
            {
                "specification": label,
                "ATT": round(result.att, 4),
                "bias": round(result.att - target_att, 4),
                "95% CI": f"[{result.att_ci[0]:+.4f}, {result.att_ci[1]:+.4f}]",
                "spillover": None if result.spillover_att is None else round(result.spillover_att, 4),
                "pretrend slope": round(result.pretrend_slope, 5),
                "pretrend p": round(result.pretrend_pvalue, 3),
            }
        )

    print(f"\n{'=' * 78}")
    print(f"추정 결과 (참값 ATT = {target_att:+.4f}, 참값 파급 = {target_spillover:+.4f})")
    print(f"  최종효과는 {truth.effect:+.4f}이지만 {truth.ramp_months}개월에 걸쳐 점증하므로")
    print(f"  사후 {max_k + 1}개월 평균의 참값은 {target_att:+.4f}입니다.")
    print("=" * 78)
    print(pd.DataFrame(rows).to_string(index=False))

    correct = results["A. 헤도닉 + 파급효과 분리 (정상)"]
    low, high = event_study.wild_cluster_bootstrap(correct)
    print(f"\n[A] wild cluster bootstrap 95% CI: [{low:+.4f}, {high:+.4f}]"
          f"  (클러스터 {correct.n_clusters}개 — 군집수가 적어 이쪽을 보고할 것)")
    print(f"\n[A] {correct.summary()}")

    figure = plotting.plot_event_study(
        correct,
        RESULTS / "figures" / "event_study_synthetic.png",
        title="Synthetic validation (2018-08-27 style design)",
        truth=truth.effect,
    )
    print(f"\n그림 저장: {figure.relative_to(RESULTS.parent)}")

    violation = _pretrend_power_check(exposure, treated, adjacent, event_month, target_att)

    return _verdict(rows, target_att, target_spillover, violation)


def _pretrend_power_check(exposure, treated, adjacent, event_month, target_att: float) -> dict:
    """Re-run on a DGP that breaks parallel trends, and see what the test does.

    The lesson here is not that the diagnostic works — it is where it stops
    working. The slope is estimated accurately, but with four treated regions
    the standard error is wide enough that a violation large enough to destroy
    the ATT still fails to reject at 5%. Pre-trend tests are underpowered
    (Roth 2022); 'the pre-trend test passed' is not evidence of anything much.
    """
    true_slope = 0.0012
    print(f"\n{'=' * 78}\n진단 검정력 확인: 평행추세를 의도적으로 위배한 DGP\n{'=' * 78}")
    transactions, _ = synthetic.simulate(
        exposure, event_month=str(event_month), parallel_trends=False
    )
    result = event_study.run(
        index=hedonic.build_index(transactions),
        treated=treated,
        adjacent=adjacent,
        event_month=event_month,
        include_spillover=True,
    )
    print(f"  참값 기울기 {true_slope:+.5f}/월 → 추정 {result.pretrend_slope:+.5f}/월 "
          f"(SE {result.pretrend_se:.5f}), p = {result.pretrend_pvalue:.3f}")
    print(f"  ATT는 {result.att:+.4f}로 오염됨 (참값 {target_att:+.4f}, "
          f"편의 {result.att - target_att:+.4f})")
    print(f"  → 기울기는 정확히 추정되지만 p로는 기각되지 않습니다. "
          f"이 설계가 80% 검정력으로 잡을 수 있는 최소 기울기는 "
          f"{result.pretrend_detectable_slope:.5f}/월입니다.")
    print("  → 교훈: 사전추세 검정 '통과'는 평행추세의 증거가 아닙니다. "
          "탐지가능 최소치를 함께 보고하세요.")
    return {
        "slope": result.pretrend_slope,
        "true_slope": true_slope,
        "att_bias": result.att - target_att,
    }


def _verdict(rows: list[dict], target_att: float, target_spillover: float, violation: dict) -> int:
    correct, pooled, raw = rows[0], rows[1], rows[2]
    checks = [
        ("A가 참값을 CI 안에 포함", _covers(correct["95% CI"], target_att)),
        ("A의 편의 < 0.01", abs(correct["bias"]) < 0.01),
        ("A의 파급효과 추정이 참값 부근", abs((correct["spillover"] or 0) - target_spillover) < 0.01),
        ("A의 사전추세가 0 부근", abs(correct["pretrend slope"]) < 0.0003),
        ("B가 효과를 과대추정", pooled["ATT"] < correct["ATT"] - 0.005),
        ("C가 효과를 과대추정", raw["ATT"] < correct["ATT"] - 0.005),
        # The diagnostic's job is to measure the violation, not to reject it —
        # rejection is beyond its power at this sample size.
        ("위배 시 기울기를 정확히 추정", abs(violation["slope"] - violation["true_slope"]) < 0.0004),
        ("위배가 실제로 ATT를 오염시킴", abs(violation["att_bias"]) > 0.01),
    ]
    print(f"\n{'=' * 78}\n검증\n{'=' * 78}")
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    failed = [label for label, passed in checks if not passed]
    print("\n결론: " + ("추정기가 참값을 복원합니다." if not failed else f"실패 {len(failed)}건 — {failed}"))
    return 0 if not failed else 1


def _covers(interval: str, value: float) -> bool:
    low, high = (float(part) for part in interval.strip("[]").split(","))
    return low <= value <= high


def _names(codes: set[str]) -> str:
    return "(" + ", ".join(sorted(regions.name_of(c) for c in codes)) + ")"


if __name__ == "__main__":
    raise SystemExit(main())
