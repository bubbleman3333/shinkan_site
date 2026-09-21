"""ビルドが一式のファイルを出すこと。実データではなく、ここで作る数冊分で確かめる。"""
import json
from datetime import date
from pathlib import Path

import pytest

from shinkan.articles import md_to_html, text_to_html
from shinkan.build import ROOT, Builder

TODAY = date(2026, 9, 21)

BOOKS = [
    # 発売済み・Cコードあり・書影あり・内容紹介あり
    {"isbn": "9784873119038", "title": "Real World HTTP", "subtitle": "歴史とコードに学ぶインターネットとウェブ技術",
     "series": "", "volume": "", "authors": [{"name": "渋川 よしき", "role": "著"}],
     "author_line": "渋川よしき", "publisher": "オライリー・ジャパン", "pubdate": "20260918",
     "cover": "https://cover.openbd.jp/9784873119038.jpg", "ccode": "3055",
     "description": "HTTP の歴史をたどりながら、コードを書いて動かして理解する。\n第 2 版では HTTP/3 も扱う。",
     "toc": "1章 HTTP/1.0 の世界\n2章 HTTP/1.1 のシンタックス", "price": 3600, "pages": 500,
     "_meta": {"first_seen": "20260918", "fetched_at": "20260921"}},
    # これから発売・同じ出版社
    {"isbn": "9784101010014", "title": "こころ", "subtitle": "", "series": "新潮文庫", "volume": "",
     "authors": [{"name": "夏目 漱石", "role": "著"}], "author_line": "夏目漱石",
     "publisher": "新潮社", "pubdate": "20261101", "cover": "", "ccode": "0193",
     "description": "", "toc": "", "price": 490, "pages": 320,
     "_meta": {"first_seen": "20260901", "fetched_at": "20260921"}},
    # Cコードなし・著者 2 冊目
    {"isbn": "9784003101018", "title": "坊っちゃん", "subtitle": "", "series": "", "volume": "",
     "authors": [{"name": "夏目 漱石", "role": "著"}], "author_line": "夏目漱石",
     "publisher": "岩波書店", "pubdate": "202609", "cover": "", "ccode": "",
     "description": "", "toc": "", "price": 0, "pages": 0,
     "_meta": {"first_seen": "20260901", "fetched_at": "20260921"}},
    # 窓の外（ページは作るが一覧には出さない）
    {"isbn": "9784088820545", "title": "むかしの本", "subtitle": "", "series": "", "volume": "",
     "authors": [], "author_line": "", "publisher": "集英社", "pubdate": "20200101",
     "cover": "", "ccode": "0979", "description": "", "toc": "", "price": 500, "pages": 200,
     "_meta": {"first_seen": "20200101", "fetched_at": "20260921"}},
]


