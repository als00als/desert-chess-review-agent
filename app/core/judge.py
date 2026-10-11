"""판단 층: Jev 에게 묻는 질문(지적이 타당한지, 리포트 점수)과 호출 함수.

검증자 에이전트(GPT)는 코드를 다시 읽고 소견을 쓰고, Jev 는 그 지적이 타당할 확률만 돌려준다.
통과시킬지는 그 확률을 보고 코드(PASS_PROB 가드)가 정한다.
"""
import warnings

from langchain_typesafe import Noul, Score, TypeSafeClassifier

from app.core.config import JEV_MODEL

warnings.filterwarnings("ignore", message=".*TypeSafeClassifier.*beta")   # 베타 안내 경고만 끈다
# Jev 분류기. 질문(Noul 확률, Score 점수)과 상태를 주면 판정 결과를 돌려준다
jev = TypeSafeClassifier(model=JEV_MODEL)

# 지적 타당성 질문: 조건을 번호로 적어 두어야 그럴듯한 일반론에 예라고 하지 않는다
FINDING_QUESTION = {
    "valid": Noul(
        instructions=(
            "code 의 해당 줄에 finding 이 말하는 문제가 실제로 있나요? 다음이 모두 맞을 때만 예다. "
            "1) evidence 의 코드가 code 에 실제로 있다. "
            "2) reason 이 Unity/C# 동작에 비추어 사실이다. "
            "3) 매 프레임 호출 같은 전제가 있으면 code 에서 그 전제가 확인된다. "
            "4) 단순 취향이 아니라 버그·성능·유지보수에 실제 영향이 있다."
        ),
    ),
}
# Score: criteria 네 문장 중 리포트에 맞는 것으로 0~3점을 매긴다(첫 문장이 0점)
REPORT_QUESTIONS = {
    "actionability": Score(
        instructions="지적마다 위치, 이유, 바로 적용할 수 있는 수정안이 있는가?",
        criteria=[
            "대부분 일반론이다.",
            "일부만 구체적이다.",
            "대부분 구체적이다.",
            "모두 위치·이유·수정안이 구체적이다.",
        ],
    ),
}


# [보조 함수] Jev 판정: judge_finding 은 검증 노드가, judge_report 는 리포트 노드가 쓴다
async def judge_finding(code: str, finding: dict, note: str) -> float:
    """지적 하나가 실제 코드에 비추어 타당할 확률(0~1)을 돌려준다."""
    state = {"code": code, "finding": finding, "verifier_note": note}
    result = await jev.ainvoke({"state": state, "questions": FINDING_QUESTION})
    return result.nouls["valid"].noul


async def judge_report(report: str) -> int:
    """리포트의 실행 가능성 점수(0~3)를 돌려준다."""
    result = await jev.ainvoke({"state": {"report": report}, "questions": REPORT_QUESTIONS})
    return result.scores["actionability"].score
