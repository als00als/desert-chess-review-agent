"""그래프 층: 노드를 등록하고 Send 분배·팬인 엣지를 잇는다."""
from langgraph.graph import END, START, StateGraph

from app.graph.edges import dispatch_reviews, dispatch_verify
from app.graph.nodes import aggregator, collect, plan_verify, reporter, reviewer, verifier
from app.graph.state import ReviewState


# [그래프 조립] 수집 → 리뷰어 병렬 → 팬인 → 검증 병렬 → 취합 → 리포트
def build_graph():
    """리뷰 파이프라인을 연결해 컴파일한 그래프를 돌려준다."""
    builder = StateGraph(ReviewState)
    builder.add_node("collect", collect)
    builder.add_node("reviewer", reviewer)
    builder.add_node("plan_verify", plan_verify)   # Send 팬인 지점: 리뷰가 모두 끝난 뒤 1번 실행
    builder.add_node("verifier", verifier)
    builder.add_node("aggregator", aggregator)
    builder.add_node("reporter", reporter)

    builder.add_edge(START, "collect")
    builder.add_conditional_edges("collect", dispatch_reviews, ["reviewer", "reporter"])
    # 일반 엣지 → 모든 reviewer 인스턴스가 끝나야 진행한다.
    # dispatch_verify 를 reviewer 의 조건 엣지로 달면 reviewer 인스턴스 수만큼 실행되므로 빈 노드에서 분기한다
    builder.add_edge("reviewer", "plan_verify")
    builder.add_conditional_edges("plan_verify", dispatch_verify, ["verifier", "aggregator"])
    builder.add_edge("verifier", "aggregator")
    builder.add_edge("aggregator", "reporter")
    builder.add_edge("reporter", END)
    return builder.compile()


if __name__ == "__main__":
    # uv run -m app.graph.builder → README 에 넣을 mermaid 그림
    print(build_graph().get_graph().draw_mermaid())
