# AIレビューの指摘が終わらないとき、何を数えて止めるか

不具合を 6 か所仕込んだ小さな Python モジュール(`subject/orders.py`)に、`claude -p` でレビュー → 修正を何ラウンドか回し、毎回の指摘を次の 3 つに分けて数えるスクリプトです。

- 元から有った行への新しい指摘
- 修正で入った行への指摘
- 前の回と同じ指摘の再掲

指摘の行は、各ラウンドの修正を git のコミットにして `git blame --porcelain` で 1 回目のコミットまで辿って分けます。「同じ指摘」は、辿った先が同じコミットの ±3 行以内で、カテゴリが同じものとしました。

止め時の条件は 3 つを実際に回し(各 3 試行)、ラウンド上限は「毎回全体をレビュー」の記録を切って求めます。

| mode | 2 回目以降のレビュー | 直す指摘 | 止める条件 |
|---|---|---|---|
| `full` | 毎回全体 | 全部 | 指摘が 0 件、または `--max-rounds` |
| `verify` | 前の回の指摘が直ったかだけ | 直っていないもの | 全部直った、または `--max-rounds` |
| `severity` | 毎回全体 | high / medium だけ | high / medium が 0 件、または `--max-rounds` |

## 前提

- Python 3.11.18(`target-version = "py311"`)
- git 2.43.0(`git blame --porcelain` を使う)
- Claude Code 2.1.331(`claude -p --output-format json --tools ""` を使う)。ログイン済みであること。`review_loop.py` を回すと API の利用料がかかる(この README の 9 試行で合計 約 1.25 USD)
- pytest 8.3.3(`requirements.txt`)

`claude` が無くても、`summarize.py` と `pytest` は `logs/` に残した実行結果だけで動きます。

## 動かし方

```bash
git clone https://github.com/liatris000/liatris-20261210-ai-review-convergence.git
cd liatris-20261210-ai-review-convergence
python3 -m pip install -r requirements.txt

# 記録済みの結果を集計する(claude は呼ばない)
python3 summarize.py

# 分類ロジックと、記録した最終コードのテスト(claude は呼ばない)
python3 -m pytest -q

# 自分で回す(claude -p を呼ぶ。logs/<mode>-t<trial>/ を上書きする)
python3 review_loop.py --mode full --max-rounds 5 --trial 1
python3 review_loop.py --mode verify --max-rounds 5 --trial 1
python3 review_loop.py --mode severity --max-rounds 5 --trial 1
python3 summarize.py
```

`logs/<mode>-t<trial>/` には、ラウンドごとのコード(`roundN.orders.py.txt`)、レビューと修正の生の応答(`roundN.review.raw.txt` / `roundN.verify.raw.txt` / `roundN.fix.raw.txt`)、集計元の `rounds.json` が入ります。

## 期待される出力

`python3 summarize.py` の末尾(記録済みの 9 試行):

```
| 止め時の条件 | 試行 | 修正を回した回数 | 仕込んだ不具合に付いた指摘 | 終了時のテスト | 指摘の延べ数 | 費用 (USD) |
|---|---|---|---|---|---|---|
| 毎回全体をレビュー | 1 | 1 | 6/6 | 6/6 | 9 | 0.1034 |
| 毎回全体をレビュー | 2 | 5 | 6/6 | 6/6 | 25 | 0.4063 |
| 毎回全体をレビュー | 3 | 1 | 6/6 | 6/6 | 10 | 0.0832 |
| 前回指摘の確認のみ | 1 | 1 | 6/6 | 6/6 | 9 | 0.0925 |
| 前回指摘の確認のみ | 2 | 1 | 6/6 | 6/6 | 9 | 0.0778 |
| 前回指摘の確認のみ | 3 | 1 | 6/6 | 6/6 | 9 | 0.0777 |
| high / medium だけ直す | 1 | 3 | 6/6 | 6/6 | 20 | 0.2011 |
| high / medium だけ直す | 2 | 2 | 6/6 | 5/6 | 16 | 0.1163 |
| high / medium だけ直す | 3 | 1 | 6/6 | 6/6 | 18 | 0.0871 |
| ラウンド上限 1 回(full の記録を切る) | 1 | 1 | 6/6 | 6/6 | 9 | 0.0768 |
| ラウンド上限 1 回(full の記録を切る) | 2 | 1 | 6/6 | 6/6 | 10 | 0.0524 |
| ラウンド上限 1 回(full の記録を切る) | 3 | 1 | 6/6 | 6/6 | 10 | 0.0547 |
```

`python3 -m pytest -q`:

```
..............ssssss                                                     [100%]
14 passed, 6 skipped
```

skip の 6 件は `tests/test_seeded.py`(仕込みの不具合のテスト)です。元のコードでは全部落ちるのが正しいので、`SUBJECT` 環境変数でファイルを指定したときだけ回ります。

`review_loop.py --mode full` の出力(試行 2):

```
[full-t2] round 1: findings=10 original_line=10 fix_line=0 repeat=0 tests_passed_before=0/6
[full-t2] round 2: findings=3 original_line=1 fix_line=2 repeat=0 tests_passed_before=6/6
[full-t2] round 3: findings=1 original_line=1 fix_line=0 repeat=0 tests_passed_before=6/6
[full-t2] round 4: findings=2 original_line=0 fix_line=2 repeat=0 tests_passed_before=6/6
[full-t2] round 5: findings=9 original_line=1 fix_line=7 repeat=1 tests_passed_before=6/6
[full-t2] done: rounds=5 tests_passed_final=6/6 cost=$0.4063
```

モデルの出力は毎回変わるので、自分で回した結果は上と一致しません。

## 確かめていない範囲

- 題材は 50 行ほどの 1 ファイルだけ。大きなコードや複数ファイルの差分では試していない
- 各条件 3 試行だけ。ばらつきの幅は分からない
- レビュアーと修正役は `claude -p` の既定のモデルだけ。GitHub Copilot・Cursor Bugbot・CodeRabbit などのレビューサービスでは試していない
- 「同じ指摘」の判定は blame の行とカテゴリだけで見ている。修正で行が書き換わると、同じ趣旨の指摘でも「修正で入った行」に数える(例: `severity-t1` の 1 回目の low「page >= 1 の確認が無い」と、2 回目の medium の同じ趣旨の指摘)
- 「仕込んだ不具合に付いた指摘」は、指摘の行がその関数の範囲に入っているかで判定している。指摘の中身が不具合そのものを言い当てているかは見ていない。修正できたかはテスト(`tests/test_seeded.py`)で見ている

## 記事

https://zenn.dev/liatris/articles/20261210-ai-review-convergence

## License

MIT
