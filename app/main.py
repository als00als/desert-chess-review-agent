"""실행 층: uv run -m app.main "<스크립트 폴더>" 로 코드 리뷰 팀을 실행하는 CLI."""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from langchain_core.messages import messages_to_dict

from app.agents.workers import create_workers
from app.core.config import EXCLUDE_DIRS, MAX_FILES, MAX_PARALLEL, OUTPUT_ROOT, REVIEWERS
from app.graph.builder import build_graph
from app.graph.nodes import USAGE
from app.tools.code_tools import build_tools


def langfuse_callbacks() -> list:
    """Langfuse 키가 있으면 CallbackHandler 하나를 담은 리스트를, 없으면 빈 리스트를 돌려준다."""
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return []
    try:
        from langfuse.langchain import CallbackHandler
        return [CallbackHandler()]
    except Exception as e:   # 추적은 선택 기능이다. 실패해도 리뷰는 계속한다
        print("Langfuse 비활성:", type(e).__name__, e)
        return []


async def main():
    """리뷰를 실행하고 산출물 폴더에 리포트와 대화 기록을 저장한다(반환값 없음)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Windows 콘솔에서 한글 경로·로그가 깨지지 않게
    parser = argparse.ArgumentParser(description="Unity C# 코드 리뷰 멀티에이전트")
    parser.add_argument("target", help="리뷰할 C# 스크립트 폴더 (공백·한글 경로는 따옴표로 감싼다)")
    parser.add_argument("--only", default=",".join(REVIEWERS), help="실행할 리뷰어 (예: bug,perf)")
    parser.add_argument("--files", default="**/*.cs", help='리뷰할 파일 glob, 루트 기준 (예: "00. Player/*.cs")')
    parser.add_argument("--max-files", type=int, default=MAX_FILES, help="리뷰할 파일 수 상한 (비용 제한)")
    parser.add_argument("--exclude", default=",".join(EXCLUDE_DIRS), help="제외할 폴더 이름 (쉼표 구분)")
    args = parser.parse_args()

    root = Path(args.target).resolve()
    if not root.is_dir():
        parser.error(f"폴더가 없습니다: {root}")
    reviewers = [r.strip() for r in args.only.split(",") if r.strip()]
    unknown = set(reviewers) - set(REVIEWERS)
    if unknown:
        parser.error(f"알 수 없는 리뷰어: {', '.join(sorted(unknown))} (가능: {', '.join(REVIEWERS)})")

    # 실행할 때마다 시각 이름의 산출물 폴더를 새로 만든다
    run_dir = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True)
    print("리뷰 대상:", root)
    print("산출물 폴더:", run_dir)

    # 도구는 리뷰 루트를 클로저로 감싸 만든다. 모델에게는 루트 기준 상대경로만 보인다
    create_workers(build_tools(root))

    state = {"root": str(root), "run_dir": f"output/{run_dir.name}", "reviewers": reviewers,
             "pattern": args.files, "max_files": args.max_files,
             "exclude": [d.strip() for d in args.exclude.split(",") if d.strip()], "started": time.time(),
             "files": [], "batches": [], "raw": {}, "verified": {}, "rejected": [], "errors": [],
             "final": [], "merged_count": 0, "messages": []}
    # recursion_limit 은 노드 실행 횟수의 상한이다. 리뷰어 수 × 배치 수 + 파일 수만큼 노드가 돌므로 넉넉히 준다
    config = {"recursion_limit": 500, "max_concurrency": MAX_PARALLEL, "run_name": "unity-code-review",
              "callbacks": [USAGE, *langfuse_callbacks()]}
    result = await build_graph().ainvoke(state, config)

    (run_dir / "messages.json").write_text(
        json.dumps(messages_to_dict(result["messages"]), ensure_ascii=False, indent=2), encoding="utf-8")
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    print("등급별:", status["by_severity"], "| 분류별:", status["by_category"])
    print("리포트:", run_dir / "review_report.md")
    if len(config["callbacks"]) > 1:
        from langfuse import get_client
        get_client().flush()   # 프로세스가 끝나기 전에 남은 트레이스를 보낸다


if __name__ == "__main__":
    asyncio.run(main())
