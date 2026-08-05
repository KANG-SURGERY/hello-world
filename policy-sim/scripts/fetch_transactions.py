"""Pull MOLIT apartment sale transactions into data/raw/.

Requires MOLIT_API_KEY (issue one at data.go.kr, 국토교통부 아파트 매매 실거래가
상세 자료). Not runnable from the remote session this was written in — outbound
access to data.go.kr is blocked there by network policy — so the first real run
happens on a machine with normal internet access.

Start small and look at the result before pulling years:

    python scripts/fetch_transactions.py --regions 11110 --from 2024-01 --to 2024-03

Then widen:

    python scripts/fetch_transactions.py --all-seoul --from 2015-01 --to 2021-12

Output is one parquet per 시군구 in data/raw/, resumable: months already on disk
are skipped, so an interrupted pull can simply be re-run.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from policysim import molit, regions  # noqa: E402

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> int:
    args = _parse_args()
    codes = sorted(regions.SEOUL) if args.all_seoul else args.regions
    if not codes:
        print("지역을 지정하세요 (--regions 또는 --all-seoul)", file=sys.stderr)
        return 2

    months = pd.period_range(args.start, args.end, freq="M")
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"{len(codes)}개 지역 × {len(months)}개월 = {len(codes) * len(months)}회 요청")

    unmapped_seen: set[str] = set()
    for code in codes:
        path = RAW / f"{code}.parquet"
        existing = pd.read_parquet(path) if path.exists() else None
        have = set(existing["month"].astype(str)) if existing is not None else set()

        pending = [m for m in months if str(m) not in have]
        if not pending:
            print(f"  {regions.name_of(code)} ({code}): 이미 완료")
            continue

        frames = [existing] if existing is not None else []
        for month in pending:
            result = molit.fetch_month(code, str(month).replace("-", ""))
            unmapped_seen |= result.unmapped
            if not result.frame.empty:
                frames.append(result.frame)
            time.sleep(args.delay)  # data.go.kr throttles aggressive callers

        combined = pd.concat(frames, ignore_index=True).drop_duplicates()
        combined.to_parquet(path, index=False)
        print(f"  {regions.name_of(code)} ({code}): 누적 {len(combined):,}건 → {path.name}")

    if unmapped_seen:
        print(f"\n⚠️ 파서가 매핑하지 못한 응답 필드: {sorted(unmapped_seen)}")
        print("   API 스키마가 바뀌었을 수 있습니다. molit._FIELD_ALIASES를 확인하세요.")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="*", default=[], help="법정동코드 5자리")
    parser.add_argument("--all-seoul", action="store_true", help="서울 25개 구 전체")
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM")
    parser.add_argument("--to", dest="end", required=True, help="YYYY-MM")
    parser.add_argument("--delay", type=float, default=0.2, help="요청 간 대기 (초)")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
