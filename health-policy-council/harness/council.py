#!/usr/bin/env python3
"""원탁회의 하네스 CLI.

  python3 harness/council.py validate                 페르소나·설정 검증
  python3 harness/council.py run --topic "..."        회차 실행
  python3 harness/council.py run --topic "..." --dry-run   API 호출 없이 프롬프트만 생성
  python3 harness/council.py agents                   Claude Code 서브에이전트 재생성
  python3 harness/council.py facts                    브리핑 팩 검증 상태
  python3 harness/council.py topics                   의제 대기열

`run`은 ANTHROPIC_API_KEY(또는 `ant auth login` 프로필)를 필요로 합니다.
`--dry-run`을 포함한 나머지 명령은 API 키 없이 동작합니다.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prompts  # noqa: E402
import render  # noqa: E402
from engine import Council  # noqa: E402
from personas import Persona, PersonaError, load_personas, resolve_seats  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
PERSONAS_DIR = ROOT / "personas"
CONTEXT_DIR = ROOT / "context"
ROLES_DIR = ROOT / "roles"
SESSIONS_DIR = ROOT / "sessions"
LEDGER = ROOT / "ledger" / "issue-ledger.md"
CONFIG = ROOT / "council.yaml"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cfg["_moderator_role"] = (ROLES_DIR / "moderator.md").read_text(encoding="utf-8")
    cfg["_red_team_role"] = (ROLES_DIR / "red-team.md").read_text(encoding="utf-8")
    return cfg


def author_position_text(cfg: dict) -> str:
    raw = (CONTEXT_DIR / "author-position.md").read_text(encoding="utf-8")
    if cfg.get("author_position") == "summary":
        m = re.search(r"^## 요약.*?$(.*?)^---", raw, re.S | re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
        print("  ! author_position: summary 인데 「요약」 절이 비어 있어 전문을 사용합니다.")
    return raw


def author_position_is_empty() -> bool:
    raw = (CONTEXT_DIR / "author-position.md").read_text(encoding="utf-8")
    return "(비어 있음)" in raw


def build_shared(topic: str, cfg: dict) -> prompts.SharedContext:
    return prompts.SharedContext(
        topic=topic,
        ground_rules=(CONTEXT_DIR / "ground-rules.md").read_text(encoding="utf-8"),
        facts=(CONTEXT_DIR / "briefing-facts.md").read_text(encoding="utf-8"),
        author_position=author_position_text(cfg),
        ledger=LEDGER.read_text(encoding="utf-8"),
    )


def slugify(topic: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", topic).strip("-")
    return (s[:40] or "session").lower()


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_validate(_args) -> int:
    personas = load_personas(PERSONAS_DIR)
    cfg = load_config()

    print(f"✓ 페르소나 {len(personas)}명 검증 통과")
    by_bloc: dict[str, list[str]] = {}
    for p in personas.values():
        by_bloc.setdefault(p.bloc, []).append(f"{p.short}{'*' if p.default_seat else ''}")
    for bloc, names in by_bloc.items():
        print(f"    {bloc}: {', '.join(names)}")
    print("    (* = 기본 회의 참석)")

    seats = resolve_seats(personas, None)
    print(f"✓ 기본 회의 참석자 {len(seats)}명")

    # A roster where nobody structurally opposes anybody produces a polite,
    # useless session — worth catching before spending money on it.
    seat_ids = {p.id for p in seats}
    isolated = [p.short for p in seats if not (set(p.disagrees_with) & seat_ids)]
    if isolated:
        print(f"  ! 기본 참석자 중 대립 상대가 없는 페르소나: {', '.join(isolated)}")
        print("    (이 사람은 반박 라운드에서 겉돌 가능성이 큽니다)")

    header = cfg["ledger_header"].strip().splitlines()[0].strip()
    if header not in LEDGER.read_text(encoding="utf-8"):
        print("  ! council.yaml의 ledger_header가 ledger/issue-ledger.md의 표 헤더와 다릅니다")
    else:
        print("✓ 쟁점 대장 헤더 일치")

    if author_position_is_empty():
        print("  ! context/author-position.md가 비어 있습니다 — 칼럼 전문을 붙여넣으세요.")
        print("    (사회자의 '필자 칼럼 반론' 절과 레드팀 우선 공격이 무력화됩니다)")
    else:
        print("✓ 필자 칼럼 있음")

    print(f"✓ 모델: 페르소나 {cfg['models']['persona']} / 사회자 {cfg['models']['moderator']}")
    return 0


def cmd_facts(_args) -> int:
    text = (CONTEXT_DIR / "briefing-facts.md").read_text(encoding="utf-8")
    unchecked = text.count("| ☐ |")
    checked = text.count("| ☑ |")
    total = unchecked + checked
    print(f"브리핑 팩: {total}개 항목 중 {checked}개 확인됨, {unchecked}개 미확인")
    if unchecked:
        print("\n미확인 항목:")
        for line in text.splitlines():
            if line.strip().endswith("| ☐ |"):
                cells = [c.strip() for c in line.split("|")]
                if len(cells) > 3:
                    print(f"  {cells[1]}  {cells[2]}")
        print("\n숫자가 틀리면 회의 전체가 오염됩니다. 최소 F-01~F-12는 원출처와 대조하세요.")
    return 0


def cmd_topics(_args) -> int:
    print((ROOT / "topics" / "queue.md").read_text(encoding="utf-8"))
    return 0


def cmd_agents(_args) -> int:
    """Generate Claude Code subagent files from the persona YAML.

    Keeps the two execution paths (Python harness / Claude Code) reading the
    same roster instead of drifting apart.
    """
    personas = load_personas(PERSONAS_DIR)
    out_dir = REPO_ROOT / ".claude" / "agents"
    out_dir.mkdir(parents=True, exist_ok=True)

    rel = "health-policy-council"
    written = 0
    for p in personas.values():
        body = "\n".join(
            [
                "---",
                f"name: council-{p.id}",
                f"description: >-",
                f"  한국 의료정책 원탁회의 참석자 — {p.name}. "
                f"{p.one_line.strip().replace(chr(10), ' ')} "
                f"/council 회의에서 이 입장을 대변할 때 사용합니다.",
                "tools: Read, Grep, Glob",
                "---",
                "",
                p.self_card(),
                "",
                "---",
                "",
                "## 발언 전 반드시 읽을 것",
                "",
                f"- `{rel}/context/ground-rules.md` — 증거 태그·반대 할당량 등 회의 규칙",
                f"- `{rel}/context/briefing-facts.md` — 인용 가능한 사실 목록",
                f"- `{rel}/context/author-position.md` — 안건이 된 칼럼",
                f"- `{rel}/ledger/issue-ledger.md` — 이미 다뤄진 쟁점 (반복 금지)",
                "",
                "규칙은 예외 없이 적용됩니다. 특히:",
                "",
                "- 모든 사실 주장에 `[사실 F-##]` / `[추정]` / `[주장]` / `[미확인]` 태그",
                "- 필자 칼럼에 동조할 의무 없음. 칭찬으로 시작하지 말 것",
                "- 반박 라운드에서는 최소 2건, 다른 발언자의 구체적 문장을 지목",
                "- 자신의 사각지대는 스스로 언급하지 않음 (사회자·레드팀의 역할)",
                "",
                "발언은 한국어로, 지정된 분량 안에서.",
            ]
        )
        (out_dir / f"council-{p.id}.md").write_text(body + "\n", encoding="utf-8")
        written += 1

    print(f"✓ {written}개 서브에이전트를 {out_dir.relative_to(REPO_ROOT)}/ 에 생성했습니다")
    print("  Claude Code에서 `/council <의제>` 로 회의를 열 수 있습니다.")
    return 0


def _dry_run(topic: str, seats: list[Persona], shared, cfg, out_dir: Path) -> int:
    """Build every prompt without calling the API. Verifies wiring, lets the
    user read exactly what each persona will be asked, and sizes the session."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shared_text = prompts.PREAMBLE + "\n\n" + shared.as_text()
    (out_dir / "00-shared-context.md").write_text(shared_text, encoding="utf-8")

    total_chars = 0
    for p in seats:
        card = p.self_card()
        r1 = prompts.round1_opening(shared)
        (out_dir / f"r1-{p.id}.md").write_text(
            f"<!-- system block 2 (persona card) -->\n{card}\n\n"
            f"<!-- user message -->\n{r1}",
            encoding="utf-8",
        )
        total_chars += len(shared_text) + len(card) + len(r1)

    observer = "\n\n".join(p.observer_card() for p in seats)
    (out_dir / "moderator-cards.md").write_text(observer, encoding="utf-8")

    calls = len(seats) * 3 + 3
    print(f"\n✓ 드라이런 완료 — 프롬프트를 {out_dir} 에 기록했습니다")
    print(f"  참석자 {len(seats)}명 → 실제 실행 시 API 호출 {calls}회")
    print(f"  공유 컨텍스트 {len(shared_text):,}자 (캐시 대상, 첫 호출 이후 ~10% 가격)")
    print(f"  1라운드 입력 총량 대략 {total_chars:,}자")
    print("\n  프롬프트를 읽어보고 이상이 없으면 --dry-run 없이 다시 실행하세요.")
    return 0


