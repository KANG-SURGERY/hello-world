"""Run the event study on real transactions cached in data/raw/.

    python scripts/run_event_study.py --policy 2018-08-27
    python scripts/run_event_study.py --policy 2018-08-27 --basis effective

Refuses to run on an unverified policy entry unless --allow-unverified is
passed: a wrong treated-region list silently invalidates every number, and that
failure is invisible in the output.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from policysim import event_study, hedonic, plotting, policies, regions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"


def main() -> int:
    args = _parse_args()
    policy = policies.load_policy(args.policy)

    if not policy.verified and not args.allow_unverified:
        print(f"[{policy.id}] 원장 항목이 아직 원문 대조 전(verified: false)입니다.", file=sys.stderr)
        print("  국토교통부 보도자료로 대상 지역·시행일을 확인한 뒤 verified: true 로 바꾸거나,", file=sys.stderr)
        print("  결과가 무의미할 수 있음을 감수하고 --allow-unverified 를 쓰세요.", file=sys.stderr)
        return 2

    # Check identifiability before touching data: "this design needs another
    # method" is the more useful message, and it should not be hidden behind a
    # missing-data error.
    if not policy.is_identifiable:
        print(f"[{policy.id}] {policy.unidentified_reason}", file=sys.stderr)
        return 2

    transactions = _load_raw()
    if transactions.empty:
        print(f"{RAW} 에 데이터가 없습니다. 먼저 scripts/fetch_transactions.py 를 실행하세요.",
              file=sys.stderr)
        return 2

    adjacency = regions.load_adjacency()
    exposure = regions.classify_exposure(set(policy.require_regions()), adjacency)
    treated = {c for c, s in exposure.items() if s == "treated"}
    adjacent = {c for c, s in exposure.items() if s == "adjacent"}

    event_month = pd.Period(policy.event_date(args.basis), freq="M")
    print(f"정책 {policy.name} ({policy.id}), 기준 = {args.basis} ({event_month})")
    print(f"거래 {len(transactions):,}건 / 지역 {transactions['region_code'].nunique()}개")

    index = hedonic.build_index(transactions)
    result = event_study.run(
        index=index,
        treated=treated,
        adjacent=adjacent,
        event_month=event_month,
        include_spillover=not args.pool_adjacent,
    )

    print(f"\n{result.summary()}")
    low, high = event_study.wild_cluster_bootstrap(result)
    print(f"wild cluster bootstrap 95% CI: [{low:+.4f}, {high:+.4f}]")

    figure = plotting.plot_event_study(
        result,
        RESULTS / "figures" / f"event_study_{policy.id}_{args.basis}.png",
        title=f"Event study — policy {policy.id} ({args.basis} basis)",
    )
    out = RESULTS / f"coefficients_{policy.id}_{args.basis}.csv"
    result.coefficients.to_csv(out, index=False)
    print(f"\n계수 {out.relative_to(ROOT)}\n그림 {figure.relative_to(ROOT)}")

    print("\n두 기준일(announced / effective)을 모두 돌려 비교하세요. "
          "차이가 크면 예고효과가 존재한다는 뜻입니다.")
    return 0


def _load_raw() -> pd.DataFrame:
    files = sorted(RAW.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    frame = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    frame["month"] = pd.PeriodIndex(frame["month"].astype(str), freq="M")
    return frame


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, help="정책 원장의 id")
    parser.add_argument("--basis", choices=["announced", "effective"], default="announced")
    parser.add_argument("--pool-adjacent", action="store_true",
                        help="인접지역을 대조군에 포함 (SUTVA 위반 — 비교용으로만)")
    parser.add_argument("--allow-unverified", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
