"""data/ から dist/ に静的サイトを書き出す。"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .articles import ARTICLE_DIR, article_for, md_to_html, text_to_html, toc_to_html
from .links import buy_links
from .model import (AUDIENCES, FORM_SLUGS, FORMS, GENRE_GROUPS, GENRES, JST, Book,
                    genre_name, genre_slug, today_jst)
from .openbd import FUTURE_DAYS, PAST_DAYS

ROOT = Path(__file__).resolve().parent.parent
PER_PAGE = 48
MIN_AUTHOR_BOOKS = 2   # これ未満しか無い著者はページを作らない（1 冊だけのページが増えすぎるため）
MONTHS_KEPT = 8


def load_books(data_dir: Path) -> list[Book]:
    out = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if raw.get("title") and raw.get("isbn"):
            out.append(Book.from_raw(raw))
    return out


def load_config(root: Path = ROOT) -> tuple[dict, dict]:
    site = json.loads((root / "config" / "site.json").read_text(encoding="utf-8"))
    aff = json.loads((root / "config" / "affiliate.json").read_text(encoding="utf-8"))
    return site, aff


def fmt_date(d: date | None) -> str:
    if not d:
        return "発売日未定"
    return f"{d.year}年{d.month}月{d.day}日"


def fmt_md(d: date | None) -> str:
    return f"{d.month}/{d.day}" if d else "未定"


def yen(n: int | None) -> str:
    return f"{int(n):,}円" if n else "価格未定"


class Builder:
    def __init__(self, out_dir: Path, site_url: str, today: date | None = None, data_dir: Path | None = None,
                 article_dir: Path = ARTICLE_DIR, root: Path = ROOT):
        self.out = out_dir
        self.site_url = site_url.rstrip("/")
        self.today = today or today_jst()
        self.data_dir = data_dir or root / "data" / "books"
        self.article_dir = article_dir
        self.root = root
        self.site, self.aff = load_config(root)
        self.env = Environment(loader=FileSystemLoader(root / "templates"),
                               autoescape=select_autoescape(["html", "xml"]))
        self.env.filters["yen"] = yen
        self.env.filters["date"] = fmt_date
        self.env.filters["md"] = fmt_md
        self.env.globals.update(url=self.url, site=self.site, ads=self.aff, today=self.today,
                                genre_name=genre_name, genre_slug=genre_slug,
                                AUDIENCES=AUDIENCES, FORMS=FORMS)
        self.sitemap: list[tuple[str, date | None]] = []

    # ---- 部品 ----
    def url(self, path: str = "") -> str:
        return f"{self.site_url}/{path.lstrip('/')}"

    def write(self, path: str, text: str) -> None:
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def render(self, template: str, path: str, *, noindex: bool = False, lastmod: date | None = None, **ctx) -> None:
        canonical = self.url(path.replace("index.html", ""))
        html = self.env.get_template(template).render(canonical=canonical, noindex=noindex, **ctx)
        self.write(path, html)
        if not noindex:
            self.sitemap.append((canonical, lastmod))

    def paginate(self, base: str, items: list[Book], *, title: str, description: str,
                 noindex: bool = False, template: str = "list.html", **ctx) -> None:
        pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        for i in range(pages):
            chunk = items[i * PER_PAGE:(i + 1) * PER_PAGE]
            path = f"{base}index.html" if i == 0 else f"{base}page/{i + 1}/index.html"
            self.render(template, path, noindex=noindex,
                        title=title if i == 0 else f"{title}（{i + 1}ページ目）",
                        description=description, items=chunk, page=i + 1, pages=pages, base=base,
                        count=len(items), **ctx)

    # ---- 本体 ----
    def build(self) -> int:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copytree(self.root / "static", self.out / "static")
        books = load_books(self.data_dir)
        today = self.today

        # 窓（直近 PAST_DAYS 日〜これから FUTURE_DAYS 日）に入る本だけを一覧に出す。
        # 窓から外れた本のページは残す（リンク切れを作らないため）が、一覧と sitemap からは消える。
        start = today - timedelta(days=PAST_DAYS)
        end = today + timedelta(days=FUTURE_DAYS)
        live = [b for b in books if b.pubdate and start <= b.pubdate <= end]
        live_set = {b.isbn for b in live}
        dropped = [b for b in books if b.isbn not in live_set]

        by_pub_desc = sorted(live, key=lambda b: (b.pubdate or date.min), reverse=True)
        released = [b for b in by_pub_desc if b.pubdate <= today]
        upcoming = sorted([b for b in live if b.pubdate > today], key=lambda b: b.pubdate)

        # 今週（月〜日）と来週
        monday = today - timedelta(days=today.weekday())
        this_week = sorted([b for b in live if monday <= b.pubdate < monday + timedelta(days=7)],
                           key=lambda b: b.pubdate, reverse=True)
        next_week = sorted([b for b in live if monday + timedelta(days=7) <= b.pubdate < monday + timedelta(days=14)],
                           key=lambda b: b.pubdate)

        by_genre: dict[str, list[Book]] = defaultdict(list)
        by_form: dict[str, list[Book]] = defaultdict(list)
        by_publisher: dict[str, list[Book]] = defaultdict(list)
        by_author: dict[str, list[Book]] = defaultdict(list)
        by_month: dict[str, list[Book]] = defaultdict(list)
        for b in live:
            if b.genre_code in GENRES:
                by_genre[b.genre_code].append(b)
            if b.form_code in FORMS:
                by_form[b.form_code].append(b)
            by_publisher[b.publisher].append(b)
            for name in b.authors:
                by_author[name].append(b)
            key = b.month_key()
            if key:
                by_month[key].append(b)

        def newest(lst: list[Book]) -> list[Book]:
            return sorted(lst, key=lambda b: (b.pubdate or date.min), reverse=True)

        genre_index = sorted(((c, GENRES[c][0], GENRES[c][1], len(v)) for c, v in by_genre.items()),
                             key=lambda t: -t[3])
        form_index = sorted(((c, FORMS[c], FORM_SLUGS[c], len(v)) for c, v in by_form.items()), key=lambda t: -t[3])
        pub_index = sorted(((p, v[0].publisher_slug, len(v)) for p, v in by_publisher.items()),
                           key=lambda t: (-t[2], t[0]))
        author_index = sorted(((a, v[0].author_slug(a), len(v)) for a, v in by_author.items() if len(v) >= MIN_AUTHOR_BOOKS),
                              key=lambda t: (-t[2], t[0]))
        months = sorted(by_month.keys(), reverse=True)[:MONTHS_KEPT]

        group_index = []
        for name, codes in GENRE_GROUPS:
            rows = [(c, GENRES[c][0], GENRES[c][1], len(by_genre.get(c, []))) for c in codes if by_genre.get(c)]
            if rows:
                group_index.append((name, sorted(rows, key=lambda t: -t[3])))

        self.env.globals.update(
            genre_index=genre_index, form_index=form_index, group_index=group_index,
            pub_index=pub_index[:40], month_index=[(m, len(by_month[m])) for m in months],
            author_pages={a for a, _, _ in author_index}, publisher_pages=set(by_publisher),
            sidebar_soon=upcoming[:6], sidebar_new=released[:6],
            stats=dict(total=len(live), released=len(released), upcoming=len(upcoming),
                       this_week=len(this_week), next_week=len(next_week),
                       publishers=len(by_publisher), authors=len(by_author), archived=len(dropped),
                       updated=max((b.fetched_at for b in books if b.fetched_at), default=today)))

        # ---- 本ごとのページ ----
        for b in books:
            same = [r for r in newest(by_genre.get(b.genre_code, [])) if r.isbn != b.isbn][:8]
            taken = {r.isbn for r in same} | {b.isbn}
            if len(same) < 8:
                same += [r for r in newest(by_publisher.get(b.publisher, []))
                         if r.isbn not in taken][:8 - len(same)]
            art = article_for(b.isbn, self.article_dir)
            self.render("book.html", f"{b.path}index.html", b=b, art=art, same=same,
                        desc_html=text_to_html(b.description), toc_html=toc_to_html(b.toc),
                        links=buy_links(b.isbn, b.full_title, self.aff),
                        noindex=b.isbn not in live_set, lastmod=b.fetched_at)

        # ---- 一覧 ----
        self.render("index.html", "index.html", this_week=this_week[:12], next_week=next_week[:12],
                    upcoming=upcoming[:12], released=released[:12],
                    covers=[b for b in by_pub_desc if b.cover][:18])
        self.paginate("new/", by_pub_desc, title="新刊一覧（発売日順）",
                      description=f"直近{PAST_DAYS}日に発売された本とこれから{FUTURE_DAYS}日以内に発売される本を、発売日の新しい順に並べています。")
        self.paginate("this-week/", this_week, title="今週の新刊",
                      description=f"{monday.month}月{monday.day}日からの 1 週間に発売された本のまとめです。毎朝自動で更新しています。")
        self.paginate("next-week/", next_week, title="来週発売の本",
                      description="来週発売される本の一覧です。予約や取り置きの参考にどうぞ。")
        self.paginate("upcoming/", upcoming, title="発売予定の本",
                      description=f"これから{FUTURE_DAYS}日以内に発売予定の本を、発売日が近い順に並べています。")
        for code, name, slug, _ in genre_index:
            self.paginate(f"g/{slug}/", newest(by_genre[code]), title=f"{name}の新刊",
                          description=f"Cコードの内容分類が「{name}」の新刊・発売予定の本の一覧です。",
                          kind="genre", key=name)
        for code, name, slug, _ in form_index:
            self.paginate(f"form/{slug}/", newest(by_form[code]), title=f"{name}の新刊",
                          description=f"{name}として登録されている新刊・発売予定の本の一覧です。",
                          kind="form", key=name)
        for name, slug, _ in pub_index:
            self.paginate(f"p/{slug}/", newest(by_publisher[name]), title=f"{name}の新刊",
                          description=f"{name}が刊行した直近の本と、これから発売される本の一覧です。",
                          kind="publisher", key=name)
        for name, slug, _ in author_index:
            self.paginate(f"a/{slug}/", newest(by_author[name]), title=f"{name}の新刊",
                          description=f"{name}が関わった直近の本と、これから発売される本の一覧です。",
                          kind="author", key=name)
        for m in months:
            y, mo = m.split("-")
            self.paginate(f"monthly/{m}/", newest(by_month[m]), title=f"{y}年{int(mo)}月の新刊まとめ",
                          description=f"{y}年{int(mo)}月に発売された（発売される）本 {len(by_month[m])} 冊のまとめです。")

        self.render("genres.html", "g/index.html", title="ジャンル別の新刊",
                    description="Cコード（日本図書コード）の内容分類ごとに新刊を並べています。")
        self.render("table.html", "form/index.html", title="形態別の新刊（文庫・新書・コミックなど）",
                    description="文庫・新書・コミック・絵本など、本の形態ごとの新刊一覧です。",
                    rows=[(n, f"form/{s}/", c) for _, n, s, c in form_index], head="形態")
        self.render("table.html", "p/index.html", title="出版社別の新刊",
                    description="出版社ごとの新刊・発売予定の冊数です。多い順に並べています。",
                    rows=[(n, f"p/{s}/", c) for n, s, c in pub_index], head="出版社")
        self.render("table.html", "a/index.html", title="著者別の新刊",
                    description=f"直近の新刊を{MIN_AUTHOR_BOOKS}冊以上出している著者の一覧です。",
                    rows=[(n, f"a/{s}/", c) for n, s, c in author_index], head="著者")
        self.render("table.html", "monthly/index.html", title="月別の新刊まとめ",
                    description="発売月ごとの新刊まとめです。",
                    rows=[(f"{m[:4]}年{int(m[5:])}月", f"monthly/{m}/", len(by_month[m])) for m in months],
                    head="発売月")
        self.render("search.html", "search/index.html", title="新刊を探す",
                    description="書名・著者・出版社・ジャンル・発売日から、いま出たばかりの本とこれから出る本を絞り込めます。")

        # ---- 固定ページ ----
        for name in ("about", "privacy"):
            text = (self.root / "content" / f"{name}.md").read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            body = md_to_html("\n".join(text.splitlines()[1:]))
            self.render("page.html", f"{name}/index.html", title=title, description=title, body=body)
        self.write("404.html", self.env.get_template("404.html").render(canonical=self.url("404.html"), noindex=True))

        # ---- 機械向け ----
        self.write("search.json", self.search_json(live))
        self.write_sitemap()
        self.write_feed(by_pub_desc[:40])
        self.write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {self.url('sitemap.xml')}\n")
        self.write(".nojekyll", "")
        return len(books)

    def search_json(self, books: list[Book]) -> str:
        rows = []
        for b in books:
            rows.append({"i": b.isbn, "t": b.full_title, "a": b.authors[:4], "p": b.publisher,
                         "d": b.pubdate.strftime("%Y-%m-%d") if b.pubdate else "",
                         "g": b.genre, "f": b.form, "c": 1 if b.cover else 0, "y": b.price})
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))

    def write_sitemap(self) -> None:
        rows = []
        for loc, lastmod in self.sitemap:
            lm = f"<lastmod>{lastmod.strftime('%Y-%m-%d')}</lastmod>" if lastmod else ""
            rows.append(f"<url><loc>{escape(loc)}</loc>{lm}</url>")
        self.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                   + "\n".join(rows) + "\n</urlset>\n")

    def write_feed(self, books: list[Book]) -> None:
        entries = []
        for b in books:
            pub = datetime.combine(b.pubdate or self.today, datetime.min.time(), JST)
            link = escape(self.url(b.path))
            entries.append(f"<item><title>{escape(b.full_title)}</title><link>{link}</link><guid>{link}</guid>"
                           f"<pubDate>{pub.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
                           f"<description>{escape(b.summary_text(200))}</description></item>")
        self.write("feed.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
                   f"<title>{escape(self.site['name'])}</title><link>{escape(self.url())}</link>"
                   f"<description>{escape(self.site['description'])}</description>\n"
                   + "\n".join(entries) + "\n</channel></rss>\n")
