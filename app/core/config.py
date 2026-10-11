"""설정 층: 경로, 모델, 배치·동시성 상한을 모으고 프로젝트 폴더의 .env 만 읽는다."""
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 경로: app/core/config.py 에서 두 단계 위가 프로젝트 폴더다. 산출물과 fixtures 는 모두 이 폴더 기준이다
PROJECT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_DIR / "output"
FIXTURES_DIR = PROJECT_DIR / "fixtures" / "SeededBugs"

# 프로젝트 폴더의 .env 만 읽는다. 다른 폴더의 .env 가 섞여 들어오지 않게 경로를 직접 준다
load_dotenv(PROJECT_DIR / ".env")

# 모델 이름: .env 에 값이 없으면 기본값을 쓴다
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
JEV_MODEL = os.getenv("TYPESAFE_MODEL", "jev-1.13.0")

REVIEWERS = ("bug", "perf", "unity")   # 리뷰어 종류. --only 로 일부만 고를 수 있다
BATCH_LINES = 600          # 리뷰어 1회 호출에 넣을 코드 줄 수 상한
MAX_FILES = 60             # 비용 상한 (--max-files 로 덮어쓴다)
MAX_PARALLEL = 4           # graph.ainvoke config 의 max_concurrency. API 속도 제한 대비
PASS_PROB = 0.5            # Jev 가 지적이 타당하다고 본 확률이 이 값 이상이면 통과
WORKER_CALL_LIMIT = 12     # 에이전트 한 번 실행당 모델 호출 상한
EXCLUDE_DIRS = ("Editor", "Plugins", "ThirdParty", "SPUM", "TextMesh Pro")   # 리뷰하지 않는 폴더 이름

# 리뷰어·검증자·취합자가 함께 쓰는 모델
# 이 모델은 Chat Completions 로는 도구 호출이 막혀 있어 Responses API 로 부른다
llm = ChatOpenAI(model=CHAT_MODEL, use_responses_api=True, timeout=180)
