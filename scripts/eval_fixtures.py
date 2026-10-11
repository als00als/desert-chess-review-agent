"""fixtures 탐지율 계산: findings.json 과 expected.json 을 파일 + 줄(±3) + 분류로 매칭한다.

사용: uv run python scripts/eval_fixtures.py [output/<실행 폴더>]   (생략하면 가장 최근 실행)
"""
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
EXPECTED = PROJECT_DIR / "fixtures" / "SeededBugs" / "expected.json"
TOLERANCE = 3


def near(f: dict, line: int) -> bool:
    return f["line_start"] - TOLERANCE <= line <= f["line_end"] + TOLERANCE


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    runs = sorted(p for p in (PROJECT_DIR / "output").iterdir() if (p / "findings.json").exists())
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else runs[-1]
    findings = json.loads((run / "findings.json").read_text(encoding="utf-8"))["findings"]
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

    used, rows = set(), []
    for e in expected["seeded"]:
        # 같은 파일, 줄 ±3, 분류(병합된 also 포함)가 맞는 지적 중 아직 매칭되지 않은 것 하나
        hit = next((i for i, f in enumerate(findings)
                    if i not in used and f["file"].endswith(e["file"]) and near(f, e["line"])
                    and ({f["category"], *f.get("also", [])} & set(e["category"]))), None)
        if hit is None:   # 분류는 달라도 위치가 맞으면 '위치만 일치'로 따로 센다
            loose = next((i for i, f in enumerate(findings)
                          if i not in used and f["file"].endswith(e["file"]) and near(f, e["line"])), None)
            rows.append((e, None, loose))
        else:
            used.add(hit)
            rows.append((e, hit, None))

    traps = [f for f in findings for t in expected["traps"]
             if f["file"].endswith(t["file"]) and f["line_start"] <= t["line_end"] and f["line_end"] >= t["line_start"]]
    detected = sum(1 for _, hit, _ in rows if hit is not None)

    print(f"실행: {run.name}")
    print("| # | 심은 문제 | 기대 분류 | 결과 |")
    print("| --- | --- | --- | --- |")
    for e, hit, loose in rows:
        if hit is not None:
            f = findings[hit]
            result = f"✅ {f['id']} ({f['severity']}) {f['file']}:{f['line_start']}"
        elif loose is not None:
            result = f"△ 위치만 일치 {findings[loose]['id']}"
        else:
            result = "❌ 미탐지"
        print(f"| {e['id']} | {e['keyword']} | {'/'.join(e['category'])} | {result} |")
    print(f"\n탐지: {detected}/{len(rows)} · 함정 오탐: {len(traps)}건 · 정답 밖 지적: {len(findings) - len(used)}건")
    for f in findings:
        if findings.index(f) not in used:
            print(f"  - 정답 밖: {f['id']} {f['file']}:{f['line_start']} {f['title']}")


if __name__ == "__main__":
    main()
