# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 현재 상태

이 디렉토리(`PROJECTsenior`)는 `github.com/KANG-SURGERY/hello-world` 저장소의 클론이며, 추적 파일은 `README.md`(`# hello-world`)뿐입니다. 빌드 시스템은 없습니다.

> **중요:** 하위의 `rectal-cancer/`는 **이 저장소의 일부가 아니라 별도의 독립 git 저장소**(`github.com/KANG-SURGERY/rectal-cancer`, Private)입니다. 물리적으로만 이 작업 트리 안에 중첩돼 있어, hello-world의 `.gitignore`가 `rectal-cancer/`를 제외합니다. `rectal-cancer/` 안에서 git 작업을 하면 그 폴더의 `.git`(별도 저장소)에 적용됩니다.

## `rectal-cancer/` — 직장암 환자 데이터 분석 (Python, 별도 저장소)

직장암(rectal cancer) 환자 데이터 분석용 Python 프로젝트. 독립 저장소 `KANG-SURGERY/rectal-cancer`(Private)로 푸시돼 있습니다. (기존에 분리돼 있던 `cancer/`·`rectal/` 디렉토리를 이 하나로 통합함.) Cookiecutter Data Science 관례를 따릅니다.

```
rectal-cancer/
├── data/{raw,interim,processed}/   # 데이터 (raw=원본/수정금지 → interim → processed)
├── notebooks/                       # Jupyter 탐색적 분석
├── src/{data,features,analysis,visualization}/  # 재사용 분석 코드 (Python 패키지)
├── results/{figures,tables}/        # 분석 결과물 (재생성 가능)
├── docs/  references/               # 데이터 사전·분석계획 / 논문·프로토콜
├── requirements.txt                 # pandas·statsmodels·lifelines·scikit-learn 등
└── .gitignore
```

- **환자 데이터(PHI)는 절대 커밋 금지.** `.gitignore`가 `data/` 내용과 데이터 확장자(`*.csv`, `*.xlsx`, `*.dta`, `*.sav`, `*.dcm` 등)를 어디에 있든 무시합니다. 폴더 구조는 `.gitkeep`으로만 추적됩니다. 새 데이터 형식을 쓰면 `.gitignore`에 추가했는지 먼저 확인하세요.
- 환경 설정: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (`rectal-cancer/` 안에서).
- 데이터 흐름: `data/raw` → (`src/data` 전처리) → `data/interim`/`processed` → (`src/analysis`) → `results/`.
- 아직 테스트·린터는 설정돼 있지 않습니다. 추가되면 명령을 여기에 기록하세요.

## Git

- **저장소 전용 ID 재정의에 주의:** 이 저장소는 로컬 git 설정으로 작성자를 덮어씁니다 — `user.name=Sung-Bum Kang`, `user.email=kangsb@snubh.org` (전역 설정 `Steve Kang`과 다름). 커밋이 의도한 ID로 기록되는지 확인하세요.
- 기본 브랜치: `main`. 원격: `origin` → `https://github.com/KANG-SURGERY/hello-world.git`.

## 상위 CLAUDE.md와의 관계

상위 `~/CLAUDE.md`(`/Users/stevekang`)는 홈 디렉토리를 "단일 HTML 파일 데모 작업 공간"으로 설명합니다. **이 저장소에는 그 패턴이 적용되지 않습니다** — 여기는 GitHub에서 클론한 별도의 git 저장소이며 HTML 데모 규칙과 무관합니다. 다만 상위 파일의 일반 환경 규칙은 유효합니다:
- 사용자는 한국어로 지시합니다. 사용자에게 보내는 텍스트·UI 문구는 한국어로, 코드 식별자·주석은 영어로 작성하세요.
- 셸은 zsh이며 헤드리스 테스트 환경이 없습니다.
