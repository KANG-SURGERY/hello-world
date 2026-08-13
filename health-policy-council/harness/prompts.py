"""Round-by-round prompt assembly.

Structure matters for cost as much as for quality: every call in a session
shares the same leading context block (ground rules + fact pack + the author's
column + the issue ledger). That block is marked with `cache_control` so the
second and later calls read it from cache at ~10% of the input price. Anything
that varies per persona or per round therefore has to come *after* it —
see `system_blocks()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from personas import Persona


@dataclass
class SharedContext:
    """Everything identical across all speakers in a session."""

    topic: str
    ground_rules: str
    facts: str
    author_position: str
    ledger: str

    def as_text(self) -> str:
        return "\n\n".join(
            [
                "# 회의 규칙",
                self.ground_rules.strip(),
                "---",
                "# 브리핑 팩 (공통 사실 기반)",
                self.facts.strip(),
                "---",
                "# 안건이 된 칼럼 (필자의 입장)",
                self.author_position.strip(),
                "---",
                "# 누적 쟁점 대장 (이전 회차까지의 기록)",
                self.ledger.strip(),
            ]
        )


PREAMBLE = (
    "당신은 한국 보건의료 정책을 다루는 원탁회의의 참석자입니다. "
    "이 회의의 목적은 합의를 만드는 것이 아니라, 의견이 갈리는 지점을 정확히 드러내고 "
    "무엇을 확인하면 그 불일치가 판정될 수 있는지 밝히는 것입니다.\n\n"
    "아래 규칙, 사실 팩, 안건 칼럼, 누적 쟁점 대장을 모두 읽고 시작하십시오. "
    "규칙은 예외 없이 적용됩니다 — 특히 증거 태그(§1)와 반대 할당량(§3)."
)


def system_blocks(shared: SharedContext, speaker_card: str) -> list[dict]:
    """System prompt as cache-friendly blocks.

    Block 0 is byte-identical for every call in the session and carries the
    cache breakpoint. Block 1 is the speaker's own card and varies, so it must
    come after — putting it first would make the shared context uncacheable.
    """
    return [
        {
            "type": "text",
            "text": PREAMBLE + "\n\n" + shared.as_text(),
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": speaker_card},
    ]


# --------------------------------------------------------------------------
# Round 1 — independent opening (parallel, blind to other speakers)
# --------------------------------------------------------------------------

def round1_opening(shared: SharedContext) -> str:
    return f"""오늘의 의제:

> {shared.topic}

이번은 **1라운드: 독립 개진**입니다. 다른 참석자의 발언을 아직 보지 못했고,
당신의 발언도 아직 아무도 보지 못했습니다. 눈치 보지 말고 당신의 이해관계에서
가장 정직한 입장을 내십시오.

다음 항목을 이 순서대로, 소제목을 붙여 작성하십시오. 전체 400~700자.

1. **입장** — 이 의제에 대한 당신의 결론 한 문단.
2. **근거** — 왜 그렇게 보는가. 증거 태그를 반드시 붙이십시오.
3. **전제** — 이 입장이 성립하려면 참이어야 하는 것. 여기서 정직하십시오.
   당신의 주장이 무너지는 조건을 스스로 밝히는 것이 이 회의의 자산입니다.
4. **레드라인** — 이 의제와 관련해 절대 수용 불가한 것.
5. **거래 카드** — 무엇을 받으면 무엇을 내줄 수 있는가. 구체적으로.

칼럼 필자에게 동조할 의무가 없습니다. 칭찬으로 시작하지 마십시오."""


# --------------------------------------------------------------------------
# Round 2 — cross-examination (parallel, sees all of round 1)
# --------------------------------------------------------------------------

def round2_rebuttal(shared: SharedContext, transcript: str, self_id: str) -> str:
    return f"""오늘의 의제: {shared.topic}

이번은 **2라운드: 교차 반박**입니다. 아래는 1라운드에서 나온 모든 발언입니다.
당신 자신(`{self_id}`)의 발언도 포함돼 있습니다.

<발언록>
{transcript}
</발언록>

규칙 §3에 따라 **최소 2건**, 다른 발언자의 **구체적 문장**을 지목해 반박하십시오.
각 반박은 다음 형식을 지키십시오 (항목당 150~300자):

**@<반박 대상 id>**
> 인용: "..." (상대 발언에서 그대로 옮길 것)
- 반박: 왜 틀렸는가
- 판정 조건: 이게 틀렸다면 무엇이 달라지는가 / 무엇을 확인하면 결판이 나는가

이어서 마지막에 한 항목을 더 쓰십시오:

**나에 대한 반박 중 가장 아픈 것**
누가 어떤 지적을 했고, 그중 인정할 부분과 인정하지 않을 부분을 나누십시오.
아무도 당신을 제대로 공격하지 않았다면 그렇게 쓰고, 당신 입장의 가장 약한 고리를
스스로 지목하십시오.

