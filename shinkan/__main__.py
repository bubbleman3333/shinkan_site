"""使い方:
  python -m shinkan fetch [--batch 10000] [--limit-batches N]   openBD から取り込む
  python -m shinkan build [--out dist] [--site-url URL]         サイトを生成
  python -m shinkan all                                          fetch → build
  python -m shinkan stats                                        手元のデータの様子を見る
  python -m shinkan pending [--limit N]                          記事がまだ無い本を出す
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .articles import pending
from .build import ROOT, Builder, load_books, load_config
from .model import today_jst
from .openbd import DATA, sync


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="shinkan", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--batch", type=int, default=10000, help="1 リクエストで問い合わせる ISBN 数")
    f.add_argument("--limit-batches", type=int, default=None, help="このバッチ数で打ち切る（試し用）")
    b = sub.add_parser("build")
    b.add_argument("--out", default="dist")
    b.add_argument("--site-url", default=None)
    a = sub.add_parser("all")
    a.add_argument("--out", default="dist")
    a.add_argument("--site-url", default=None)
    sub.add_parser("stats")
    q = sub.add_parser("pending")
    q.add_argument("--limit", type=int, default=50)
    args = p.parse_args(argv)

    site, _ = load_config()
    if args.cmd in ("fetch", "all"):
        sync(data_dir=DATA, batch=getattr(args, "batch", 10000),
             limit_batches=getattr(args, "limit_batches", None))
    if args.cmd in ("build", "all"):
        n = Builder(Path(args.out), args.site_url or site["site_url"]).build()
        print(f"{n} 冊から {args.out}/ を生成した")
    if args.cmd == "stats":
        books = load_books(ROOT / "data" / "books")
        today = today_jst()
        genres = Counter(b.genre or "（Cコードなし）" for b in books)
        pubs = Counter(b.publisher for b in books)
        print(f"保存している本: {len(books)} 冊")
        print(f"  発売済み: {sum(1 for b in books if b.pubdate and b.pubdate <= today)} 冊")
        print(f"  発売予定: {sum(1 for b in books if b.pubdate and b.pubdate > today)} 冊")
        print(f"  書影あり: {sum(1 for b in books if b.cover)} 冊 / 内容紹介あり: {sum(1 for b in books if b.description)} 冊")
        print(f"  出版社: {len(pubs)} 社")
        print("  ジャンル上位: " + "、".join(f"{k}({v})" for k, v in genres.most_common(10)))
    if args.cmd == "pending":
        books = load_books(ROOT / "data" / "books")
        for b in pending(books, args.limit):
            print(f"{b.isbn}\t{b.pubdate}\t{b.publisher}\t{b.full_title}")


if __name__ == "__main__":
    main()
