# 町の資料の検索（日野町データポータル・非公式）

日野町のサイトに公開されている資料（計画、予算・決算、財政、広報ひの、審議会、記者会見など）の本文から、言葉で資料とページを探すページ。日野町データポータル（https://kken78.github.io/hino-portal/ ）の一つ。

- 結果は、資料ごとに、言葉が見つかったページと前後の文を出す。ページの番号を押すと、町のサイトの PDF がそのページで開く。
- 会議録は、会議録検索（https://kken78.github.io/hino-council-search/ ）で探す。
- 本文の文字は、原典の PDF から機械で取り出したもの。読み取りの誤りや欠けがあることがある。内容は原典で確かめる。画像だけの資料は、言葉では探せない。

## 材料

| リポジトリ | 使うもの |
|---|---|
| kken78/hino-town-docs | 台帳 `data/sources.tsv`、原典の文字 `data/text/` |
| kken78/shiga-hino-plans | 計画の一覧 `data/manifest.json`、原典の台帳 `data/sources_index.tsv`、原典の文字 `data/text/` |

材料の版は `inputs.lock.json` で決める（リポジトリごとに commit を1つ）。

## ファイル

| ファイル | 中身 |
|---|---|
| index.html | 検索のページ。`data/` を `<script>` で読む（ファイルとして開いても動く） |
| data/index.js | 資料の一覧（分類・年度・日付・題・URL・形式・大きさ・ページ数）と、本文のファイルの一覧。道具が作る |
| data/t-<名前>.js | ページごとの本文の文字（探すための形。DESIGN.md ADR-2）。計画と、年ごとに分け、1.5MB を目安にさらに分ける。道具が作る |
| inputs.lock.json | 材料のリポジトリと commit |
| tools/build_data.py | 材料から `data/` を作る道具 |

## 作り直し方

材料のリポジトリ（hino-town-docs と shiga-hino-plans）を、このリポジトリと同じフォルダに置き、`inputs.lock.json` の commit を取得しておく（`git fetch`）。道具は、作業ツリーでなく、その commit の中身を git から読む。

```bash
python3 tools/build_data.py            # 材料が隣のフォルダにあるとき
python3 tools/build_data.py --src <材料を並べたフォルダ>
```

台帳のページ数と原典の文字を改ページで分けた数が合わないなど、決まりに合わないものが1つでもあれば、`data/` は書き出されず、終了コード 1 で止まる。材料の版を上げるときは、`inputs.lock.json` の commit を直して道具を実行し、`inputs.lock.json` と `data/` を同じコミットに入れる。

PR と main への push のたびに、GitHub Actions（`.github/workflows/check.yml`）が lock の commit の材料で道具を実行し、`data/` がコミットされたものと一致するかを確かめる。あわせて、hino-portal の共通の部品の検査（`shared/check.py`・`shared/check_mobile.mjs`）を走らせる。

## 町のサイトから外された資料

町のサイトから外された資料は、本文を検索の対象から外し、題と「町のサイトから外された資料」と確認した日だけを出す。外された理由を確かめ、新しい版への差し替えやページの整理によるものと分かったときは、検索の対象に戻す。戻した資料のリンク先は、Webアーカイブの保存版があればそれにし、無ければリンクを付けない（DESIGN.md ADR-4）。

## ライセンス

コードは MIT License（[LICENSE](LICENSE)）。検索のデータの構造（列の作り方、分類の名前など）は CC BY 4.0（表示は https://github.com/kken78/hino-shiryo ）。資料の題と本文の文字は、日野町など各資料の発行者の著作物で、このリポジトリのライセンスの対象外。
