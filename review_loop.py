"""同じコードに AI レビュー → 修正を何ラウンドか回し、指摘を「どこで生まれたか」で分けて記録する。

使い方:
    python3 review_loop.py --mode full --max-rounds 5 --trial 1
    python3 review_loop.py --mode verify --max-rounds 5 --trial 1
    python3 review_loop.py --mode severity --max-rounds 5 --trial 1

mode:
    full      毎ラウンド全体をレビューし、出た指摘を全部直す。指摘 0 件で止める
    verify    1 回目だけ全体をレビューし、2 回目以降は前の回の指摘が直ったかだけ確かめる
    severity  毎ラウンド全体をレビューし、high / medium だけ直す。high / medium が 0 件で止める

レビュアーと修正役は `claude -p`(Claude Code のヘッドレス実行)。ツールは渡さず、コードはプロンプトに埋め込む。
各ラウンドの修正は work/<mode>/ の git リポジトリにコミットし、指摘の行を git blame で 1 回目のコミットまで辿る。
"""

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUBJECT = ROOT / "subject" / "orders.py"
SEEDED = json.loads((ROOT / "seeded_bugs.json").read_text(encoding="utf-8"))
CATEGORIES = ["bug", "error-handling", "validation", "security", "performance", "design", "style", "docs"]
SAME_LINE_WINDOW = 3

REVIEW_PROMPT = """You are reviewing a Python module before it is merged.
List every problem you think should be fixed. Do not use any tools; the full file is below with line numbers.

Respond with ONLY a JSON array (no prose, no code fence). Each element:
{{"line": <int line number in the file below>, "severity": "high"|"medium"|"low",
  "category": one of {categories}, "title": "<short English summary>"}}
Return [] if there is nothing to fix.

File: orders.py
{numbered}
"""

VERIFY_PROMPT = """You previously reviewed this Python module and reported the findings below.
The author has pushed a revision. Check ONLY whether each previous finding is now resolved.
Do not report new problems. Do not use any tools.

Respond with ONLY a JSON array (no prose, no code fence), one element per previous finding, in the same order:
{{"id": <int>, "resolved": true|false, "line": <int line in the new file, or null>}}

Previous findings:
{previous}

File: orders.py
{numbered}
"""

FIX_PROMPT = """Fix the following review findings in this Python module. Keep the public function names.
Do not use any tools. Respond with ONLY the full updated file inside one ```python code block.

Findings:
{findings}

File: orders.py
{source}
"""


def run_claude(prompt):
    """claude -p を 1 回呼び、(本文, 費用 USD) を返す。"""
    cmd = ["claude", "-p", "--output-format", "json", "--tools", "", "--no-session-persistence"]
    out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600, check=True)
    data = json.loads(out.stdout)
    return data["result"], data.get("total_cost_usd", 0.0)


