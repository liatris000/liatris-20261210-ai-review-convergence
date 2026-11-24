"""review_loop.py の分類ロジックのテスト。claude は呼ばない。"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review_loop as rl  # noqa: E402


def make_repo(tmp_path, first, second):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                       check=True, capture_output=True)
    (tmp_path / "orders.py").write_text(first)
    git("init", "-q")
    git("add", "orders.py")
    git("commit", "-q", "-m", "base")
    base = rl.git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "orders.py").write_text(second)
    git("commit", "-q", "-am", "fix")
    return base


def test_blame_separates_original_and_fix_lines(tmp_path):
    base = make_repo(tmp_path, "a = 1\nb = 2\nc = 3\n", "a = 1\nnew = 9\nb = 2\nc = 3\n")
    assert rl.blame_anchor(tmp_path, 1) == (base, 1)
    origin, _ = rl.blame_anchor(tmp_path, 2)
    assert origin != base
    assert rl.blame_anchor(tmp_path, 3) == (base, 2)


def test_classify_repeat_original_fix():
    prior = [{"origin": "base", "orig_line": 10, "category": "bug"}]
    assert rl.classify({"origin": "base", "orig_line": 12, "category": "bug"}, "base", prior) == "repeat"
    assert rl.classify({"origin": "base", "orig_line": 12, "category": "style"}, "base", prior) == "original_line"
    assert rl.classify({"origin": "base", "orig_line": 20, "category": "bug"}, "base", prior) == "original_line"
    assert rl.classify({"origin": "fix1", "orig_line": 10, "category": "bug"}, "base", prior) == "fix_line"


def test_seeded_hit_uses_function_ranges():
    source = (Path(rl.ROOT) / "subject" / "orders.py").read_text(encoding="utf-8")
    ranges = rl.function_ranges(source)
    lo, _ = ranges["paginate"]
    assert rl.seeded_hit("base", "base", lo + 2, ranges) == "page-offset"
    assert rl.seeded_hit("fix1", "base", lo + 2, ranges) is None


def test_extractors():
    assert rl.extract_json_array('note\n[{"line": 1}]\n') == [{"line": 1}]
    assert rl.extract_python("x\n```python\nprint(1)\n```\n") == "print(1)\n"
