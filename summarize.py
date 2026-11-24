"""logs/<mode>-t<trial>/rounds.json を読み、ラウンドごとの内訳と、止め時の条件ごとの比較を Markdown の表で出す。

使い方:
    python3 summarize.py            # logs/ の結果を集計
    python3 summarize.py --cap 1    # 「ラウンド上限」を 1 回にしたときの値を full の記録から読む(既定 1)
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
N_SEEDED = len(json.loads((ROOT / "seeded_bugs.json").read_text(encoding="utf-8")))
LABELS = {"full": "毎回全体をレビュー", "verify": "前回指摘の確認のみ", "severity": "high / medium だけ直す"}


def load_all():
    """logs/<mode>-t<trial>/rounds.json を mode・trial の順に読む。"""
    results = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "logs").glob("*-t*/rounds.json")]
    order = list(LABELS)
    return sorted(results, key=lambda r: (order.index(r["mode"]), r["trial"]))


def breakdown(result):
    lines = [f"### {LABELS[result['mode']]} ({result['mode']}, 試行 {result['trial']})", "",
             "| ラウンド | 指摘 | 元から有った行・新規 | 修正で入った行 | 再掲 | high | medium | low "
             "| その時点のテスト |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in result["rounds"]:
        fs = r["findings"]
        kind = [f["kind"] for f in fs]
        sev = [f["severity"] for f in fs]
        lines.append(f"| {r['round']} | {len(fs)} | {kind.count('original_line')} | {kind.count('fix_line')} | "
                     f"{kind.count('repeat')} | {sev.count('high')} | {sev.count('medium')} | {sev.count('low')} | "
                     f"{r['tests_passed_before']}/{N_SEEDED} |")
    lines.append(f"| 終了後 | | | | | | | | {result['tests_passed_final']}/{N_SEEDED} |")
    return "\n".join(lines)


def seeded_found(rounds):
    return {f["seeded"] for r in rounds for f in r["findings"] if f.get("seeded")}


def fixes_applied(rounds):
    return sum(1 for r in rounds if r["fixed_requested"] > 0)


def comparison(results, cap):
    lines = ["| 止め時の条件 | 試行 | 修正を回した回数 | 仕込んだ不具合に付いた指摘 | 終了時のテスト "
             "| 指摘の延べ数 | 費用 (USD) |",
             "|---|---|---|---|---|---|---|"]
    for res in results:
        rounds = res["rounds"]
        total = sum(len(r["findings"]) for r in rounds)
        lines.append(f"| {LABELS[res['mode']]} | {res['trial']} | {fixes_applied(rounds)} | "
                     f"{len(seeded_found(rounds))}/{N_SEEDED} | "
                     f"{res['tests_passed_final']}/{N_SEEDED} | {total} | {res['total_cost_usd']} |")
    for full in (r for r in results if r["mode"] == "full" and len(r["rounds"]) > cap):
        rounds = full["rounds"][:cap]
        after = full["rounds"][cap]["tests_passed_before"]
        total = sum(len(r["findings"]) for r in rounds)
        cost = round(sum(r["cost_usd"] for r in rounds), 4)
        lines.append(f"| ラウンド上限 {cap} 回(full の記録を切る) | {full['trial']} | {fixes_applied(rounds)} | "
                     f"{len(seeded_found(rounds))}/{N_SEEDED} | {after}/{N_SEEDED} | {total} | {cost} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=1)
    args = ap.parse_args()
    results = load_all()
    if not results:
        raise SystemExit("logs/<mode>-t<trial>/rounds.json がありません。先に review_loop.py を回してください")
    for res in results:
        print(breakdown(res))
        print()
    print("### 止め時の条件ごとの比較")
    print()
    print(comparison(results, args.cap))


if __name__ == "__main__":
    main()
