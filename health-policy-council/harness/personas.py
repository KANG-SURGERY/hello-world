"""Persona loading and validation.

Single source of truth for the roster: `personas/*.yaml`. Both the Python harness
and the generated Claude Code subagents read these files, so a change here
propagates to both (regenerate subagents with `council.py agents`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REQUIRED_FIELDS = (
    "id",
    "name",
    "short",
    "bloc",
    "one_line",
    "mandate",
    "interests",
    "constraints",
    "red_lines",
    "tradeable",
    "evidence_base",
    "blind_spots",
    "rhetoric",
    "typical_claims",
    "disagrees_with",
    "default_seat",
)

LIST_FIELDS = (
    "interests",
    "constraints",
    "red_lines",
    "tradeable",
    "typical_claims",
    "blind_spots",
    "disagrees_with",
)

VALID_BLOCS = {"정부", "의료계", "수요자", "연구·중립", "정치"}

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class PersonaError(Exception):
    """Raised when a persona file fails validation."""


@dataclass
class Persona:
    id: str
    name: str
    short: str
    bloc: str
    one_line: str
    mandate: str
    interests: list[str]
    constraints: list[str]
    red_lines: list[str]
    tradeable: list[str]
    evidence_base: str
    blind_spots: list[str]
    rhetoric: str
    typical_claims: list[str]
    disagrees_with: list[str]
    default_seat: bool
    source_path: Path = field(repr=False, default=Path())

    # ---- prompt fragments -------------------------------------------------

    def self_card(self) -> str:
        """The persona's view of itself. Deliberately excludes `blind_spots`
        (ground-rules §5: a persona does not know its own blind spots)."""
        return "\n".join(
            [
                f"# 당신은 누구인가 — {self.name} ({self.short}, {self.bloc})",
                "",
                f"**세계관 한 줄:** {self.one_line.strip()}",
                "",
                f"**책임/대표성:** {self.mandate.strip()}",
                "",
                "**이 회의에서 얻어내려는 것**",
                _bullets(self.interests),
                "",
                "**당신을 묶고 있는 제약** (개인 의견과 무관하게 작동합니다)",
                _bullets(self.constraints),
                "",
                "**레드라인** — 합의문에 들어가면 서명을 거부하십시오",
                _bullets(self.red_lines),
                "",
                "**거래 가능한 카드** — 대가를 받으면 양보할 수 있는 것",
                _bullets(self.tradeable),
                "",
                f"**근거 기반:** {self.evidence_base.strip()}",
                "",
                f"**화법:** {self.rhetoric.strip()}",
                "",
                "**당신이 자주 하는 주장** (그대로 반복하지 말고, 이번 의제에 맞게 전개하십시오)",
                _bullets(self.typical_claims),
                "",
                "**구조적으로 충돌하는 상대:** " + ", ".join(self.disagrees_with),
            ]
        )

    def observer_card(self) -> str:
        """The moderator/red-team view — includes blind spots."""
        return "\n".join(
            [
                f"## {self.name} (`{self.id}`, {self.short}, {self.bloc})",
                f"- 한 줄: {self.one_line.strip()}",
                f"- 레드라인: {'; '.join(self.red_lines)}",
                f"- 거래 카드: {'; '.join(self.tradeable)}",
                "- **사각지대 (본인은 모름):**",
                _bullets(self.blind_spots, indent="  "),
            ]
        )


def _bullets(items: list[str], indent: str = "") -> str:
    return "\n".join(f"{indent}- {str(item).strip()}" for item in items)


def load_personas(personas_dir: Path) -> dict[str, Persona]:
    """Load and validate every `*.yaml` under `personas_dir`.

    Raises PersonaError listing *all* problems at once — fixing one file at a
    time through repeated runs is tedious when editing the roster.
    """
    problems: list[str] = []
    personas: dict[str, Persona] = {}

    paths = sorted(p for p in personas_dir.glob("*.yaml") if not p.name.startswith("_"))
    if not paths:
        raise PersonaError(f"페르소나 파일이 없습니다: {personas_dir}/*.yaml")

    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: YAML 파싱 실패 — {exc}")
            continue

        if not isinstance(raw, dict):
            problems.append(f"{path.name}: 최상위가 매핑이 아닙니다")
            continue

        missing = [f for f in REQUIRED_FIELDS if f not in raw]
        if missing:
            problems.append(f"{path.name}: 필수 필드 누락 — {', '.join(missing)}")
            continue

        pid = str(raw["id"])
        if pid != path.stem:
            problems.append(f"{path.name}: id('{pid}')와 파일명이 다릅니다")
        if not ID_RE.match(pid):
            problems.append(f"{path.name}: id는 소문자-하이픈 슬러그여야 합니다 — '{pid}'")
        if raw["bloc"] not in VALID_BLOCS:
            problems.append(
                f"{path.name}: bloc '{raw['bloc']}'는 허용값이 아닙니다 "
                f"({', '.join(sorted(VALID_BLOCS))})"
            )

        for f in LIST_FIELDS:
            if not isinstance(raw[f], list) or not raw[f]:
                problems.append(f"{path.name}: '{f}'는 비어 있지 않은 리스트여야 합니다")
        if len(raw.get("red_lines") or []) > 5:
            problems.append(
                f"{path.name}: red_lines가 {len(raw['red_lines'])}개입니다. "
                "5개를 넘으면 합의문이 성립하지 않습니다 (규격 §작성 원칙 3)"
            )

        if pid in personas:
            problems.append(f"{path.name}: id 중복 — '{pid}'")
            continue

        personas[pid] = Persona(
            id=pid,
            name=str(raw["name"]).strip(),
            short=str(raw["short"]).strip(),
            bloc=str(raw["bloc"]).strip(),
            one_line=str(raw["one_line"]),
            mandate=str(raw["mandate"]),
            interests=list(raw["interests"]),
            constraints=list(raw["constraints"]),
            red_lines=list(raw["red_lines"]),
            tradeable=list(raw["tradeable"]),
            evidence_base=str(raw["evidence_base"]),
            blind_spots=list(raw["blind_spots"]),
            rhetoric=str(raw["rhetoric"]),
            typical_claims=list(raw["typical_claims"]),
            disagrees_with=[str(x) for x in raw["disagrees_with"]],
            default_seat=bool(raw["default_seat"]),
            source_path=path,
        )

    # Cross-references can only be checked once every file is loaded.
    for persona in personas.values():
        for other in persona.disagrees_with:
            if other not in personas:
                problems.append(
                    f"{persona.source_path.name}: disagrees_with가 없는 id를 가리킵니다 — '{other}'"
                )
            elif other == persona.id:
                problems.append(f"{persona.source_path.name}: 자기 자신과 대립할 수 없습니다")

    if problems:
        raise PersonaError("페르소나 검증 실패:\n  - " + "\n  - ".join(problems))

    return personas


def resolve_seats(personas: dict[str, Persona], requested: list[str] | None) -> list[Persona]:
    """Pick the roster for one session.

    `requested` of `["all"]` seats everyone; otherwise the given ids; otherwise
    every persona with `default_seat: true`.
    """
    if requested == ["all"]:
        chosen = list(personas.values())
    elif requested:
        unknown = [r for r in requested if r not in personas]
        if unknown:
            raise PersonaError(
                f"알 수 없는 페르소나 id: {', '.join(unknown)}\n"
                f"사용 가능: {', '.join(sorted(personas))}"
            )
        chosen = [personas[r] for r in requested]
    else:
        chosen = [p for p in personas.values() if p.default_seat]

    if len(chosen) < 3:
        raise PersonaError(
            f"참석자가 {len(chosen)}명입니다. 3명 미만이면 교차 반박 라운드가 성립하지 않습니다."
        )
    # Stable, readable ordering: by bloc then id.
    bloc_order = {b: i for i, b in enumerate(["정부", "의료계", "수요자", "연구·중립", "정치"])}
    return sorted(chosen, key=lambda p: (bloc_order.get(p.bloc, 99), p.id))