허수아비 때리기 금지(규칙 §6). 상대 입장을 상대가 부인할 요약으로 바꾸지 마십시오."""


# --------------------------------------------------------------------------
# Round 3 — bargaining (parallel, sees rounds 1 and 2)
# --------------------------------------------------------------------------

def round3_bargain(shared: SharedContext, transcript: str) -> str:
    return f"""오늘의 의제: {shared.topic}

이번은 **3라운드: 협상**입니다. 아래는 1~2라운드 전체 기록입니다.

<발언록>
{transcript}
</발언록>

여기서 묻는 것은 "무엇이 옳은가"가 아니라 **"무엇에 서명할 수 있는가"**입니다.
300~500자로 다음을 쓰십시오.

1. **내가 제안하는 패키지** — 이 방에서 실제로 3명 이상이 서명할 수 있다고 보는
   구체적 조합. 누가 무엇을 내주고 무엇을 받는지 명시하십시오.
   "협력 강화" 같은 문구는 패키지가 아닙니다.
2. **내가 서명 못 하는 것** — 2라운드에서 나온 제안 중 당신의 레드라인에 걸리는 것과
   어느 레드라인인지.
3. **내가 이번에 새로 양보하는 것** — 1라운드에서 밝힌 것보다 한 발 더 나간 양보와
   그 대가로 요구하는 것. 양보할 게 없으면 없다고 쓰고 이유를 대십시오.
4. **이 협상이 깨진다면 그 지점** — 당신이 보기에 가장 먼저 무너질 조항.

상대가 이걸 읽는다는 것을 전제로 쓰십시오. 실제 협상 문서처럼."""


# --------------------------------------------------------------------------
# Moderator and red team
# --------------------------------------------------------------------------

def moderator_prompt(
    shared: SharedContext, transcript: str, observer_cards: str, ledger_header: str
) -> str:
    return f"""오늘의 의제: {shared.topic}

아래는 이번 회차 전체 기록입니다.

<발언록>
{transcript}
</발언록>

아래는 각 참석자의 **사각지대** 정보입니다. 참석자 본인들은 이것을 모릅니다.
이번 회차 발언에서 **실제로 드러난** 사각지대만 지적하십시오.

<사각지대>
{observer_cards}
</사각지대>

당신의 역할 정의(`roles/moderator.md`)에 있는 9개 절을 순서대로, 형식 그대로 작성하십시오.

9절(쟁점 대장 갱신 지시)은 아래 헤더에 맞춰 붙여넣을 수 있는 표 행으로 출력하십시오:

{ledger_header}
"""


def red_team_prompt(
    shared: SharedContext, transcript: str, synthesis: str, observer_cards: str
) -> str:
    return f"""오늘의 의제: {shared.topic}

아래는 이번 회차 전체 기록과 사회자의 종합문입니다.

<발언록>
{transcript}
</발언록>

<사회자_종합>
{synthesis}
</사회자_종합>

<사각지대>
{observer_cards}
</사각지대>

당신의 역할 정의(`roles/red-team.md`)에 있는 7개 공격 순서를 모두 수행하고,
지정된 출력 형식으로 작성하십시오.

사회자 종합문 자체도 공격 대상입니다(7번). 봉합한 지점, 힘의 차이를 균등한 무게로
가린 지점, 판정 가능성을 낙관적으로 매긴 지점을 찾으십시오.

대안을 제시하지 마십시오. 살아남은 결론이 있으면 정직하게 인정하십시오."""


def closing_prompt(synthesis: str, red_team: str, ledger_header: str) -> str:
    return f"""당신은 이 회의의 사회자입니다. 아래는 당신이 작성한 종합문과,
그에 대한 레드팀의 공격입니다.

<나의_종합문>
{synthesis}
</나의_종합문>

<레드팀_공격>
{red_team}
</레드팀_공격>

레드팀의 공격을 반영해 종합문의 다음 세 부분만 **수정본**으로 다시 쓰십시오.
전체 종합문을 반복하지 마십시오.

## 수정: 성립 가능한 거래
레드팀 공격을 견디는 거래만 남기십시오. 전부 무너졌다면 그렇게 쓰고,
무엇이 추가돼야 성립하는지 밝히십시오.

## 수정: 필자 칼럼에 대한 가장 강한 반론
레드팀이 필자 칼럼을 공격한 내용을 반영해 다시 3개로 정리하십시오.

## 레드팀 공격에 대한 판정
레드팀의 각 공격에 대해 `수용` / `부분 수용` / `기각` 중 하나로 판정하고,
한 줄 이유를 대십시오. 기각할 때는 근거를 대십시오 — 레드팀도 틀릴 수 있습니다.

## 수정: 쟁점 대장 갱신 지시
아래 헤더에 맞춘 표 행으로 최종본을 출력하십시오.

{ledger_header}
"""
