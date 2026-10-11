"""그래프 층: 리포트 마크다운을 코드로 만든다. 숫자와 표는 LLM 에 맡기지 않는다."""

CATEGORY_NAME = {"bug": "버그", "perf": "성능", "unity": "Unity 안티패턴"}
SEVERITY_NAME = {"P0": "P0 즉시 수정 (크래시·진행 불가)", "P1": "P1 잘못된 동작", "P2": "P2 성능·잠재 버그", "P3": "P3 유지보수"}


def cell(text: str) -> str:
    """표 칸에 넣을 수 있게 줄바꿈과 | 를 바꾼다."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def code_block(text: str) -> str:
    return "```csharp\n" + text.strip("\n") + "\n```"


def render_finding(f: dict) -> str:
    also = f" (+{', '.join(CATEGORY_NAME[c] for c in f['also'])})" if f.get("also") else ""
    conf = f" · Jev {f['confidence']:.2f}" if isinstance(f.get("confidence"), float) else ""
    loc = f"{f['line_start']}" if f["line_start"] == f["line_end"] else f"{f['line_start']}-{f['line_end']}"
    return "\n".join([
        f"#### {f['id']} · {f['title']}",
        f"- 위치: `{f['file']}:{loc}` · 분류: {CATEGORY_NAME[f['category']]}{also}{conf}",
        f"- 이유: {f['reason']}",
        f"- 수정 제안: {f['suggestion']}",
        "",
        code_block(f["evidence"]),
    ])


def render_report(stats: dict, summary: str, final: list[dict], rejected: list[dict], files: list[dict]) -> str:
    """기획서 6.3 순서(요약 → 총평 → 등급별 지적 → 파일별 표 → 기각 부록)로 리포트를 만든다."""
    sev, cat = stats["by_severity"], stats["by_category"]
    out = [
        "# Unity 코드 리뷰 리포트",
        "",
        "## 1. 요약",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 리뷰 파일 | {stats['files']}개 ({stats['lines']:,}줄, 배치 {stats['batches']}개) |",
        f"| 리뷰어 | {', '.join(CATEGORY_NAME[r] for r in stats['reviewers'])} |",
        f"| 리뷰어 지적 → 최종 | {stats['raw_findings']}건 → **{stats['final']}건** (검증 기각 {stats['rejected']}, 병합 {stats['merged']}) |",
        f"| 등급별 | P0 {sev['P0']} · P1 {sev['P1']} · P2 {sev['P2']} · P3 {sev['P3']} |",
        f"| 분류별 | 버그 {cat['bug']} · 성능 {cat['perf']} · Unity {cat['unity']} |",
        f"| 소요 시간 · 토큰 | {stats['elapsed_sec']}초 · {stats['tokens']:,} 토큰 ({stats['model']}) |",
    ]
    if stats["errors"]:
        out.append(f"| 실패한 작업 | {len(stats['errors'])}건 (status.json 참고) |")
    out += ["", "## 2. 총평", "", summary.strip(), "", "## 3. 지적 목록"]
    for s, name in SEVERITY_NAME.items():
        items = [f for f in final if f["severity"] == s]
        if items:
            out += ["", f"### {name} — {len(items)}건", ""]
            out += [render_finding(f) + "\n" for f in items]
    if not final:
        out += ["", "검증을 통과한 지적이 없습니다."]

    out += ["", "## 4. 파일별 요약", "", "| 파일 | 줄 | P0 | P1 | P2 | P3 |", "| --- | --- | --- | --- | --- | --- |"]
    for file in files:
        mine = [f for f in final if f["file"] == file["path"]]
        if mine:
            counts = " | ".join(str(sum(f["severity"] == s for f in mine)) for s in SEVERITY_NAME)
            out.append(f"| `{file['path']}` | {file['lines']} | {counts} |")
    clean = sum(1 for file in files if not any(f["file"] == file["path"] for f in final))
    out += ["", f"지적 없는 파일: {clean}개"]

    out += ["", "## 5. 부록: 검증에서 기각된 지적", ""]
    if rejected:
        out += ["| 위치 | 분류 | 지적 | 기각 사유 |", "| --- | --- | --- | --- |"]
        for r in rejected:
            f = r["finding"]
            out.append(f"| `{f['file']}:{f['line_start']}` | {f['category']} | {cell(f['title'])} | {cell(r['reason'])} |")
    else:
        out.append("없음")
    return "\n".join(out) + "\n"
