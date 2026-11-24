"""logs/ に残した各試行の最終コードが、記録どおりの数だけ仕込みのテストを通すか確かめる。claude は呼ばない。"""

import json
from pathlib import Path

import pytest

import review_loop as rl

ROOT = Path(__file__).resolve().parent.parent
RUNS = sorted((ROOT / "logs").glob("*-t*/rounds.json"))


def test_original_subject_fails_every_seeded_test():
    assert rl.run_tests(ROOT / "subject" / "orders.py") == 0


@pytest.mark.parametrize("rounds_json", RUNS, ids=lambda p: p.parent.name)
def test_final_code_matches_recorded_result(rounds_json):
    recorded = json.loads(rounds_json.read_text(encoding="utf-8"))["tests_passed_final"]
    assert rl.run_tests(rounds_json.parent / "final.orders.py.txt") == recorded
