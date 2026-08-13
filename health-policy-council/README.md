# 한국 의료정책 원탁회의 (health-policy-council)

의료정책의 여러 이해관계자를 페르소나 에이전트로 세워 하나의 의제를 놓고 토론시키고,
**의견이 갈리는 지점과 그것을 판정할 방법**을 산출하는 시스템입니다.
합의문을 만드는 것이 목적이 아닙니다.

한겨레 「왜냐면」 칼럼(`context/author-position.md`)이 상설 안건으로 들어가 있고,
매 회차 사회자가 **그 칼럼에 대한 가장 강한 반론 3개**를 반드시 산출합니다.
이 시스템의 목적은 필자의 논지를 보강하는 것이 아니라 어디서 틀릴 수 있는지 찾는 것입니다.

---

## 왜 이렇게 복잡한가

LLM 페르소나를 여러 개 세우면 기본적으로 네 가지 방식으로 실패합니다.
이 시스템의 구조는 거의 전부 그 실패를 막기 위한 것입니다.

| 실패 방식 | 이 시스템의 장치 |
|---|---|
| 전부 비슷한 중립적 상식으로 수렴 | 페르소나마다 충돌하는 `interests`·`constraints`·`red_lines`. 1라운드는 서로 못 보는 상태에서 독립 진행 |
| 사용자(필자)에게 동조 | 규칙 §2가 동조 의무를 명시적으로 제거. 사회자는 매 회차 필자 반론 3개를 의무 산출 |
| 그럴듯한 헛소리 | 증거 태그 `[사실 F-##]`/`[추정]`/`[주장]`/`[미확인]` 강제. 태그 없는 사실 주장은 종합에서 폐기 |
| 회를 거듭해도 같은 말 반복 | `ledger/issue-ledger.md`가 매 회차 프롬프트에 들어가고, 규칙 §7이 반복을 금지 |

그리고 라운드가 진행될수록 서로의 언어에 적응해 **아무도 반대할 수 없는 결론**으로
수렴하는 경향이 있어서, 마지막에 그 수렴을 깨는 **레드팀**을 별도로 붙였습니다.
레드팀은 대안을 내지 않습니다 — 대안을 내는 순간 이해관계자가 되기 때문입니다.

---

## 회차 구조

```
0  브리핑      규칙 + 사실 팩 + 칼럼 + 누적 쟁점 대장  (모든 참석자 공통)
1  독립 개진   동시 · 서로 못 봄 — 입장/근거/전제/레드라인/거래카드
2  교차 반박   동시 · 1라운드 전체를 봄 — 최소 2건, 구체적 문장 지목
3  협상        동시 · 1~2라운드를 봄 — "무엇에 서명할 수 있는가"
4  사회자 종합  쟁점 지도 · 합의vs봉합 · 성립 가능한 거래 · 검증 필요 목록 · 필자 반론
5  레드팀      위 결론이 왜 작동하지 않는지 공격 (사회자 종합문 자체도 대상)
6  사회자 최종  레드팀 공격을 판정하고 거래·필자 반론·쟁점 대장을 수정
```

1~3라운드가 동시 진행인 것이 중요합니다. 순차로 돌리면 뒤에 말하는 사람이 앞사람에게
맞춰 버려서, 반박이 반박이 아니게 됩니다.

---

## 두 가지 실행 경로

### A. Claude Code 안에서 (API 키 불필요, 지금 바로 됨)

```
/council 필수의료 수가를 대폭 인상하면 그 돈이 실제로 필수의료 인력에 도달하는가
```

의제를 비우면 `topics/queue.md` 맨 위 항목을 씁니다.
`.claude/agents/council-*.md` 서브에이전트로 각 페르소나가 실행되고,
진행 규칙은 `.claude/skills/council/SKILL.md`에 있습니다.

### B. Python 하네스 (자동화·재현·비용 추적용)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r harness/requirements.txt

python3 harness/council.py validate          # 페르소나·설정 검증
python3 harness/council.py facts             # 브리핑 팩 검증 상태
python3 harness/council.py topics            # 의제 대기열

# 실제 실행 전에 프롬프트를 눈으로 확인 (API 호출 없음)
python3 harness/council.py run --topic "..." --dry-run

