"""그래프 층: 노드 사이의 갈 곳을 정하는 라우팅 함수. 여기서는 Send 로 병렬 분배한다."""
from langgraph.types import Send

from app.graph.state import ReviewState


# [라우팅 함수] 리뷰어 × 배치마다 reviewer 로 Send 만들기
def dispatch_reviews(state: ReviewState) -> list[Send] | str:
    """리뷰어 × 배치마다 reviewer 로 보내는 Send 목록을, 배치가 없으면 "reporter" 를 돌려준다."""
    # 빈 리스트를 돌려주면 그래프가 조용히 끝난다. 리뷰할 파일이 없어도 리포트는 남긴다
    if not state["batches"]:
        return "reporter"
    return [Send("reviewer", {"reviewer": r, "batch": b, "root": state["root"]})
            for r in state["reviewers"] for b in state["batches"]]


# [라우팅 함수] 파일마다 verifier 로 Send 만들기
def dispatch_verify(state: ReviewState) -> list[Send] | str:
    """지적을 파일별로 묶어 verifier 로 보내는 Send 목록을, 지적이 없으면 "aggregator" 를 돌려준다."""
    groups = {}
    for items in state["raw"].values():
        for f in items:
            groups.setdefault(f["file"], []).append(f)
    if not groups:
        return "aggregator"
    return [Send("verifier", {"file": k, "findings": v, "root": state["root"]}) for k, v in sorted(groups.items())]
