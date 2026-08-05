# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 현재 상태

`github.com/KANG-SURGERY/hello-world` 저장소입니다. 추적 파일은 `README.md`, `.gitignore`, `CLAUDE.md` 세 개뿐이고, 빌드 시스템·테스트·린터·의존성이 전혀 없습니다. 기본 브랜치는 `main`, 원격은 `origin` → `https://github.com/KANG-SURGERY/hello-world`.

작업 트리 경로는 클론 위치마다 다릅니다(사용자 Mac에서는 `PROJECTsenior`, 원격 세션에서는 `/home/user/hello-world` 등). 경로 이름에 의존하지 마세요.

## `rectal-cancer/` — 이 저장소가 아닙니다

사용자의 Mac 클론에는 이 작업 트리 안에 `rectal-cancer/` 디렉토리가 물리적으로 중첩돼 있습니다. 이것은 **hello-world의 일부가 아니라 별도의 독립 git 저장소**(`github.com/KANG-SURGERY/rectal-cancer`, Private)이며, 그래서 hello-world의 `.gitignore`가 `rectal-cancer/`를 제외합니다(임베디드 gitlink로 잘못 추적되는 것을 막기 위함).

> **먼저 확인하세요:** gitignore된 별도 저장소이므로 **hello-world를 새로 클론하면 따라오지 않습니다.** 웹·원격 세션처럼 fresh clone으로 시작한 환경에는 이 디렉토리가 존재하지 않습니다. 관련 작업을 지시받으면 `ls rectal-cancer`로 존재 여부를 먼저 확인하고, 없으면 별도 저장소를 클론해야 한다고 사용자에게 알리세요.

존재할 때의 성격 (Cookiecutter Data Science 관례를 따르는 직장암 환자 데이터 분석 Python 프로젝트):

- 데이터 흐름: `data/raw`(원본, 수정 금지) → `src/data` 전처리 → `data/interim`/`processed` → `src/analysis` → `results/`.
- **환자 데이터(PHI)는 절대 커밋 금지.** 그 저장소의 `.gitignore`가 `data/` 내용과 데이터 확장자(`*.csv`, `*.xlsx`, `*.dta`, `*.sav`, `*.dcm` 등)를 경로와 무관하게 무시하며, 폴더 구조는 `.gitkeep`으로만 추적됩니다. 새 데이터 형식을 도입하면 `.gitignore`에 먼저 추가하세요.
- 환경 설정은 `rectal-cancer/` 안에서: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (pandas·statsmodels·lifelines·scikit-learn 등).
- `rectal-cancer/` 안에서의 git 작업은 그 폴더의 `.git`(별도 저장소)에 적용됩니다 — hello-world가 아닙니다. 커밋·푸시 대상 저장소를 착각하지 마세요.

## Git

커밋 전에 작성자 ID를 확인하세요. 사용자의 Mac 클론은 저장소 로컬 설정으로 전역 ID(`Steve Kang`)를 덮어써 `user.name=Sung-Bum Kang`, `user.email=kangsb@snubh.org`로 커밋합니다. **새 클론에는 이 로컬 설정이 없으므로** 같은 ID로 커밋하려면 직접 설정해야 합니다:

```sh
git config user.name "Sung-Bum Kang" && git config user.email "kangsb@snubh.org"
```

## 사용자 환경 규칙

- 사용자는 한국어로 지시합니다. 사용자에게 보내는 텍스트·UI 문구는 한국어로, 코드 식별자·주석은 영어로 작성하세요.
- 사용자의 상위 `~/CLAUDE.md`는 홈 디렉토리를 "단일 HTML 파일 데모 작업 공간"으로 설명하지만, **그 패턴은 이 저장소에 적용되지 않습니다** — 여기는 GitHub에서 클론한 별도 git 저장소입니다.
- 로컬 셸은 zsh이며 헤드리스 테스트 환경이 없습니다.