# 회차 실행 (ANTHROPIC_API_KEY 필요)
python3 harness/council.py run --topic "..."
python3 harness/council.py run --topic "..." --seats all        # 13인 확대 회의
python3 harness/council.py run --topic "..." --seats mohw-official,kma-practitioner,resident-young,patient-civic
```

두 경로는 **같은 `personas/*.yaml`을 읽습니다.** 페르소나를 고친 뒤에는
`python3 harness/council.py agents`로 서브에이전트를 재생성하세요.

---

## 지속적 루프

세 가지 방식이 있고, 셋 다 같은 하네스를 씁니다.

**1. GitHub Actions (권장 — 저장소만 있으면 됨)**
`.github/workflows/council-weekly.yml`. 매주 대기열 맨 위 의제로 회차를 돌리고 PR을 올립니다.
`ANTHROPIC_API_KEY` 시크릿 등록 후 `schedule` 블록의 주석을 푸세요.
지금은 수동 실행(workflow_dispatch)만 열려 있습니다 — 사실 팩 검증 전에 자동으로 돌리면
검증 안 된 숫자 위에서 회의가 쌓이기 때문입니다.

**2. Claude Code 예약 작업**
"매주 월요일 아침에 원탁회의 한 회차 돌려 줘"라고 요청하면 반복 트리거로 등록됩니다.

**3. 로컬 cron**
```cron
0 9 * * 1 cd ~/PROJECTsenior/health-policy-council && .venv/bin/python harness/council.py run --topic "$(grep -m1 '^- \[ \]' topics/queue.md | sed -E 's/^- \[ \] \*\*[A-Z0-9]+\.\*\* //')"
```

### 루프를 유지하는 데 사람이 해야 하는 일

자동화하지 않은 부분이 셋 있습니다. **셋 다 판단이 필요해서 일부러 남겨 뒀습니다.**

1. **쟁점 대장 갱신** — 회차 결과의 「쟁점 대장 갱신 지시」를 `ledger/issue-ledger.md`에
   반영. 이걸 빠뜨리면 루프가 매주 같은 회의를 반복합니다. 이 시스템에서 가장 중요한 한 가지.
2. **검증 필요 목록 처리** — `[미확인]`으로 나온 항목을 실제로 확인하고, 확인된 것은
   `context/briefing-facts.md`로 승격.
3. **의제 대기열 관리** — 다룬 의제는 완료로, 새 의제는 추가.

Claude Code에서는 "이번 회차 결과를 쟁점 대장에 반영해 줘" 한 줄로 1·3번이 처리됩니다.

---

## 파일 구조

```
health-policy-council/
├── personas/            13명의 이해관계자 정의 (+ _schema.md 작성 규격)
├── roles/               moderator.md · red-team.md — 참석자가 아닌 진행/공격 역할
├── context/
│   ├── ground-rules.md      증거 태그·반대 할당량 등 회의 규칙 ← 품질의 핵심
│   ├── briefing-facts.md    공통 사실 팩 (F-## 번호로 인용) ← 검증 필요
│   └── author-position.md   안건이 된 칼럼 ← 붙여넣어야 함
├── ledger/issue-ledger.md   누적 쟁점 = 이 시스템의 기억
├── topics/queue.md          의제 대기열
├── sessions/                회차별 산출물 (report.md · brief.md)
├── harness/                 Python 하네스
└── council.yaml             모델·effort·동시성 설정
```

---

## 먼저 해야 할 두 가지

1. **`context/author-position.md`에 칼럼 전문을 붙여넣으세요.**
   비어 있으면 사회자의 필자 반론과 레드팀의 우선 공격이 무력화됩니다.
2. **`context/briefing-facts.md`의 F-01~F-12를 원출처와 대조하세요.**
   이 팩은 모델의 사전 지식으로 초안을 잡은 것이라 숫자가 틀렸을 수 있고,
   틀린 숫자는 회의 전체를 오염시킵니다. `python3 harness/council.py facts`로 상태 확인.

---

## 비용

기본 9인 회의 = API 호출 30회. 공유 컨텍스트(규칙+사실팩+칼럼+대장, 약 8천 자)는
프롬프트 캐시로 재사용돼 두 번째 호출부터 입력 비용이 약 1/10로 떨어집니다.
`--dry-run`이 실행 전에 호출 수와 입력 크기를 알려주고, 회차 리포트 하단에
실제 토큰 사용량과 개략 비용이 기록됩니다.

싸게 돌리려면 `council.yaml`의 `models.persona`를 낮추십시오.
`models.moderator`와 `models.red_team`은 낮추지 마세요 — 회의 전체를 읽고 판정하는
자리라 여기서 산출물의 질이 결정됩니다.

---

## 한계 (알고 쓰십시오)

- **페르소나는 실제 이해관계자가 아닙니다.** 모델이 학습한 담론의 재구성이며,
  실제 복지부 공무원이나 전공의가 무슨 생각을 하는지의 증거가 아닙니다.
  이 회의의 산출물은 **가설과 질문**이지 사실이 아닙니다.
- **브리핑 팩을 검증하지 않으면 정교하게 틀린 회의가 나옵니다.** 형식이 그럴듯할수록
  틀린 숫자가 눈에 안 띕니다.
- **모델의 편향이 그대로 들어옵니다.** 한국 의료정책 담론에서 특정 입장이 온라인에
  더 많이 쓰였다면 그 입장이 더 유창하게 재현됩니다. 레드팀과 사각지대 장치가
  이를 완화하지만 제거하지는 못합니다.
- **이 시스템은 여론조사가 아닙니다.** 각 진영의 인원 비례나 실제 영향력을 반영하지 않습니다.
