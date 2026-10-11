"""그래프 층: 리뷰 파이프라인이 함께 쓰는 State, Send 입력, 병렬 결과를 모으는 리듀서."""
import operator
from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# [리듀서] 키 별로 모으는 dict 병합
def merge_by_key(current: dict, new: dict) -> dict:
    """키 기준으로 합친 새 딕셔너리를 돌려준다. 같은 키는 새 값으로 덮인다."""
    merged = dict(current)
    merged.update(new)
    return merged


# [State] 코드 리뷰 그래프의 공유 데이터
class ReviewState(TypedDict):
    # 처음 설정: 노드에서 바꾸지 않는 입력
    root: str                 # 리뷰 대상 절대경로 (모델에게는 보여 주지 않는다)
    run_dir: str              # 이번 실행의 산출물 폴더(프로젝트 기준 상대경로, 예: output/20261011_213000)
    reviewers: list[str]      # 실행할 리뷰어 ["bug", "perf", "unity"]
    pattern: str              # 리뷰할 파일 glob (루트 기준)
    max_files: int            # 리뷰할 파일 수 상한
    exclude: list[str]        # 제외할 폴더 이름
    started: float            # 시작 시각(time.time). 리포트의 소요 시간에 쓴다

    # collect: 수집 결과
    files: list[dict]         # [{path, lines, classes, unity_methods}]
    batches: list[dict]       # [{batch_id, files: [path, ...]}]

    # reviewer: 병렬 리뷰어가 같은 단계에 동시에 쓰므로 리듀서가 꼭 필요하다(없으면 InvalidUpdateError)
    raw: Annotated[dict[str, list], merge_by_key]        # {"unity:b03": [finding, ...]}
    # verifier: 파일 단위 병렬 검증 결과
    verified: Annotated[dict[str, list], merge_by_key]   # {"00. Player/PlayerController.cs": [finding, ...]}
    rejected: Annotated[list[dict], operator.add]        # [{finding, reason}]
    errors: Annotated[list[str], operator.add]           # 실패한 리뷰어·검증자 기록 (일부 실패해도 리포트는 쓴다)

    # aggregator: 병합·정렬한 최종 지적
    final: list[dict]
    merged_count: int         # 병합으로 줄어든 지적 수

    # 기록: messages.json 에 남길 에이전트 대화
    messages: Annotated[list, add_messages]


# Send 는 State 전체 대신 이 작은 입력만 넘긴다
class ReviewInput(TypedDict):
    """Send 로 reviewer 하나에 넘기는 입력."""
    reviewer: str
    batch: dict
    root: str


class VerifyInput(TypedDict):
    """Send 로 verifier 하나에 넘기는 입력. 파일 하나의 지적 묶음."""
    file: str
    findings: list[dict]
    root: str
