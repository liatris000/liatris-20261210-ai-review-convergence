"""仕込んだ不具合ごとのテスト。元の subject/orders.py では全部落ちる。

SUBJECT 環境変数で検査するファイルを指定する(review_loop.py が各ラウンドのコードに対して回す)。
指定が無いときは全部 skip する。元のコードでは全部落ちるのが正しいので、通常の pytest では回さない。
"""

import importlib.machinery
import importlib.util
import os
from pathlib import Path

import pytest

SUBJECT = os.environ.get("SUBJECT")
pytestmark = pytest.mark.skipif(not SUBJECT, reason="SUBJECT が未指定(review_loop.py から呼ばれたときだけ回す)")


def load():
    loader = importlib.machinery.SourceFileLoader("orders_under_test", str(Path(SUBJECT)))
    spec = importlib.util.spec_from_loader("orders_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_negative_qty():
    with pytest.raises(ValueError):
        load().parse_quantity("-3")


def test_discount_scale():
    assert load().apply_discount(200, 10) == pytest.approx(180)


def test_page_offset():
    assert load().paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_mutable_default():
    mod = load()
    mod.merge_tags(["a"])
    assert mod.merge_tags(["b"]) == ["b"]


def test_swallow_errors(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(Exception):  # noqa: B017  握りつぶさずに何か送出すればよい
        load().load_config(broken)


def test_empty_average():
    mod = load()
    try:
        result = mod.average_price([])
    except ValueError:
        return
    assert result == 0
