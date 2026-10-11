"""도구 층: 리뷰어·검증자가 다른 파일 맥락을 확인할 때 쓰는 @tool 네 개.

MCP filesystem 서버의 읽기 결과에는 줄번호가 없어서, 줄번호가 붙은 결과를 주는 도구를 직접 만든다.
모델에게는 리뷰 루트 기준 상대경로만 보여 주고, 루트는 클로저로 감춘다(한글·공백 절대경로는 옮겨 적다 깨진다).
"""
import re
from pathlib import Path

from langchain.tools import tool

from app.tools.collector import hint_line, numbered, read_lines, unity_info

READ_MAX = 300    # read_file 한 번에 돌려주는 최대 줄 수
GREP_MAX = 50     # grep_code 가 돌려주는 최대 건수


def safe_path(root: Path, rel: str) -> Path:
    """상대경로를 루트 아래 절대경로로 바꾼다. 루트 밖으로 나가면 ValueError."""
    p = (root / rel.strip().lstrip("/\\")).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"리뷰 루트 밖 경로는 읽을 수 없습니다: {rel}")
    return p


def build_tools(root: Path) -> list:
    """리뷰 루트를 클로저로 감싼 도구 네 개 [read_file, grep_code, list_files, get_unity_methods] 를 돌려준다."""
    root = root.resolve()

    @tool
    def read_file(path: str, start: int = 1, end: int = 0) -> str:
        """리뷰 루트 기준 상대경로의 C# 파일을 줄번호와 함께 읽는다. end=0 이면 start 부터 300줄."""
        try:
            lines = read_lines(safe_path(root, path))
        except (ValueError, OSError) as e:
            return f"읽기 실패: {e}"
        start = max(1, start)
        end = min(end or start + READ_MAX - 1, start + READ_MAX - 1, len(lines))
        return f"{path} ({len(lines)}줄 중 {start}-{end})\n{numbered(lines, start, end)}"

    @tool
    def grep_code(pattern: str) -> str:
        """리뷰 루트 아래 .cs 파일에서 정규식을 찾아 '파일:줄: 내용'을 최대 50건 돌려준다. 호출하는 곳·선언 위치 찾기에 쓴다."""
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"정규식 오류: {e}"
        hits = []
        for p in sorted(root.rglob("*.cs")):
            for i, line in enumerate(read_lines(p), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(root).as_posix()}:{i}: {line.strip()}")
                    if len(hits) >= GREP_MAX:
                        return "\n".join(hits) + f"\n(상한 {GREP_MAX}건에서 멈춤)"
        return "\n".join(hits) or "결과 없음"

    @tool
    def list_files(subdir: str = "") -> str:
        """리뷰 루트(또는 그 아래 subdir) 의 .cs 파일 상대경로 목록을 돌려준다."""
        try:
            base = safe_path(root, subdir)
        except ValueError as e:
            return str(e)
        return "\n".join(p.relative_to(root).as_posix() for p in sorted(base.rglob("*.cs"))) or "파일 없음"

    @tool
    def get_unity_methods(path: str) -> str:
        """C# 파일의 클래스·상속과 Unity 메시지 메서드(Awake/Update 등)의 줄 범위를 돌려준다. *는 매 프레임 호출."""
        try:
            lines = read_lines(safe_path(root, path))
        except (ValueError, OSError) as e:
            return f"읽기 실패: {e}"
        return f"{path}: {hint_line(unity_info(lines))}"

    return [read_file, grep_code, list_files, get_unity_methods]
