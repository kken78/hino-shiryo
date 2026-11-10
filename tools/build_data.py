#!/usr/bin/env python3
"""build_data.py — 材料の台帳と原典の文字から、検索のデータ（data/）を作る。

  python3 tools/build_data.py [--src <材料のリポジトリを並べたフォルダ>]

- 材料は inputs.lock.json の commit から読む（git の中身を読むので、材料のフォルダの作業ツリーの状態にはよらない）。
  --src の既定は、このリポジトリの1つ上のフォルダ（~/GitHub のように並べて置く）。
- 書き出すもの：data/index.js（資料の一覧と、分けたファイルの一覧）と data/t-<名前>.js（ページの文字）。
- 検算：台帳のページ数と、原典の文字を改ページで分けた数が合わないなど、決まりに合わないものが1つでもあれば、
  何も書き出さずに終了コード 1 で止まる。
- 標準ライブラリだけを使う。
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data")
SHARD_MAX = 1_500_000  # 1つのファイルの文字の目安（バイト）。計画と年で分けたうえで、これを超えたら分ける

# hino-town-docs の分類（DOCS_SCHEMA.md §3）の、画面での名前と並び
CATS = [
    ("keikaku", "計画"),
    ("yosan", "予算"),
    ("kessan", "決算"),
    ("zaisei", "財政"),
    ("kofukin", "交付金"),
    ("hyoka", "評価と検証"),
    ("jigyo", "施設・事業の構想と計画"),
    ("shingi", "審議会・会議"),
    ("chiiki", "地域・自治会・住民参加"),
    ("bosai", "防災"),
    ("tokei", "統計と一覧"),
    ("kaiken", "記者会見"),
    ("koho", "広報ひの"),
]
CAT_NAME = dict(CATS)
ARCHIVE = "Webアーカイブ"  # 計画の原典の台帳の note にこの字があれば、掲載が終わり、まだ判断の付いていない資料とみなす（DESIGN.md ADR-4）

errors = []


def err(msg):
    errors.append(msg)


class Repo:
    def __init__(self, path, commit):
        self.path, self.commit = path, commit
        if not os.path.isdir(os.path.join(path, ".git")):
            sys.exit(f"材料のリポジトリが無い: {path}")
        r = subprocess.run(["git", "-C", path, "cat-file", "-e", commit + "^{commit}"], capture_output=True)
        if r.returncode:
            sys.exit(f"{path} に commit {commit} が無い（git fetch してから実行する）")

    def ls(self, prefix):
        out = subprocess.run(["git", "-C", self.path, "ls-tree", "-r", "--name-only", self.commit, prefix],
                             capture_output=True, text=True, check=True).stdout
        return [x for x in out.split("\n") if x]

    def read_many(self, paths):
        """git cat-file --batch でまとめて読む。{path: str}"""
        if not paths:
            return {}
        p = subprocess.Popen(["git", "-C", self.path, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        data, _ = p.communicate("".join(f"{self.commit}:{x}\n" for x in paths).encode())
        res, pos = {}, 0
        for x in paths:
            nl = data.index(b"\n", pos)
            head = data[pos:nl].split()
            if head[-1] == b"missing":
                pos = nl + 1
                continue
            size = int(head[2])
            res[x] = data[nl + 1:nl + 1 + size].decode("utf-8")
            pos = nl + 1 + size + 1
        return res

    def read(self, path):
        return self.read_many([path]).get(path)


def norm(s):
    """探すための形：NFKC にそろえ、空白と改行を除く（DESIGN.md ADR-2）"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def pdf_pages(text, want, name):
    pages = text.split("\f")
    if len(pages) == want + 1 and pages[-1].strip() == "":
        pages = pages[:-1]
    if len(pages) != want:
        err(f"{name}: 改ページで分けた数 {len(pages)} が台帳のページ数 {want} と合わない")
    return [norm(p) for p in pages]


