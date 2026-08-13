"""Session orchestration against the Anthropic API.

Round structure (see README):

    R1 독립 개진   parallel, blind
    R2 교차 반박   parallel, sees R1
    R3 협상        parallel, sees R1+R2
    사회자 종합    sequential
    레드팀 공격    sequential
    사회자 최종    sequential

Rounds 1-3 fan out because the whole point is that personas form their position
without adapting to each other mid-round; the barrier between rounds is what
makes a rebuttal a rebuttal. The closing three are inherently sequential.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import prompts
from personas import Persona


@dataclass
class Turn:
    speaker_id: str
    speaker_name: str
    round_name: str
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    error: str | None = None


@dataclass
class SessionResult:
    topic: str
    seats: list[Persona]
    rounds: dict[str, list[Turn]] = field(default_factory=dict)
    synthesis: Turn | None = None
    red_team: Turn | None = None
    closing: Turn | None = None

    def all_turns(self) -> list[Turn]:
        turns = [t for r in self.rounds.values() for t in r]
        turns += [t for t in (self.synthesis, self.red_team, self.closing) if t]
        return turns

    def usage(self) -> dict[str, int]:
        totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for t in self.all_turns():
            totals["input"] += t.input_tokens
            totals["output"] += t.output_tokens
            totals["cache_read"] += t.cache_read_tokens
            totals["cache_write"] += t.cache_write_tokens
        return totals

    def failures(self) -> list[Turn]:
        return [t for t in self.all_turns() if t.error]


def _transcript(turns: list[Turn], *, exclude: str | None = None) -> str:
    parts = []
    for t in turns:
        if t.error or (exclude and t.speaker_id == exclude):
            continue
        parts.append(f"### [{t.round_name}] {t.speaker_name} (`{t.speaker_id}`)\n\n{t.text}")
    return "\n\n---\n\n".join(parts)


class Council:
    def __init__(self, client, cfg: dict, shared: prompts.SharedContext, verbose=True):
        self.client = client
        self.cfg = cfg
        self.shared = shared
        self.verbose = verbose
        # Bound concurrency so a 12-seat roster doesn't trip org rate limits.
        self._gate = asyncio.Semaphore(int(cfg.get("max_concurrency", 5)))

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    async def _call(
        self,
        *,
        speaker_id: str,
        speaker_name: str,
        round_name: str,
        speaker_card: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str,
    ) -> Turn:
        """One model call. Streams because moderator turns are long enough to
        risk an HTTP timeout on a non-streaming request, and streaming costs
        nothing extra for the short ones."""
        turn = Turn(speaker_id, speaker_name, round_name, "")
        async with self._gate:
            try:
                async with self.client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=prompts.system_blocks(self.shared, speaker_card),
                    thinking={"type": "adaptive"},
                    output_config={"effort": effort},
                    messages=[{"role": "user", "content": user_prompt}],
                ) as stream:
                    message = await stream.get_final_message()
            except Exception as exc:  # network, rate limit after retries, 4xx
                turn.error = f"{type(exc).__name__}: {exc}"
                self._log(f"  ✗ {round_name} / {speaker_name} — {turn.error}")
                return turn

        if message.stop_reason == "refusal":
            turn.error = "모델이 응답을 거부했습니다 (stop_reason=refusal)"
            self._log(f"  ✗ {round_name} / {speaker_name} — 거부됨")
            return turn

        turn.text = "\n".join(b.text for b in message.content if b.type == "text").strip()
        u = message.usage
        turn.input_tokens = u.input_tokens or 0
        turn.output_tokens = u.output_tokens or 0
        turn.cache_read_tokens = getattr(u, "cache_read_input_tokens", 0) or 0
        turn.cache_write_tokens = getattr(u, "cache_creation_input_tokens", 0) or 0
        if not turn.text:
            turn.error = f"빈 응답 (stop_reason={message.stop_reason})"
        self._log(
            f"  ✓ {round_name} / {speaker_name} "
            f"(출력 {turn.output_tokens}토큰, 캐시읽기 {turn.cache_read_tokens})"
        )
        return turn

    async def _fan_out(self, seats: list[Persona], round_name: str, prompt_for) -> list[Turn]:
        self._log(f"\n▶ {round_name} — {len(seats)}명 동시 진행")
        tasks = [
            self._call(
                speaker_id=p.id,
                speaker_name=p.name,
                round_name=round_name,
                speaker_card=p.self_card(),
                user_prompt=prompt_for(p),
                model=self.cfg["models"]["persona"],
                max_tokens=int(self.cfg["max_tokens"]["persona"]),
                effort=self.cfg["effort"]["persona"],
            )
            for p in seats
        ]
        return list(await asyncio.gather(*tasks))

    async def run(self, seats: list[Persona], *, rounds: int = 3) -> SessionResult:
        result = SessionResult(topic=self.shared.topic, seats=seats)

        r1 = await self._fan_out(seats, "1라운드 독립 개진", lambda p: prompts.round1_opening(self.shared))
        result.rounds["1라운드 독립 개진"] = r1
        self._abort_if_dead(r1, "1라운드")

        t1 = _transcript(r1)
        r2 = await self._fan_out(
            seats,
            "2라운드 교차 반박",
            lambda p: prompts.round2_rebuttal(self.shared, t1, p.id),
        )
        result.rounds["2라운드 교차 반박"] = r2

        transcript = _transcript(r1 + r2)
        if rounds >= 3:
            r3 = await self._fan_out(
                seats,
                "3라운드 협상",
                lambda p: prompts.round3_bargain(self.shared, transcript),
            )
            result.rounds["3라운드 협상"] = r3
            transcript = _transcript(r1 + r2 + r3)

        observer_cards = "\n\n".join(p.observer_card() for p in seats)
        ledger_header = self.cfg["ledger_header"]

        self._log("\n▶ 사회자 종합")
        result.synthesis = await self._call(
            speaker_id="moderator",
            speaker_name="사회자",
            round_name="사회자 종합",
            speaker_card=self.cfg["_moderator_role"],
            user_prompt=prompts.moderator_prompt(
                self.shared, transcript, observer_cards, ledger_header
            ),
            model=self.cfg["models"]["moderator"],
            max_tokens=int(self.cfg["max_tokens"]["moderator"]),
            effort=self.cfg["effort"]["moderator"],
        )

        self._log("\n▶ 레드팀 공격")
        result.red_team = await self._call(
            speaker_id="red-team",
            speaker_name="레드팀",
            round_name="레드팀",
            speaker_card=self.cfg["_red_team_role"],
            user_prompt=prompts.red_team_prompt(
                self.shared, transcript, result.synthesis.text, observer_cards
            ),
            model=self.cfg["models"]["red_team"],
            max_tokens=int(self.cfg["max_tokens"]["red_team"]),
            effort=self.cfg["effort"]["red_team"],
        )

        self._log("\n▶ 사회자 최종 정리")
        result.closing = await self._call(
            speaker_id="moderator",
            speaker_name="사회자 (최종)",
            round_name="최종 정리",
            speaker_card=self.cfg["_moderator_role"],
            user_prompt=prompts.closing_prompt(
                result.synthesis.text, result.red_team.text, ledger_header
            ),
            model=self.cfg["models"]["moderator"],
            max_tokens=int(self.cfg["max_tokens"]["moderator"]),
            effort=self.cfg["effort"]["moderator"],
        )

        return result

    @staticmethod
    def _abort_if_dead(turns: list[Turn], label: str) -> None:
        """If round 1 produced nothing usable there is no transcript to rebut,
        and every later round would be garbage. Fail loudly instead."""
        alive = [t for t in turns if not t.error]
        if len(alive) < 3:
            errs = "\n  ".join(f"{t.speaker_name}: {t.error}" for t in turns if t.error)
            raise RuntimeError(
                f"{label}에서 유효한 발언이 {len(alive)}개뿐입니다 (최소 3개 필요).\n  {errs}"
            )
