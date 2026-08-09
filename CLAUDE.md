# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 현재 상태

`github.com/KANG-SURGERY/hello-world` 저장소. 추적 파일은 `README.md`, `.gitignore`, `CLAUDE.md` 셋뿐이며 **소스 코드·빌드 시스템·테스트·린터가 전혀 없습니다.** 빌드/실행/테스트 명령이 존재하지 않으므로 없는 명령을 추측해 실행하지 마세요. 처음 도구 설정을 추가할 때 그 명령을 이 문서에 기록하세요.

클론 디렉토리 이름은 환경마다 다릅니다(로컬 작업 트리에서는 `PROJECTsenior`, 원격 세션에서는 `hello-world` 등). 경로 이름에 의존하는 로직을 만들지 마세요.

## 환경에 따라 존재 여부가 달라지는 것들

아래 두 가지는 **사용자의 로컬 머신에만 있고, GitHub에서 새로 클론한 작업 트리(원격/웹 세션 포함)에는 없습니다.** 있다고 가정하지 말고 항상 먼저 확인하세요.

### 1. 중첩된 `rectal-cancer/` — 별도의 독립 저장소

`rectal-cancer/`는 **이 저장소의 일부가 아니라 물리적으로만 중첩된 독립 git 저장소**(`github.com/KANG-SURGERY/rectal-cancer`, Private)입니다. hello-world의 `.gitignore`가 이 경로를 제외하는 유일한 이유는 임베디드 저장소(gitlink)로 잘못 추적되는 것을 막기 위해서입니다.

- 그 폴더 안에서 git 명령을 실행하면 **그 폴더의 `.git`(다른 저장소)에 적용됩니다.** hello-world 브랜치·커밋과 뒤섞지 마세요.
- 내용: 직장암(rectal cancer) 환자 데이터 분석용 Python 프로젝트. Cookiecutter Data Science 관례 — `data/{raw,interim,processed}`, `notebooks/`, `src/{data,features,analysis,visualization}/`, `results/{figures,tables}/`, `docs/`, `references/`, `requirements.txt`(pandas·statsmodels·lifelines·scikit-learn 등).
- 데이터 흐름: `data/raw`(원본, 수정 금지) → `src/data` 전처리 → `data/interim`·`processed` → `src/analysis` → `results/`.
- 환경 설정은 그 폴더 안에서: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- **환자 데이터(PHI)는 절대 커밋 금지.** 그쪽 `.gitignore`가 `data/` 내용과 데이터 확장자(`*.csv`, `*.xlsx`, `*.dta`, `*.sav`, `*.dcm` 등)를 경로와 무관하게 무시하고, 폴더 구조는 `.gitkeep`으로만 추적합니다. 새로운 데이터 형식을 다루게 되면 커밋 전에 `.gitignore` 반영 여부를 먼저 확인하세요.

### 2. 저장소 전용 git ID 재정의

사용자의 로컬 클론에는 저장소 로컬 설정으로 작성자가 `Sung-Bum Kang <kangsb@snubh.org>`로 덮여 있습니다(전역 설정 `Steve Kang`과 다름). 이 설정은 **`.git/config`에 있어 저장소 내용으로 배포되지 않으므로** 새 클론에는 없습니다. 커밋 전에 `git config user.name`·`git config user.email`로 실제 값을 확인하고, 의도한 ID가 아니면 사용자에게 확인하세요.

## Git

- 기본 브랜치 `main`. 원격 `origin` → `https://github.com/KANG-SURGERY/hello-world`.

## 작업 규칙

- 사용자는 한국어로 지시합니다. **사용자에게 보내는 텍스트·문서·UI 문구는 한국어로**, 코드 식별자와 코드 주석은 영어로 작성하세요.
- 로컬 셸은 zsh이며 헤드리스 테스트 환경이 없습니다.
- 사용자 홈에 별도의 `~/CLAUDE.md`("단일 HTML 파일 데모 작업 공간")가 있을 수 있으나, **그 HTML 데모 규칙은 이 저장소에 적용되지 않습니다.** 여기는 GitHub에서 클론한 독립 git 저장소입니다.