def extract_json_array(text):
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError(f"JSON 配列が見つからない: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def extract_python(text):
    m = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    if not m:
        raise ValueError(f"python のコードブロックが見つからない: {text[:200]!r}")
    return m.group(1)


def numbered(source):
    return "\n".join(f"{i:>3}: {line}" for i, line in enumerate(source.splitlines(), 1))


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def blame_anchor(repo, line):
    """行を、その行を入れたコミットと、そのコミットでの行番号に辿る。"""
    n_lines = len((repo / "orders.py").read_text(encoding="utf-8").splitlines())
    line = min(max(int(line), 1), n_lines)
    porcelain = git(repo, "blame", "--porcelain", "-L", f"{line},{line}", "HEAD", "--", "orders.py")
    sha, orig_line = porcelain.split()[:2]
    return sha, int(orig_line)


def function_ranges(source):
    tree = ast.parse(source)
    return {n.name: (n.lineno, n.end_lineno) for n in tree.body if isinstance(n, ast.FunctionDef)}


def seeded_hit(origin, base_sha, orig_line, base_ranges):
    """元のコードの行に付いた指摘なら、その行を含む仕込みの不具合の id を返す。"""
    if origin != base_sha:
        return None
    for bug in SEEDED:
        lo, hi = base_ranges[bug["function"]]
        if lo <= orig_line <= hi:
            return bug["id"]
    return None


def is_same(a, b):
    """同じ指摘か: blame で辿った行が同じコミットの ±3 行以内で、カテゴリが同じ。"""
    return (a["origin"] == b["origin"] and abs(a["orig_line"] - b["orig_line"]) <= SAME_LINE_WINDOW
            and a["category"] == b["category"])


def classify(finding, base_sha, prior):
    if any(is_same(finding, p) for p in prior):
        return "repeat"
    return "original_line" if finding["origin"] == base_sha else "fix_line"


def run_tests(path):
    """仕込みの不具合のテストを、そのラウンドのコードに対して回し、通った数を返す。"""
    env = {"SUBJECT": str(path), "PATH": "/usr/bin:/bin:/usr/local/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "tests" / "test_seeded.py")]
    out = subprocess.run(cmd, capture_output=True, text=True, env=env)
    m = re.search(r"(\d+) passed", out.stdout)
    return int(m.group(1)) if m else 0


def ask_json(prompt, log_dir, name):
    for attempt in range(2):
        text, cost = run_claude(prompt)
        (log_dir / f"{name}.raw.txt").write_text(text, encoding="utf-8")
        try:
            return extract_json_array(text), cost
        except (ValueError, json.JSONDecodeError):
            if attempt == 1:
                raise
    raise RuntimeError("unreachable")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "verify", "severity"], required=True)
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--trial", type=int, default=1, help="同じ条件を何度か回すときの番号。logs/<mode>-t<trial>/ に書く")
    args = ap.parse_args()

    name = f"{args.mode}-t{args.trial}"
    repo = ROOT / "work" / name
    log_dir = ROOT / "logs" / name
    shutil.rmtree(repo, ignore_errors=True)
    shutil.rmtree(log_dir, ignore_errors=True)
    repo.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    shutil.copy(SUBJECT, repo / "orders.py")
    git(repo, "init", "-q")
    git(repo, "-c", "user.name=loop", "-c", "user.email=loop@example.invalid", "add", "orders.py")
    git(repo, "-c", "user.name=loop", "-c", "user.email=loop@example.invalid", "commit", "-q", "-m", "round 0")
    base_sha = git(repo, "rev-parse", "HEAD").strip()
    base_ranges = function_ranges(SUBJECT.read_text(encoding="utf-8"))

    prior, rounds, total_cost = [], [], 0.0
    previous_open = []
    for rnd in range(1, args.max_rounds + 1):
        source = (repo / "orders.py").read_text(encoding="utf-8")
        (log_dir / f"round{rnd}.orders.py.txt").write_text(source, encoding="utf-8")
        passed = run_tests(repo / "orders.py")

        if args.mode == "verify" and rnd > 1:
            prev_text = "\n".join(f'{i}. line {f["line"]}: [{f["severity"]}] {f["title"]}'
                                  for i, f in enumerate(previous_open))
            verdicts, cost = ask_json(VERIFY_PROMPT.format(previous=prev_text, numbered=numbered(source)),
                                             log_dir, f"round{rnd}.verify")
            resolved = {int(v["id"]) for v in verdicts if v.get("resolved")}
            new_line = {int(v["id"]): v.get("line") for v in verdicts}
            findings = [dict(f, kind="repeat", line=new_line.get(i) or f["line"])
                        for i, f in enumerate(previous_open) if i not in resolved]
        else:
            raw, cost = ask_json(REVIEW_PROMPT.format(categories=CATEGORIES, numbered=numbered(source)),
                                        log_dir, f"round{rnd}.review")
            findings = []
            for f in raw:
                origin, orig_line = blame_anchor(repo, f["line"])
                f = dict(f, origin=origin, orig_line=orig_line,
                         seeded=seeded_hit(origin, base_sha, orig_line, base_ranges))
                f["kind"] = classify(f, base_sha, prior)
                findings.append(f)
        total_cost += cost

        to_fix = findings
        if args.mode == "severity":
            to_fix = [f for f in findings if f["severity"] in ("high", "medium")]
        record = {"round": rnd, "tests_passed_before": passed, "findings": findings,
                  "fixed_requested": len(to_fix), "cost_usd": round(cost, 4)}

        if not to_fix:
            record["stopped"] = True
            rounds.append(record)
            break

        fix_list = "\n".join(f'- line {f["line"]}: [{f["severity"]}] {f["title"]}' for f in to_fix)
        fix_text, fix_cost = run_claude(FIX_PROMPT.format(findings=fix_list, source=source))
        (log_dir / f"round{rnd}.fix.raw.txt").write_text(fix_text, encoding="utf-8")
        total_cost += fix_cost
        record["cost_usd"] = round(cost + fix_cost, 4)
        (repo / "orders.py").write_text(extract_python(fix_text), encoding="utf-8")
        git(repo, "-c", "user.name=loop", "-c", "user.email=loop@example.invalid",
            "commit", "-q", "-am", f"round {rnd} fix")

        prior.extend(findings)
        previous_open = to_fix
        rounds.append(record)
        kinds = [f["kind"] for f in findings]
        print(f"[{name}] round {rnd}: findings={len(findings)} original_line={kinds.count('original_line')} "
              f"fix_line={kinds.count('fix_line')} repeat={kinds.count('repeat')} tests_passed_before={passed}/6",
              flush=True)

    final_source = (repo / "orders.py").read_text(encoding="utf-8")
    (log_dir / "final.orders.py.txt").write_text(final_source, encoding="utf-8")
    result = {"mode": args.mode, "trial": args.trial, "max_rounds": args.max_rounds, "rounds": rounds,
              "tests_passed_final": run_tests(repo / "orders.py"), "total_cost_usd": round(total_cost, 4)}
    (log_dir / "rounds.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{name}] done: rounds={len(rounds)} tests_passed_final={result['tests_passed_final']}/6 "
          f"cost=${result['total_cost_usd']}")


if __name__ == "__main__":
    main()
