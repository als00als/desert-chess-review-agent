# Desert Chess Code Reviewer — Unity C# 코드 리뷰 멀티에이전트

Unity 프로젝트의 C# 스크립트 폴더를 넣으면 **버그 · 성능 · Unity 안티패턴** 리뷰어 3명이 동시에 코드를 읽습니다. 이어서 **검증 에이전트**가 지적마다 실제 코드를 다시 읽어 오탐을 걸러 내고, **취합 에이전트**가 겹친 지적을 합쳐 우선순위별 리뷰 리포트를 씁니다.

```bash
uv run -m app.main "C:/Project_Game/Desert Chess/dessert chess/Desert-Chess/Assets/01. Script"
# → output/<실행 시각>/review_report.md, findings.json, status.json, messages.json
```

> AI Campus 과제 「나만의 에이전트 설계·구현」 B안 제출물. 2인 팀 게임 프로젝트 **데저트 체스**(Unity 6, URP 2D)의 실제 코드를 리뷰합니다.

---

## 1. 프로젝트 소개 — 무엇을 해결하는가

| 상황 | 문제 |
| --- | --- |
| 데저트 체스는 **2인 팀**이 기획과 개발을 함께 함 | 서로의 코드를 꼼꼼히 리뷰할 사람과 시간이 없음 |
| Unity는 **에러 없이 조용히 틀리는** 코드가 많음 | 자식 오브젝트에 `DontDestroyOnLoad` → 경고만 뜨고 무시됨 (**실제로 겪은 사례**). `Update`마다 `GetComponent`, 이벤트 구독 후 해제 누락, 파괴된 `UnityEngine.Object`에 `?.` 사용 등 |
| 일반 린터(Roslyn 분석기)는 **Unity 생명주기 맥락**을 모름 | "이 메서드는 매 프레임 호출된다", "이 싱글턴은 씬 재로드 시 중복된다" 같은 판단을 못 함 |
| LLM 한 번에 전체 코드를 넣으면 | 컨텍스트가 넘치고, 관점이 섞여 얕은 리뷰가 되며, **존재하지 않는 줄을 지적하는 환각**이 생김 |

→ **관점별 전문 리뷰어를 병렬로 돌리고, 지적마다 실제 코드로 다시 검증**하는 구조로 해결합니다.

## 2. Agent 구조

```mermaid
graph TD
    START([시작]) --> collect["① collect<br/>.cs 수집·Unity 메서드 추출<br/>(LLM 없음)"]
    collect -- "Send × (리뷰어 3 × 배치 N)" --> reviewer["②③④ reviewer<br/>bug / perf / unity<br/>ReAct + @tool"]
    collect -. "파일 없음" .-> reporter
    reviewer --> plan_verify["plan_verify<br/>(팬인: 모든 리뷰가 끝난 뒤 1번)"]
    plan_verify -- "Send × 파일" --> verifier["⑤ verifier<br/>GPT가 줄을 다시 읽고<br/>Jev 확률로 통과 판정"]
    plan_verify -. "지적 없음" .-> aggregator
    verifier --> aggregator["⑥ aggregator<br/>겹친 지적 병합·심각도 재조정"]
    aggregator --> reporter["⑦ reporter<br/>표·통계는 코드, 총평만 LLM"]
    reporter --> END([끝])
```

(`uv run -m app.graph.builder` 로 LangGraph가 그린 mermaid 원본을 출력할 수 있습니다.)

### 노드별 역할

| # | 노드 | LLM | 입력 → 출력 | 핵심 |
| --- | --- | --- | --- | --- |
| ① | `collect` | ✗ | 폴더 → `files`, `batches` | `*.cs`만, `Editor/` 등 제외. UTF-8 BOM·CRLF 처리. 클래스·상속·Unity 메시지 메서드(`Awake/Update/...`)와 줄 범위를 정규식으로 뽑아 리뷰어 힌트로 줌(매 프레임 호출은 `*`). 줄 수 600줄 기준으로 배치 |
| ② | `reviewer`(bug) | ✓ | 배치 → `raw` | NullReference, 초기화 순서, 이벤트 해제 누락, foreach 중 수정, 인덱스 경계, 상태 머신 |
| ③ | `reviewer`(perf) | ✓ | 배치 → `raw` | `Update` 안 `GetComponent`/`Find*`, 매 프레임 할당, 문자열 `Animator` 파라미터, `Instantiate/Destroy` 남발 |
| ④ | `reviewer`(unity) | ✓ | 배치 → `raw` | 자식 `DontDestroyOnLoad`, 싱글턴 중복, `UnityEngine.Object`에 `?.`/`??`, `CompareTag`, `Time.deltaTime` 누락 |
| ⑤ | `verifier` | ✓ + Jev | 파일별 지적 → `verified` / `rejected` | GPT 검증자가 `read_file`로 그 줄을 다시 읽고 존재·타당성을 판정, **Jev(TypeSafe)** 가 타당할 확률을 매겨 0.5 미만은 기각. 줄 번호 오류는 근거 코드로 다시 찾아 고침 |
| ⑥ | `aggregator` | ✓ | `verified` → `final` | 같은 파일에서 줄이 겹치는 지적을 코드로 묶고, 묶음만 LLM에 보내 같은 문제끼리 합침(예: perf·unity가 같은 `GetComponent` 지적). P0~P3 재조정, 정렬, `BUG-001` 같은 id는 코드가 붙임 |
| ⑦ | `reporter` | △ | `final` → 파일 | 표·건수·시간·토큰은 파이썬이 만들고 총평 3~5문장만 LLM. Jev로 리포트 실행 가능성 점수(0~3)를 `status.json`에 기록 |