def town_docs(repo):
    rows = list(csv.DictReader(io.StringIO(repo.read("data/sources.tsv")), delimiter="\t"))
    files = set(repo.ls("data/text/"))
    want = []
    for r in rows:
        if r["format"] in ("pdf", "html"):
            want.append(f"data/text/{r['id']}.txt")
        elif r["format"] == "xlsx":
            want += [f for f in files if f.startswith(f"data/text/{r['id']}/")]
    texts = repo.read_many([w for w in want if w in files])
    docs = []
    for r in rows:
        if r["category"] not in CAT_NAME:
            err(f"{r['id']}: 分類 {r['category']} の画面の名前が決まっていない（tools/build_data.py の CATS）")
            continue
        d = {"id": r["id"], "cc": r["category"], "y": r["fiscal_year"], "d": r["date"], "t": r["title"],
             "u": r["url"], "fmt": r["format"], "b": int(r["bytes"] or 0), "pages": [], "labels": None,
             "sha": r["sha256"]}
        m = re.fullmatch(r"koho-no(\d+)-\d+", r["id"])
        if m:
            d["no"] = int(m.group(1))   # 広報ひのの号数（台帳の id による。DESIGN.md ADR-7）
        if "removed" not in r:
            err("hino-town-docs の台帳に removed の列が無い（DOCS_SCHEMA.md §4 の前の版。inputs.lock.json を上げる）")
            return []
        if r["removed"] and r["removed_judgment"] != "replaced":
            d["k"] = "gone"                     # 掲載が終わり、withheld か、まだ判断していない（ADR-4）
        elif r["check"] == "image" or r["text_method"] == "none":
            d["k"] = "image"
        else:
            d["k"] = "text"
        if d["k"] == "text":
            if r["format"] == "pdf":
                t = texts.get(f"data/text/{r['id']}.txt")
                if t is None:
                    err(f"{r['id']}: 原典の文字が無い")
                else:
                    d["pages"] = pdf_pages(t, int(r["pages"] or 0), r["id"])
            elif r["format"] == "html":
                t = texts.get(f"data/text/{r['id']}.txt")
                if t is None:
                    err(f"{r['id']}: 原典の文字が無い")
                else:
                    d["pages"] = [norm(t)]
                    d["labels"] = ["ページの本文"]
            elif r["format"] == "xlsx":
                sheets_tsv = texts.get(f"data/text/{r['id']}/sheets.tsv")
                if sheets_tsv is None:
                    err(f"{r['id']}: シートの一覧が無い")
                else:
                    labels, pages = [], []
                    for s in csv.DictReader(io.StringIO(sheets_tsv), delimiter="\t"):
                        parts = [texts.get(f"data/text/{r['id']}/{s['順']}.tsv", ""),
                                 texts.get(f"data/text/{r['id']}/{s['順']}-zukei.tsv", "")]
                        if f"data/text/{r['id']}/{s['順']}.tsv" not in texts:
                            err(f"{r['id']}: シート {s['順']} の文字が無い")
                        labels.append(f"シート「{s['シートの名前']}」")
                        pages.append(norm("\n".join(parts)))
                    d["pages"], d["labels"] = pages, labels
        if r["removed"] and d["k"] != "gone":
            d["r"] = r["removed"]               # replaced：本文を探し、リンクは保存版（空なら無し）
            d["u"] = r["archive_url"]
        docs.append(d)
    return docs


def plan_docs(repo, seen):
    """計画の原典。hino-town-docs の台帳にも同じ資料（url か sha256 が同じ）があるものは、そちらで載せるので飛ばす。"""
    man = {p["id"]: p for p in json.loads(repo.read("data/manifest.json"))["plans"]}
    rows = list(csv.DictReader(io.StringIO(repo.read("data/sources_index.tsv")), delimiter="\t"))
    rows = [r for r in rows if r["file"] and r["url"] not in seen and r["sha256"] not in seen]
    paths = [f"data/text/{r['id']}/{r['file'].rsplit('.', 1)[0]}.txt" for r in rows]
    texts = repo.read_many(paths)
    docs = []
    for r, p in zip(rows, paths):
        if r["id"] not in man:
            err(f"{r['id']}/{r['file']}: 計画の一覧（manifest）に無い計画")
            continue
        label = re.sub(r"\s*サイズ[：:].*$", "", r["label"]).strip()
        label = re.sub(r"\s*[（(]PDF(形式)?[、,].*?[)）]\s*$", "", label, flags=re.I).strip()
        label = re.sub(r"\.pdf$", "", label, flags=re.I).strip()
        d = {"id": f"{r['id']}/{r['file']}", "cc": "keikaku", "y": "", "d": "", "t": man[r["id"]]["name"],
             "sub": label, "u": r["url"], "fmt": "pdf", "b": int(r["bytes"] or 0), "pages": [], "labels": None}
        if ARCHIVE in r["note"]:
            d["k"] = "gone"
        elif r["text_chars"] in ("", "0"):
            d["k"] = "image"
        else:
            d["k"] = "text"
            if p not in texts:
                err(f"{d['id']}: 原典の文字が無い")
            else:
                d["pages"] = pdf_pages(texts[p], int(r["pages"] or 0), d["id"])
        docs.append(d)
    return docs


