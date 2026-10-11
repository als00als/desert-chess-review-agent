"""그래프 층: 수집, 리뷰어, 검증자, 취합자, 리포트 노드."""
import asyncio
import difflib
import json
import time
from pathlib import Path

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.workers import TOOL_CALLS, WORKERS
from app.core.config import BATCH_LINES, CHAT_MODEL, PASS_PROB, PROJECT_DIR, llm
from app.core.judge import judge_finding, judge_report
from app.core.prompts import (
    MERGE_PROMPT,
    REVIEW_INPUT,
    SUMMARY_PROMPT,
    TO_JSON_PROMPT,
    VERDICT_JSON_PROMPT,
    VERIFY_INPUT,
)
from app.core.schemas import MergeDecision, ReviewBatch, VerifyResult
from app.graph.report import render_report
from app.graph.state import ReviewInput, ReviewState, VerifyInput
from app.tools.collector import collect_files, make_batches, numbered, read_lines, render_batch

USAGE = UsageMetadataCallbackHandler()   # 모델별 토큰 사용량. main 이 실행 config 의 callbacks 에 넣는다
JEV_LIMIT = asyncio.Semaphore(4)         # Jev 동시 호출 수 상한
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
ID_PREFIX = {"bug": "BUG", "perf": "PERF", "unity": "UNITY"}


# [보조 함수] 리뷰어가 적은 파일 경로를 배치 안의 실제 경로로 맞춘다. 대소문자·구분자·폴더 누락 실수를 고친다
def fix_path(path: str, batch_files: list[str]) -> str | None:
    """배치 안에서 path 와 같은(또는 파일 이름이 같은) 경로를 돌려준다. 없으면 None."""
    norm = path.replace("\\", "/").strip().strip("`").lower()
    for f in batch_files:
        if f.lower() == norm:
            return f
    name = norm.rsplit("/", 1)[-1]
    same = [f for f in batch_files if f.lower().rsplit("/", 1)[-1] == name]
    return same[0] if len(same) == 1 else None


# [보조 함수] 실제 코드 발췌: 지적한 줄 앞뒤 5줄을 줄번호와 함께 읽는다. Jev 판정과 리포트 검증에 쓴다
def excerpt(root: Path, file: str, start: int, end: int, pad: int = 5) -> str:
    lines = read_lines(root / file)
    return numbered(lines, max(1, start - pad), min(len(lines), end + pad))


# [보조 함수] 줄 번호 바로잡기: 근거 코드 첫 줄이 실제로 있는 줄을 코드로 찾는다
# 이유: 검증자가 고친 줄 번호는 메서드 전체처럼 넓어지는 일이 많아, 근거 코드가 원래 범위에 있으면 원래 번호를 믿는다
def relocate(f: dict, lines: list[str], v_start: int, v_end: int) -> dict:
    """근거 코드가 원래 범위 → 검증자 범위 → 원래 위치 ±10줄 순서로 있는 곳의 줄 범위를 붙인 지적을 돌려준다."""
    first = next((s.strip() for s in f["evidence"].splitlines() if s.strip()), "")
    span = f["line_end"] - f["line_start"]

    def found(start, end):
        return first and any(first in lines[i - 1] for i in range(max(1, start), min(len(lines), end) + 1))

    if found(f["line_start"], f["line_end"]):
        return f
    if 1 <= v_start <= v_end <= len(lines) and found(v_start, v_end):
        return f | {"line_start": v_start, "line_end": v_end}
    for d in range(1, 11):
        for i in (f["line_start"] - d, f["line_start"] + d):
            if 1 <= i <= len(lines) and first and first in lines[i - 1]:
                return f | {"line_start": i, "line_end": min(len(lines), i + span)}
    return f


# [노드] 수집: LLM 없이 .cs 파일과 Unity 메서드를 모으고 줄 수 기준으로 배치를 나눈다
async def collect(state: ReviewState) -> dict:
    """파일 목록과 배치 목록을 State 에 쓸 값으로 돌려준다."""
    files = collect_files(Path(state["root"]), state["pattern"], tuple(state["exclude"]), state["max_files"])
    batches = make_batches(files, BATCH_LINES)
    total = sum(f["lines"] for f in files)
    print(f"collect: 파일 {len(files)}개 ({total}줄) → 배치 {len(batches)}개 × 리뷰어 {len(state['reviewers'])}명")
    return {"files": files, "batches": batches}