### 리뷰어가 쓰는 도구 (`app/tools/code_tools.py`)

모든 도구는 **리뷰 루트 밖을 읽지 못하게** 경로를 검사하고, 모델에게는 루트 기준 상대경로만 보여 줍니다(한글·공백이 든 절대경로는 모델이 옮겨 적다 깨뜨리기 쉬움).

| 도구 | 하는 일 | 쓰는 담당 |
| --- | --- | --- |
| `read_file(path, start, end)` | 줄번호가 붙은 코드 (`   42│ code`), 최대 300줄 | 리뷰어 3명, 검증자 |
| `grep_code(pattern)` | 정규식으로 `파일:줄: 내용` 최대 50건 — 호출하는 곳·선언 위치 찾기 | 리뷰어 3명 |
| `list_files(subdir)` | `.cs` 상대경로 목록 | 리뷰어 3명 |
| `get_unity_methods(path)` | 클래스·상속, Unity 메시지 메서드와 줄 범위 | 리뷰어 3명 |

검증자는 **읽기 도구 하나만** 받습니다(starter의 `ALLOWED_TOOLS` 패턴).

### 배운 내용 적용 매핑

| 배운 것 | 적용 위치 |
| --- | --- |
| **LangGraph StateGraph + 리듀서** | `graph/state.py` — 병렬 결과를 `merge_by_key`(키별 dict 병합), `operator.add`(기각·오류 누적), `add_messages`(대화 기록)로 모음 |
| **병렬 실행 (`Send`) + 팬인** | `graph/edges.py` — 리뷰어 × 배치, 파일별 검증을 `Send`로 팬아웃. `reviewer → plan_verify` 일반 엣지로 모든 리뷰가 끝난 뒤 한 번만 분기 |
| **`create_agent` + 미들웨어** | `agents/workers.py` — `ModelCallLimitMiddleware`(에이전트 1회당 모델 호출 12번 상한), `wrap_tool_call`(도구 호출 수 집계 → `status.json`) |
| **`@tool` 도구 / ReAct** | `tools/code_tools.py` — 리뷰어·검증자가 필요할 때 다른 파일을 찾아 읽음 |
| **구조화 출력 (Pydantic)** | `core/schemas.py` — 에이전트의 텍스트 답 → `ReviewBatch`/`VerifyResult`/`MergeDecision`으로 변환. id·분류·통계는 코드가 정함 |
| **LLM-as-judge (Jev)** | `core/judge.py` — 지적 타당성 확률(`Noul`)로 검증 통과를 코드 가드가 결정, 리포트 품질 점수(`Score`) |
| **레이어드 구조** | `core → tools → agents → graph → main` (starter와 동일) |
| **관측 (Langfuse)** | `.env`에 키가 있으면 `CallbackHandler`를 실행 config에 붙여 리뷰어별 트레이스를 남김 |

## 3. 실행 방법

### 준비

