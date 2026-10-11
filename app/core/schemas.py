"""스키마 층: 리뷰어·검증자·취합자가 GPT 구조화 출력으로 받는 모양을 정한다."""
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["P0", "P1", "P2", "P3"]


# 리뷰어 출력: 지적 하나. id 와 category 는 모델에 맡기지 않고 코드가 붙인다
class RawFinding(BaseModel):
    """리뷰어가 낸 지적 하나."""
    file: str = Field(description="리뷰 루트 기준 상대경로. 입력 코드 머리줄에 적힌 경로를 그대로 옮긴다")
    line_start: int = Field(description="문제가 시작되는 줄 번호. 입력 코드 왼쪽에 붙은 번호 그대로")
    line_end: int = Field(description="문제가 끝나는 줄 번호. 한 줄이면 line_start 와 같다")
    severity: Severity = Field(description="P0 크래시·진행 불가, P1 잘못된 동작이 실제 발생, P2 성능 저하·잠재 버그, P3 유지보수·스타일")
    title: str = Field(description="한 줄 요약")
    evidence: str = Field(description="해당 줄 코드를 그대로 옮긴 발췌. 줄 번호는 빼고 10줄 이내")
    reason: str = Field(description="왜 문제인지. Unity/C# 동작 근거")
    suggestion: str = Field(description="수정 방법. 가능하면 짧은 코드 예시")


class ReviewBatch(BaseModel):
    """리뷰어 한 명이 배치 하나를 읽고 낸 지적 목록."""
    findings: list[RawFinding] = Field(description="지적 목록. 확실한 것만. 없으면 빈 리스트")


# 검증자 출력: 지적 하나에 대한 판정
class Verdict(BaseModel):
    """검증자가 실제 코드를 다시 읽고 내린 판정."""
    index: int = Field(description="입력 지적 목록의 번호(0부터)")
    exists: bool = Field(description="evidence 의 코드가 실제 파일에 있는가")
    valid: bool = Field(description="reason 의 주장이 Unity/C# 동작에 비추어 맞는가")
    line_start: int = Field(description="실제 위치의 시작 줄. 틀렸으면 고친 번호, 맞으면 원래 번호")
    line_end: int = Field(description="실제 위치의 끝 줄")
    note: str = Field(description="판정 근거 한두 문장. 기각이면 사유")


class VerifyResult(BaseModel):
    """검증자가 파일 하나의 지적 묶음에 대해 낸 판정 목록."""
    verdicts: list[Verdict] = Field(description="입력 지적마다 하나씩, 같은 순서로")


# 취합자 출력: 후보 묶음을 같은 문제끼리 나눈 결과
class MergedIssue(BaseModel):
    """같은 원인의 같은 문제로 본 지적들과 합친 내용."""
    indices: list[int] = Field(description="이 문제에 속하는 입력 지적 번호들. 혼자면 번호 하나")
    category: Literal["bug", "perf", "unity"] = Field(
        description="문제의 성격에 가장 맞는 분류. bug: 잘못된 동작·예외, perf: 매 프레임 비용·GC 할당, unity: Unity 특유의 잘못된 사용법")
    title: str = Field(description="합친 한 줄 요약")
    reason: str = Field(description="합친 이유")
    suggestion: str = Field(description="합친 수정 제안")
    severity: Severity = Field(description="심각도 기준에 따라 다시 정한 최종 등급")


class MergeDecision(BaseModel):
    """후보 묶음 하나를 같은 문제끼리 나눈 목록. 모든 입력 번호가 정확히 한 번씩 들어간다."""
    issues: list[MergedIssue] = Field(description="문제 목록")