# [노드] 리뷰어: Send 로 (리뷰어 종류 × 배치)마다 하나씩 병렬 실행한다. 결과는 "종류:배치" 키로 raw 에 모인다
async def reviewer(state: ReviewInput) -> dict:
    """리뷰어 에이전트로 배치 하나를 리뷰하고 {"종류:배치": [지적]} 을 돌려준다."""
    kind, batch = state["reviewer"], state["batch"]
    key = f"{kind}:{batch['batch_id']}"
    print(f"reviewer: {key} 시작 (파일 {len(batch['files'])}개)")
    code = render_batch(Path(state["root"]), batch["files"])
    try:
        result = await WORKERS[kind].ainvoke({"messages": [HumanMessage(REVIEW_INPUT.format(code=code))]})
        text = result["messages"][-1].text
        # 에이전트 최종 답(텍스트) → 구조화 출력으로 한 번 더 변환 (create_agent 의 response_format 보다 안전)
        out = await llm.with_structured_output(ReviewBatch).ainvoke([SystemMessage(TO_JSON_PROMPT), HumanMessage(text)])
    except Exception as e:   # 리뷰어 하나가 실패해도 나머지 결과로 리포트를 쓴다
        print(f"reviewer: {key} 실패 {type(e).__name__}: {e}")
        return {"raw": {key: []}, "errors": [f"{key}: {type(e).__name__}: {e}"]}

    items, dropped = [], 0
    for f in out.findings:
        path = fix_path(f.file, batch["files"])
        if path is None:
            dropped += 1
            continue
        items.append(f.model_dump() | {"file": path, "category": kind})
    print(f"reviewer: {key} 지적 {len(items)}건" + (f" (경로 불일치 {dropped}건 제외)" if dropped else ""))
    # 첫 메시지(배치 코드 전체)는 크기만 크고 다시 볼 일이 없어 기록에서 뺀다
    return {"raw": {key: items}, "messages": result["messages"][1:]}


# [노드] 팬인 지점: 모든 reviewer 인스턴스가 끝난 뒤 한 번만 실행되어 dispatch_verify 로 분기한다
async def plan_verify(state: ReviewState) -> dict:
    total = sum(len(v) for v in state["raw"].values())
    files = len({f["file"] for v in state["raw"].values() for f in v})
    print(f"plan_verify: 리뷰 {len(state['raw'])}건 완료, 지적 {total}건 → 파일 {files}개 검증")
    return {}


