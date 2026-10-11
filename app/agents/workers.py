"""에이전트 층: 리뷰어 세 명과 검증자를 각자 허용된 도구만으로 create_agent 해 둔다."""
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_tool_call

from app.core.config import WORKER_CALL_LIMIT, llm
from app.core.prompts import WORKER_PROMPTS

# 워커별 허용 도구. 검증자는 줄을 다시 읽기만 하면 되므로 읽기 도구 하나만 준다
ALLOWED_TOOLS = {
    "bug": ["read_file", "grep_code", "list_files", "get_unity_methods"],
    "perf": ["read_file", "grep_code", "list_files", "get_unity_methods"],
    "unity": ["read_file", "grep_code", "list_files", "get_unity_methods"],
    "verifier": ["read_file"],
}

WORKERS = {}                 # 워커 이름 -> 에이전트. main 에서 리뷰 루트로 도구를 만든 뒤 채운다
TOOL_CALLS = {}              # 도구 이름 -> 호출 수. status.json 에 남긴다


# [미들웨어] 도구 호출 수를 센다
# 이유: 리뷰어가 맥락 확인에 도구를 얼마나 썼는지가 비용과 ReAct 동작의 근거다. 호출 길목에서 세면 워커 코드를 고치지 않아도 된다
@wrap_tool_call
async def count_tool_calls(request, handler):
    """도구 이름별 호출 수를 TOOL_CALLS 에 더하고 도구를 그대로 실행한다."""
    name = request.tool_call["name"]
    TOOL_CALLS[name] = TOOL_CALLS.get(name, 0) + 1
    return await handler(request)


def create_workers(tools: list) -> None:
    """도구 전체에서 워커별 허용 도구만 골라 WORKERS 를 채운다(반환값 없음)."""
    by_name = {t.name: t for t in tools}
    for name, allowed in ALLOWED_TOOLS.items():
        WORKERS[name] = create_agent(
            llm,
            [by_name[n] for n in allowed],
            system_prompt=WORKER_PROMPTS[name],
            name=name,   # Langfuse 트레이스에 리뷰어 이름이 보인다
            middleware=[ModelCallLimitMiddleware(run_limit=WORKER_CALL_LIMIT, exit_behavior="end"),
                        count_tool_calls],
        )
