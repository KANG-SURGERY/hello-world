"""Session output rendering.

Two artifacts per session:

  report.md     the full record — transcript, synthesis, red team, closing
  brief.md      the two-page version, which is what actually gets read

`brief.md` exists because the audience is a surgeon reading between cases.
A 20,000-character transcript nobody opens is a failed session.
"""

from __future__ import annotations

from datetime import date

from engine import SessionResult

# List price per million tokens, USD. Update alongside model choices in
# council.yaml — used only for the rough cost line in the report footer.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def estimate_cost(usage: dict[str, int], cfg: dict) -> float:
    """Rough single-model approximation: prices the whole session at the
    persona model's rate. Real spend differs because the moderator and red team
    run on a costlier model — treat this as an order of magnitude, not a bill."""
    model = cfg["models"]["persona"]
    inp, out = PRICES.get(model, (5.00, 25.00))
    billed_input = usage["input"] + usage["cache_write"] * 1.25 + usage["cache_read"] * 0.1
    return (billed_input * inp + usage["output"] * out) / 1_000_000


def render_report(result: SessionResult, cfg: dict, session_date: date) -> str:
    lines: list[str] = [
        f"# 원탁회의 회차 기록 — {session_date.isoformat()}",
        "",
        f"**의제:** {result.topic}",
        "",
        f"**참석:** {', '.join(f'{p.short}({p.id})' for p in result.seats)} "
        f"— 총 {len(result.seats)}명 + 사회자 + 레드팀",
        "",
    ]

    if result.failures():
        lines += [
            "> ⚠️ **일부 발언이 실패했습니다.** 아래 발언자는 이 기록에서 빠져 있습니다:",
            "",
        ]
        lines += [f"> - {t.round_name} / {t.speaker_name}: {t.error}" for t in result.failures()]
        lines.append("")

    # The synthesis is what the reader wants first; the transcript is evidence.
    if result.closing and not result.closing.error:
        lines += ["## 최종 정리 (레드팀 반영)", "", result.closing.text, "", "---", ""]
    if result.synthesis and not result.synthesis.error:
        lines += ["## 사회자 종합", "", result.synthesis.text, "", "---", ""]
    if result.red_team and not result.red_team.error:
        lines += ["## 레드팀 공격", "", result.red_team.text, "", "---", ""]

    lines += ["## 발언 전문", ""]
    for round_name, turns in result.rounds.items():
        lines += [f"### {round_name}", ""]
        for t in turns:
            if t.error:
                continue
            lines += [f"#### {t.speaker_name} (`{t.speaker_id}`)", "", t.text, ""]

    usage = result.usage()
    lines += [
        "---",
        "",
        "## 실행 정보",
        "",
        f"- 모델: 페르소나 `{cfg['models']['persona']}` / "
        f"사회자·레드팀 `{cfg['models']['moderator']}`",
        f"- 토큰: 입력 {usage['input']:,} / 출력 {usage['output']:,} / "
        f"캐시읽기 {usage['cache_read']:,} / 캐시쓰기 {usage['cache_write']:,}",
        f"- 개략 비용: 약 ${estimate_cost(usage, cfg):.2f} (정가 기준 근사치)",
        "",
        "> 이 기록의 모든 사실 주장에는 증거 태그가 붙어 있어야 합니다.",
        "> `[미확인]`·`[추정]` 항목은 사회자 종합의 「검증 필요 목록」에 모여 있습니다.",
        "> **그 목록을 확인하기 전까지 이 회의의 결론을 인용하지 마십시오.**",
    ]
    return "\n".join(lines)


def render_brief(result: SessionResult, session_date: date) -> str:
    """The read-in-five-minutes version: closing first, red team second, nothing else."""
    parts = [
        f"# 요약 브리프 — {session_date.isoformat()}",
        "",
        f"**의제:** {result.topic}",
        "",
        "> 전문은 같은 폴더의 `report.md`에 있습니다.",
        "",
        "---",
        "",
    ]
    if result.closing and not result.closing.error:
        parts += [result.closing.text, "", "---", ""]
    if result.red_team and not result.red_team.error:
        parts += ["## 레드팀이 남긴 공격", "", result.red_team.text, ""]
    return "\n".join(parts)
