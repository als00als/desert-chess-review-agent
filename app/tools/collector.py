"""도구 층: LLM 없이 C# 파일을 모으고 클래스·Unity 메시지 메서드를 정규식으로 뽑는다.

collect 노드와 @tool get_unity_methods, 줄번호 붙인 코드 렌더링이 이 함수들을 함께 쓴다.
"""
import fnmatch
import re
from pathlib import Path

# Unity 가 이름으로 불러 주는 메시지 메서드. 리뷰어에게 "매 프레임 호출" 같은 힌트를 주는 데 쓴다
UNITY_MESSAGES = (
    "Awake", "Start", "OnEnable", "OnDisable", "OnDestroy", "Update", "LateUpdate", "FixedUpdate",
    "OnValidate", "Reset", "OnApplicationQuit", "OnApplicationPause",
    "OnTriggerEnter", "OnTriggerEnter2D", "OnTriggerStay", "OnTriggerStay2D", "OnTriggerExit", "OnTriggerExit2D",
    "OnCollisionEnter", "OnCollisionEnter2D", "OnCollisionStay", "OnCollisionStay2D",
    "OnCollisionExit", "OnCollisionExit2D", "OnGUI", "OnDrawGizmos", "OnDrawGizmosSelected",
    "OnBecameVisible", "OnBecameInvisible",
)
PER_FRAME = ("Update", "LateUpdate", "FixedUpdate", "OnGUI", "OnTriggerStay", "OnTriggerStay2D",
             "OnCollisionStay", "OnCollisionStay2D")

CLASS_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|abstract|sealed|static|partial)\s+)*"
                      r"class\s+(\w+)(?:\s*<[^>]*>)?(?:\s*:\s*([\w<>.,\s]+?))?\s*(?:where\b.*)?\{?\s*$")
METHOD_RE = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|async|new)\s+)*"
                       r"(?:void|IEnumerator|async\s+void|Task|Awaitable)\s+(" + "|".join(UNITY_MESSAGES) + r")\s*\(")


def read_lines(path: Path) -> list[str]:
    """C# 파일을 줄 목록으로 읽는다. UTF-8 BOM 은 utf-8-sig 가 떼고, CRLF 는 splitlines 가 처리한다."""
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()


def method_end(lines: list[str], start: int) -> int:
    """start 줄(0부터)에서 시작하는 메서드의 닫는 중괄호 줄(0부터)을 찾는다. 문자열 안 중괄호는 무시하지 않는 근사치다."""
    depth, opened = 0, False
    for i in range(start, len(lines)):
        code = lines[i].split("//", 1)[0]
        depth += code.count("{") - code.count("}")
        if "{" in code:
            opened = True
        if opened and depth <= 0:
            return i
        if not opened and "=>" in code and code.rstrip().endswith(";"):
            return i                                   # 식 본문 메서드 (void Update() => Foo();)
    return len(lines) - 1


def unity_info(lines: list[str]) -> dict:
    """클래스 이름·상속, Unity 메시지 메서드와 그 줄 범위(1부터)를 돌려준다."""
    classes, methods = [], []
    for i, line in enumerate(lines):
        m = CLASS_RE.match(line)
        if m:
            classes.append({"name": m.group(1), "base": (m.group(2) or "").strip(), "line": i + 1})
        m = METHOD_RE.match(line)
        if m:
            methods.append({"name": m.group(1), "start": i + 1, "end": method_end(lines, i) + 1})
    return {"classes": classes, "unity_methods": methods}


def collect_files(root: Path, pattern: str = "**/*.cs", exclude: tuple[str, ...] = (), max_files: int = 0) -> list[dict]:
    """root 아래 C# 파일을 모아 [{path, lines, classes, unity_methods}] 로 돌려준다. path 는 루트 기준 상대경로('/' 구분)."""
    files = []
    for p in sorted(root.rglob("*.cs")):
        rel = p.relative_to(root).as_posix()
        if any(part in exclude for part in p.relative_to(root).parts[:-1]):
            continue
        if pattern not in ("", "**/*.cs") and not fnmatch.fnmatch(rel, pattern):
            continue
        lines = read_lines(p)
        files.append({"path": rel, "lines": len(lines), **unity_info(lines)})
        if max_files and len(files) >= max_files:
            break
    return files


def make_batches(files: list[dict], max_lines: int) -> list[dict]:
    """파일을 줄 수 합이 max_lines 를 넘지 않게 묶는다. 한 파일이 max_lines 보다 길면 그 파일 혼자 한 배치다."""
    batches, current, size = [], [], 0
    for f in files:
        if current and size + f["lines"] > max_lines:
            batches.append(current)
            current, size = [], 0
        current.append(f["path"])
        size += f["lines"]
    if current:
        batches.append(current)
    return [{"batch_id": f"b{i:02d}", "files": b} for i, b in enumerate(batches, 1)]


def hint_line(info: dict) -> str:
    """리뷰어에게 줄 한 줄 힌트: 클래스, 상속, Unity 메서드(매 프레임 호출 표시)."""
    cls = ", ".join(f"{c['name']}" + (f" : {c['base']}" if c["base"] else "") for c in info["classes"]) or "-"
    meth = ", ".join(f"{m['name']}({m['start']}-{m['end']}){'*' if m['name'] in PER_FRAME else ''}"
                     for m in info["unity_methods"]) or "-"
    return f"클래스: {cls} | Unity 메서드: {meth}"


def numbered(lines: list[str], start: int = 1, end: int = 0) -> str:
    """줄 목록을 '   42│ code' 모양으로 렌더링한다. start, end 는 1부터, end=0 이면 끝까지."""
    end = min(end or len(lines), len(lines))
    return "\n".join(f"{i:>5}│ {lines[i - 1]}" for i in range(max(1, start), end + 1))


def render_batch(root: Path, paths: list[str]) -> str:
    """배치 파일들의 전체 코드를 줄번호와 힌트를 붙여 하나의 글로 만든다."""
    parts = []
    for rel in paths:
        lines = read_lines(root / rel)
        parts.append(f"===== FILE: {rel} ({len(lines)}줄)\n{hint_line(unity_info(lines))}\n{numbered(lines)}")
    return "\n\n".join(parts)