1. **Python 3.12**, **[uv](https://docs.astral.sh/uv/)**
2. 의존성 설치: `uv sync`
3. `.env.example`을 `.env`로 복사하고 키를 채웁니다. (`.env`는 `.gitignore`에 있어 커밋되지 않습니다)

| 키 | 필수 | 용도 |
| --- | --- | --- |
| `OPENAI_API_KEY` | ✅ | 리뷰어·검증자·취합자·총평 |
| `OPENAI_CHAT_MODEL` | | 기본 `gpt-5.6-luna` (Responses API로 호출 — 이 모델은 Chat Completions로는 도구 호출이 막혀 있음) |
| `TYPESAFE_API_KEY` | ✅ | Jev 판정 |
| `TYPESAFE_MODEL` | | 기본 `jev-1.13.0` |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | 선택 | 실행 추적 |

### 실행

```bash
# 의도적 버그를 심은 테스트 파일
uv run -m app.main "fixtures/SeededBugs"

# 내 Unity 프로젝트 (공백·한글 경로는 따옴표로)
uv run -m app.main "D:/MyGame/Assets/Scripts"

# 옵션
uv run -m app.main "<폴더>" --only bug,perf          # 일부 리뷰어만
uv run -m app.main "<폴더>" --files "00. Player/*.cs" # 일부 파일만 (루트 기준 glob)
uv run -m app.main "<폴더>" --max-files 30           # 비용 제한
uv run -m app.main "<폴더>" --exclude "Editor,Plugins" # 제외 폴더

# fixtures 탐지율 계산 (가장 최근 실행 기준)
uv run python scripts/eval_fixtures.py
```

진행 로그는 노드 이름으로 시작합니다 (`collect:`, `reviewer:`, `plan_verify:`, `verifier:`, `aggregator:`, `reporter:`).

### 결과물 (`output/<실행 시각>/`)

| 파일 | 내용 |
| --- | --- |
| `review_report.md` | 요약 표 → 총평 → P0~P3 지적(위치·이유·수정 제안·근거 코드) → 파일별 표 → 기각된 지적과 사유 |
| `findings.json` | 최종 지적과 기각 목록 (기계용) |
| `status.json` | 건수, 소요 시간, 모델별 토큰, 도구 호출 수, 실패 기록, Jev 리포트 점수 |
| `messages.json` | 리뷰어·검증자 에이전트 대화 기록 (디버깅용) |

예시: [`output/sample/`](output/sample/) (fixtures 실행 결과)

## 4. 결과

RESULTS_PLACEHOLDER

## 5. 한계와 향후 계획

**한계**
- 정규식 기반 Unity 메서드 추출이라, 부분 클래스·매크로가 복잡한 코드에서는 힌트가 빠질 수 있습니다 (리뷰어는 코드 전체를 함께 받으므로 힌트는 보조 정보).
- 씬(.unity)·프리팹 YAML을 보지 않으므로, "인스펙터에서 할당되는가" 같은 판단은 코드만으로 합니다.
- LLM 출력이라 실행마다 지적 수가 조금씩 달라집니다. 검증자 + Jev 가드가 그 편차 중 오탐 쪽을 줄입니다.

**향후 계획**
- 씬·프리팹 YAML을 읽는 **Scene Reviewer** (컴포넌트 누락 참조, 레이어 설정)
- `git diff`만 리뷰하는 **PR 모드** + GitHub MCP로 PR 코멘트 등록
- 리포트를 보고 수정 패치를 제안하는 **Fixer 에이전트** (사람 승인 후 적용)
- Unity 베스트 프랙티스 문서 **RAG**

## 6. 폴더 구조

```
app/
├── core/      설정과 판단 기준
│   ├── config.py     경로, 모델, 배치·동시성·통과 기준 상수
│   ├── prompts.py    리뷰어 3명(관점별 체크리스트), 검증자, 취합자, 총평 프롬프트
│   ├── schemas.py    RawFinding, ReviewBatch, Verdict, VerifyResult, MergeDecision
│   └── judge.py      Jev 판정: 지적 타당 확률, 리포트 점수
├── tools/     에이전트에게 붙이는 도구 (LLM 없음)
│   ├── collector.py    C# 수집, Unity 메서드 추출, 배치, 줄번호 렌더링
│   └── code_tools.py   @tool read_file / grep_code / list_files / get_unity_methods
├── agents/
│   └── workers.py      리뷰어 3명 + 검증자 create_agent, 허용 도구 ALLOWED_TOOLS, 미들웨어
├── graph/     LangGraph 워크플로
│   ├── state.py        ReviewState, Send 입력, merge_by_key 리듀서
│   ├── nodes.py        collect, reviewer, plan_verify, verifier, aggregator, reporter
│   ├── edges.py        dispatch_reviews, dispatch_verify (Send)
│   ├── report.py       리포트 마크다운 생성 (코드)
│   └── builder.py      build_graph (+ mermaid 출력)
└── main.py    CLI: 인자 → 그래프 실행 → output/ 저장
fixtures/SeededBugs/   의도적 버그 C# 5개 + expected.json(정답지)
scripts/eval_fixtures.py  탐지율 계산
```