# [노드] 검증자: Send 로 파일마다 병렬 실행한다. GPT 검증자가 줄을 다시 읽어 소견을 쓰고, Jev 확률로 통과를 정한다
async def verifier(state: VerifyInput) -> dict:
    """파일 하나의 지적 묶음을 검증해 {"verified": {파일: [통과]}, "rejected": [기각]} 을 돌려준다."""
    root, file, items = Path(state["root"]), state["file"], state["findings"]
    listing = "\n\n".join(
        f"[{i}] 줄 {f['line_start']}-{f['line_end']} ({f['category']}, {f['severity']}) {f['title']}\n"
        f"근거 코드: {f['evidence']}\n이유: {f['reason']}" for i, f in enumerate(items))
    try:
        result = await WORKERS["verifier"].ainvoke({"messages": [HumanMessage(VERIFY_INPUT.format(file=file, findings=listing))]})
        out = await llm.with_structured_output(VerifyResult).ainvoke([
            SystemMessage(VERDICT_JSON_PROMPT.format(count=len(items))), HumanMessage(result["messages"][-1].text)])
        verdicts = {v.index: v for v in out.verdicts}
        messages = result["messages"]
    except Exception as e:
        print(f"verifier: {file} 실패 {type(e).__name__}: {e}")
        return {"rejected": [{"finding": f, "reason": f"검증 실패: {type(e).__name__}"} for f in items],
                "errors": [f"verifier {file}: {type(e).__name__}: {e}"]}

    lines = read_lines(root / file)

    async def judge_one(i: int, f: dict) -> tuple[dict, str | None]:
        """지적 하나를 판정해 (지적, 기각 사유 또는 None) 을 돌려준다."""
        v = verdicts.get(i)
        if v is None:
            return f, "검증 답변 없음"
        if not v.exists:
            return f, f"코드 없음: {v.note}"
        if not v.valid:
            return f, f"검증자 부당 판정: {v.note}"
        f = relocate(f, lines, v.line_start, v.line_end) | {"verifier_note": v.note}
        async with JEV_LIMIT:
            try:
                prob = await judge_finding(excerpt(root, file, f["line_start"], f["line_end"]),
                                           {k: f[k] for k in ("title", "evidence", "reason", "category")}, v.note)
            except Exception as e:   # Jev 가 실패하면 GPT 판정만으로 통과시키고 기록한다
                print(f"verifier: Jev 실패 {type(e).__name__}: {e}")
                prob = None
        f = f | {"confidence": prob}
        if prob is not None and prob < PASS_PROB:
            return f, f"Jev 타당 확률 {prob:.2f} < {PASS_PROB}: {v.note}"
        return f | {"verified": True}, None

    judged = await asyncio.gather(*(judge_one(i, f) for i, f in enumerate(items)))
    passed = [f for f, why in judged if why is None]
    rejected = [{"finding": f, "reason": why} for f, why in judged if why is not None]
    print(f"verifier: {file} 통과 {len(passed)} / 기각 {len(rejected)}")
    return {"verified": {file: passed}, "rejected": rejected, "messages": messages[1:]}