def cmd_run(args) -> int:
    cfg = load_config()
    personas = load_personas(PERSONAS_DIR)
    seats = resolve_seats(personas, args.seats.split(",") if args.seats else None)
    shared = build_shared(args.topic, cfg)

    session_date = date.today()
    out_dir = SESSIONS_DIR / f"{session_date.isoformat()}-{slugify(args.topic)}"

    if author_position_is_empty():
        print("  ! 경고: context/author-position.md가 비어 있습니다.")
        print("    필자 칼럼 반론과 레드팀의 우선 공격 대상이 없는 채로 진행합니다.\n")

    if args.dry_run:
        return _dry_run(args.topic, seats, shared, cfg, out_dir / "dry-run")

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        print("anthropic SDK가 없습니다: pip install -r harness/requirements.txt", file=sys.stderr)
        return 1

    print(f"의제: {args.topic}")
    print(f"참석: {', '.join(p.short for p in seats)} ({len(seats)}명)")

    async def go():
        # max_retries above the default 2 because a 30-call session has more
        # chances to hit a transient 429 than a single request does.
        async with AsyncAnthropic(max_retries=4, timeout=600.0) as client:
            council = Council(client, cfg, shared)
            return await council.run(seats, rounds=args.rounds)

    try:
        result = asyncio.run(go())
    except RuntimeError as exc:
        print(f"\n✗ 회의 중단: {exc}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render.render_report(result, cfg, session_date), encoding="utf-8")
    (out_dir / "brief.md").write_text(render.render_brief(result, session_date), encoding="utf-8")

    usage = result.usage()
    print(f"\n✓ 회차 완료 → {out_dir}")
    print(f"  brief.md   먼저 읽을 것 (요약)")
    print(f"  report.md  전문")
    print(
        f"  토큰: 입력 {usage['input']:,} / 출력 {usage['output']:,} / "
        f"캐시읽기 {usage['cache_read']:,}"
    )
    print(f"  개략 비용: 약 ${render.estimate_cost(usage, cfg):.2f}")
    if result.failures():
        print(f"  ! 실패한 발언 {len(result.failures())}건 (report.md 상단 참조)")
    print("\n  다음 할 일: 최종 정리의 「쟁점 대장 갱신 지시」를")
    print("  ledger/issue-ledger.md에 반영하세요. 반영하지 않으면 다음 회차가 같은 말을 반복합니다.")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="council", description="한국 의료정책 원탁회의 하네스"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="페르소나·설정 검증").set_defaults(func=cmd_validate)
    sub.add_parser("facts", help="브리핑 팩 검증 상태").set_defaults(func=cmd_facts)
    sub.add_parser("topics", help="의제 대기열 출력").set_defaults(func=cmd_topics)
    sub.add_parser("agents", help="Claude Code 서브에이전트 재생성").set_defaults(func=cmd_agents)

    run = sub.add_parser("run", help="회차 실행")
    run.add_argument("--topic", required=True, help="이번 회차 의제")
    run.add_argument("--seats", help="쉼표로 구분한 페르소나 id, 또는 'all'")
    run.add_argument("--rounds", type=int, default=3, choices=[2, 3], help="토론 라운드 수")
    run.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 생성")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    try:
        return args.func(args)
    except PersonaError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"\n✗ 파일을 찾을 수 없습니다: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