def main(argv):
    src = os.path.dirname(ROOT)
    if "--src" in argv:
        src = os.path.abspath(argv[argv.index("--src") + 1])
    lock = json.load(open(os.path.join(ROOT, "inputs.lock.json"), encoding="utf-8"))
    commits = {i["repo"]: i["commit"] for i in lock["inputs"]}
    repos = {k: Repo(os.path.join(src, k.split("/")[1]), v) for k, v in commits.items()}
    tdocs = town_docs(repos["kken78/hino-town-docs"])
    seen = {d["u"] for d in tdocs} | {d["sha"] for d in tdocs}
    docs = plan_docs(repos["kken78/shiga-hino-plans"], seen) + tdocs

    # 並び：分類の順、その中は新しい順（年度・日付の降順）、同じなら id の順
    order = {c: i for i, (c, _) in enumerate(CATS)}
    docs.sort(key=lambda d: (order[d["cc"]], [-ord(ch) for ch in (d["d"] or d["y"])], d["id"]))

    # 文字の無い資料の文字は持たない。掲載が終わり、本文を使わない資料（gone）は本文を持たない（ADR-4）
    for d in docs:
        if d["k"] != "text":
            d["pages"] = []
        elif not any(d["pages"]):
            err(f"{d['id']}: 文字があるはずの資料の文字が空")

    # ファイルに分ける：計画と、そのほかは年（日付か年度の上4桁）ごと。大きければさらに分ける
    buckets = {}
    for i, d in enumerate(docs):
        if d["pages"]:
            k = ("keikaku" if d["cc"] == "keikaku" else "y", (d["d"] or d["y"])[:4])
            buckets.setdefault(k, []).append(i)
    shards = []
    for k, idx in buckets.items():
        cur = None
        for i in idx:
            size = sum(len(p.encode()) for p in docs[i]["pages"])
            if cur is None or (cur["docs"] and cur["size"] + size > SHARD_MAX):
                n = sum(1 for x in shards if x["key"] == k)
                cur = {"key": k, "name": (k[0] if k[0] == "keikaku" else k[1] or "x") + (f"-{n + 1}" if n else ""),
                       "docs": [], "size": 0}
                shards.append(cur)
            cur["docs"].append(i)
            cur["size"] += size
            docs[i]["s"] = cur["name"]
    # 読む順：計画を先に、そのあとは新しいものから
    shards.sort(key=lambda s: (s["key"][0] != "keikaku", [-ord(ch) for ch in s["key"][1]], s["name"]))

    if errors:
        print(f"誤り {len(errors)}件。data/ は書き出さない", file=sys.stderr)
        for e in errors[:50]:
            print("  " + e, file=sys.stderr)
        return 1

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.startswith("t-") and f.endswith(".js"):
            os.remove(os.path.join(OUT, f))
    meta = []
    for d in docs:
        m = {"c": d["cc"], "t": d["t"], "u": d["u"], "f": d["fmt"], "b": d["b"], "k": d["k"]}
        for a in ("sub", "y", "d", "r", "no"):
            if d.get(a):
                m[a] = d[a]
        if d["k"] == "text":
            m["n"] = len(d["pages"])
            m["s"] = d["s"]
        if d["labels"]:
            m["l"] = d["labels"]
        meta.append(m)
    index = {
        "inputs": {k.split("/")[1]: v for k, v in commits.items()},
        "cats": [[c, n] for c, n in CATS],
        "docs": meta,
        "shards": [s["name"] for s in shards],
    }
    with open(os.path.join(OUT, "index.js"), "w", encoding="utf-8") as f:
        f.write("// tools/build_data.py が作る。直接編集しない。\n")
        f.write("window.SHIRYO=" + json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n")
    for s in shards:
        body = {str(i): docs[i]["pages"] for i in s["docs"]}
        with open(os.path.join(OUT, f"t-{s['name']}.js"), "w", encoding="utf-8") as f:
            f.write("(window.SHIRYO_T=window.SHIRYO_T||{})[" + json.dumps(s["name"]) + "]="
                    + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + ";\n")

    from collections import Counter
    kinds = Counter(d["k"] for d in docs)
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith(".js"))
    print(f"資料 {len(docs)}件（文字あり {kinds['text']}・画像だけ {kinds['image']}・掲載が終わり本文を使わない {kinds['gone']}）、"
          f"ページ {sum(len(d['pages']) for d in docs)}、ファイル {len(shards) + 1}、合わせて {total / 1e6:.1f}MB")
    for c, n in CATS:
        ds = [d for d in docs if d["cc"] == c]
        print(f"  {n}: {len(ds)}件（文字あり {sum(1 for d in ds if d['k'] == 'text')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