# [보조 함수] 병합 후보 찾기: 같은 파일에서 줄 범위가 겹치거나(±1) 근거 코드가 거의 같으면 한 묶음
# 제목은 리뷰어마다 표현이 달라 유사도로 거르지 않는다. 묶음 안을 같은 문제끼리 나누는 일은 LLM 이 한다
def candidate_groups(items: list[dict]) -> list[list[dict]]:
    """union-find 로 묶은 지적 그룹 목록을 돌려준다. 혼자인 지적도 길이 1 그룹으로 들어간다."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(items):
        for j in range(i + 1, len(items)):
            b = items[j]
            if a["file"] != b["file"]:
                continue
            overlap = a["line_start"] <= b["line_end"] + 1 and b["line_start"] <= a["line_end"] + 1
            same_code = difflib.SequenceMatcher(None, a["evidence"], b["evidence"]).ratio() >= 0.8
            if overlap or same_code:
                parent[find(j)] = find(i)
    groups = {}
    for i, f in enumerate(items):
        groups.setdefault(find(i), []).append(f)
    return list(groups.values())


# [노드] 취합자: 코드로 병합 후보를 찾고, 후보 묶음만 LLM 에 같은 문제인지 묻는다. 정렬하고 id 를 붙인다
async def aggregator(state: ReviewState) -> dict:
    """병합·정렬한 최종 지적 목록을 State 에 쓸 값으로 돌려준다."""
    items = [f for fs in state["verified"].values() for f in fs]
    groups = candidate_groups(items)

    async def merge(group: list[dict]) -> list[dict]:
        if len(group) == 1:
            return group
        text = "\n\n".join(f"[{i}] ({f['category']}, {f['severity']}) {f['file']}:{f['line_start']}-{f['line_end']} {f['title']}\n"
                           f"근거 코드: {f['evidence']}\n이유: {f['reason']}\n수정 제안: {f['suggestion']}"
                           for i, f in enumerate(group))
        try:
            d = await llm.with_structured_output(MergeDecision).ainvoke([SystemMessage(MERGE_PROMPT), HumanMessage(text)])
        except Exception as e:
            print(f"aggregator: 병합 판단 실패 {type(e).__name__}: {e}")
            return group
        out, seen = [], set()
        for issue in d.issues:
            members = [group[i] for i in dict.fromkeys(issue.indices) if 0 <= i < len(group) and i not in seen]
            if not members:
                continue
            seen.update(i for i in issue.indices if 0 <= i < len(group))
            # 가장 심각한 원래 지적을 바탕으로, 위치는 가장 좁은 지적 것을 쓴다
            base = min(members, key=lambda f: SEVERITY_ORDER[f["severity"]])
            narrow = min(members, key=lambda f: f["line_end"] - f["line_start"])
            confs = [f["confidence"] for f in members if f.get("confidence") is not None]
            out.append(base | {"title": issue.title, "reason": issue.reason, "suggestion": issue.suggestion,
                               "severity": issue.severity, "line_start": narrow["line_start"],
                               "line_end": narrow["line_end"], "evidence": narrow["evidence"],
                               "also": sorted({f["category"] for f in members} - {base["category"]}),
                               "confidence": max(confs) if confs else None})
        # 모델이 빠뜨린 번호는 그대로 남긴다 (지적을 잃지 않게)
        out += [f for i, f in enumerate(group) if i not in seen]
        return out

    merged = [f for out in await asyncio.gather(*(merge(g) for g in groups)) for f in out]
    merged.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["file"], f["line_start"]))
    counters = {}
    final = []
    for f in merged:
        counters[f["category"]] = counters.get(f["category"], 0) + 1
        final.append({"id": f"{ID_PREFIX[f['category']]}-{counters[f['category']]:03d}", **f})
    print(f"aggregator: 검증 통과 {len(items)}건 → 병합 후 {len(final)}건")
    return {"final": final, "merged_count": len(items) - len(final)}


# [노드] 리포트: 표·목록·통계는 코드로 만들고 총평만 LLM 이 쓴다. md·json·status 를 산출물 폴더에 저장한다
async def reporter(state: ReviewState) -> dict:
    """review_report.md, findings.json, status.json 을 저장한다."""
    final = state.get("final", [])
    summary = "지적 없음."
    if final:
        brief = "\n".join(f"{f['id']} {f['severity']} {f['file']}:{f['line_start']} {f['title']}" for f in final)
        try:
            summary = (await llm.ainvoke([SystemMessage(SUMMARY_PROMPT), HumanMessage(brief)])).text
        except Exception as e:
            summary = f"(총평 생성 실패: {type(e).__name__})"

    raw_count = sum(len(v) for v in state["raw"].values())
    usage = {model: dict(u) for model, u in USAGE.usage_metadata.items()}
    tokens = sum(u.get("total_tokens", 0) for u in usage.values())
    stats = {
        "model": CHAT_MODEL,
        "files": len(state["files"]),
        "lines": sum(f["lines"] for f in state["files"]),
        "batches": len(state["batches"]),
        "reviewers": state["reviewers"],
        "raw_findings": raw_count,
        "rejected": len(state["rejected"]),
        "merged": state.get("merged_count", 0),
        "final": len(final),
        "by_severity": {s: sum(f["severity"] == s for f in final) for s in SEVERITY_ORDER},
        "by_category": {c: sum(f["category"] == c for f in final) for c in ID_PREFIX},
        "elapsed_sec": round(time.time() - state["started"], 1),
        "tokens": tokens,
        "usage": usage,
        "tool_calls": dict(TOOL_CALLS),
        "errors": state["errors"],
    }
    report = render_report(stats, summary, final, state["rejected"], state["files"])
    try:   # 리포트 실행 가능성 점수(0~3). 실패해도 리포트는 남긴다
        stats["jev_actionability"] = await judge_report(report) if final else None
    except Exception as e:
        stats["jev_actionability"] = f"실패: {type(e).__name__}"

    out = PROJECT_DIR / state["run_dir"]
    (out / "review_report.md").write_text(report, encoding="utf-8")
    (out / "findings.json").write_text(json.dumps({"findings": final, "rejected": state["rejected"]},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"reporter: 최종 {len(final)}건 (기각 {stats['rejected']}, 병합 {stats['merged']}) "
          f"{stats['elapsed_sec']}초, 토큰 {tokens:,}")
    return {}