@pytest.fixture
def site(tmp_path: Path) -> Path:
    data = tmp_path / "books"
    data.mkdir()
    for raw in BOOKS:
        (data / f"{raw['isbn']}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    articles = tmp_path / "articles"
    articles.mkdir()
    (articles / "9784873119038.md").write_text("# 訳者のメモ\n\n**第 2 版**です。\n\n- ひとつ\n- ふたつ\n", encoding="utf-8")
    out = tmp_path / "dist"
    n = Builder(out, "https://example.com/shinkan", today=TODAY, data_dir=data,
                article_dir=articles, root=ROOT).build()
    assert n == len(BOOKS)
    return out


def read(out: Path, path: str) -> str:
    return (out / path).read_text(encoding="utf-8")


def test_一式のファイルが出る(site: Path):
    for path in ["index.html", "404.html", "robots.txt", "sitemap.xml", "feed.xml", "search.json",
                 ".nojekyll", "static/style.css", "static/favicon.svg", "static/og.png",
                 "about/index.html", "privacy/index.html", "search/index.html",
                 "new/index.html", "this-week/index.html", "next-week/index.html", "upcoming/index.html",
                 "g/index.html", "form/index.html", "p/index.html", "a/index.html", "monthly/index.html",
                 "b/9784873119038/index.html", "b/9784101010014/index.html", "b/9784088820545/index.html",
                 "monthly/2026-09/index.html", "monthly/2026-11/index.html"]:
        assert (site / path).exists(), path


def test_ジャンルと形態と出版社と著者のページが出る(site: Path):
    assert (site / "g/electronics/index.html").exists()        # C3055 → 55 電子通信
    assert (site / "g/japanese-novel/index.html").exists()     # C0193 → 93 日本の小説・物語
    assert (site / "form/tankobon/index.html").exists()
    assert (site / "form/bunko/index.html").exists()           # C0193 の 2 桁目 = 1 文庫
    # 著者ページは 2 冊以上ある人だけ（夏目漱石は 2 冊、渋川よしきは 1 冊）
    from shinkan.model import slugify
    assert (site / f"a/{slugify('夏目 漱石')}/index.html").exists()
    assert not (site / f"a/{slugify('渋川 よしき')}/index.html").exists()


def test_本のページの中身(site: Path):
    html = read(site, "b/9784873119038/index.html")
    assert "Real World HTTP" in html
    assert "オライリー・ジャパン" in html
    assert "2026年9月18日" in html
    assert "https://www.amazon.co.jp/dp/4873119030" in html         # 購入リンク（ISBN10）
    assert "books.rakuten.co.jp" in html and "honto.jp" in html and "kinokuniya" in html
    assert "HTTP の歴史をたどりながら" in html                        # 内容紹介
    assert "出典: openBD / オライリー・ジャパン" in html              # 出典表示
    assert "1章 HTTP/1.0 の世界" in html                             # 目次
    assert "訳者のメモ" in html and "<strong>第 2 版</strong>" in html  # data/articles の差し込み
    assert '"@type":"Book"' in html and '"isbn":"9784873119038"' in html
    assert '"@type":"BreadcrumbList"' in html
    assert '<link rel="canonical" href="https://example.com/shinkan/b/9784873119038/">' in html
    assert 'property="og:image" content="https://cover.openbd.jp/9784873119038.jpg"' in html


def test_書影が無い本はogpが既定の画像になる(site: Path):
    html = read(site, "b/9784101010014/index.html")
    assert 'property="og:image" content="https://example.com/shinkan/static/og.png"' in html
    assert "書影はありません" in html


def test_窓から外れた本はページを残すが一覧と_sitemap_から消える(site: Path):
    html = read(site, "b/9784088820545/index.html")
    assert 'name="robots" content="noindex,follow"' in html
    assert "/b/9784088820545/" not in read(site, "sitemap.xml")
    assert "むかしの本" not in read(site, "new/index.html")
    assert "むかしの本" not in read(site, "search.json")
    # 窓の中の本はちゃんと sitemap に載る
    assert "/b/9784873119038/" in read(site, "sitemap.xml")


def test_今週と来週の振り分け(site: Path):
    # 2026-09-21 は月曜。9/18 は先週、11/1 は先なので「今週の新刊」は 0 冊になる
    assert "該当する本は今のところありません" in read(site, "this-week/index.html")
    assert "全 0 冊" in read(site, "next-week/index.html")
    assert "Real World HTTP" in read(site, "new/index.html")
    assert "こころ" in read(site, "upcoming/index.html")


def test_search_json(site: Path):
    rows = json.loads(read(site, "search.json"))
    by_isbn = {r["i"]: r for r in rows}
    assert len(rows) == 3   # 窓の外の 1 冊は入らない
    assert by_isbn["9784873119038"]["t"] == "Real World HTTP 歴史とコードに学ぶインターネットとウェブ技術"
    assert by_isbn["9784873119038"]["g"] == "電子通信"
    assert by_isbn["9784873119038"]["c"] == 1
    assert by_isbn["9784101010014"]["a"] == ["夏目 漱石"]


def test_sitemap_と_feed_と_robots(site: Path):
    assert "<loc>https://example.com/shinkan/</loc>" in read(site, "sitemap.xml")
    assert "Sitemap: https://example.com/shinkan/sitemap.xml" in read(site, "robots.txt")
    feed = read(site, "feed.xml")
    assert "<title>新刊ウォッチ</title>" in feed and "Real World HTTP" in feed


def test_トップに構造化データと統計が出る(site: Path):
    html = read(site, "index.html")
    assert '"@type":"WebSite"' in html and '"SearchAction"' in html
    assert "新刊ウォッチ" in html


# ---- 小さな Markdown 変換 ----

def test_md_to_html():
    html = md_to_html("# 見出し\n\n段落 **強い**\n\n- 一\n- 二\n")
    assert "<h2>見出し</h2>" in html
    assert "<strong>強い</strong>" in html
    assert "<ul><li>一</li>" in html.replace("\n", "")


def test_text_to_html_はタグをエスケープする():
    assert text_to_html("<script>x</script>") == "<p>&lt;script&gt;x&lt;/script&gt;</p>"
