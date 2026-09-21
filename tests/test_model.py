"""ISBN の変換、Cコードの読み方、発売日の範囲判定。"""
from datetime import date

import pytest

from shinkan.links import buy_links
from shinkan.model import (Book, in_window, isbn13_to_isbn10, normalize_person, parse_pubdate,
                           slugify, valid_isbn13)


# ---------------------------------------------------------------- ISBN

@pytest.mark.parametrize("isbn13, isbn10", [
    ("9784873119038", "4873119030"),   # Real World HTTP（オライリー）
    ("9784101010014", "4101010013"),   # 新潮文庫
    ("9784003101094", "400310109X"),   # チェックディジットが X になる例
    ("9784088820545", "4088820541"),
])
def test_isbn13_to_isbn10(isbn13, isbn10):
    assert isbn13_to_isbn10(isbn13) == isbn10


def test_isbn13_to_isbn10_は979を変換しない():
    # 979 で始まる ISBN13 には対応する ISBN10 が無い（Amazon の /dp/ が作れない）
    assert isbn13_to_isbn10("9791234567896") is None
    assert isbn13_to_isbn10("978487311903") is None   # 12 桁
    assert isbn13_to_isbn10("") is None


def test_isbn13_to_isbn10_はハイフンを無視する():
    assert isbn13_to_isbn10("978-4-87311-903-8") == "4873119030"


def test_valid_isbn13():
    assert valid_isbn13("9784873119038")
    assert not valid_isbn13("9784873119039")
    assert not valid_isbn13("123")


# ---------------------------------------------------------------- 発売日

@pytest.mark.parametrize("raw, expected", [
    ("20260915", date(2026, 9, 15)),
    ("202609", date(2026, 9, 1)),       # 年月だけなら 1 日として扱う
    ("2026-09", date(2026, 9, 1)),
    ("2026-09-15", date(2026, 9, 15)),
    ("20260931", date(2026, 9, 1)),     # 9/31 のような日付は月初に丸める
    ("[19--]", None),
    ("2026", None),
    ("", None),
    (None, None),
])
def test_parse_pubdate(raw, expected):
    assert parse_pubdate(raw) == expected


def test_in_window():
    today = date(2026, 9, 21)
    assert in_window(date(2026, 9, 21), today, 90, 60)
    assert in_window(date(2026, 6, 23), today, 90, 60)     # ちょうど 90 日前
    assert in_window(date(2026, 11, 20), today, 90, 60)    # ちょうど 60 日後
    assert not in_window(date(2026, 6, 22), today, 90, 60)
    assert not in_window(date(2026, 11, 21), today, 90, 60)
    assert not in_window(None, today, 90, 60)


# ---------------------------------------------------------------- Cコード

def book(**kw) -> Book:
    raw = {"isbn": "9784873119038", "title": "テスト本", "publisher": "テスト社",
           "pubdate": "20260915", "authors": [{"name": "山田 太郎", "role": "著"}]}
    raw.update(kw)
    return Book.from_raw(raw)


def test_ccode_の3つの桁を読み分ける():
    b = book(ccode="0093")
    assert b.audience == "一般"          # 1 桁目
    assert b.form == "単行本"            # 2 桁目
    assert b.genre == "日本の小説・物語"  # 3〜4 桁目
    assert b.genre_slug == "japanese-novel"
    assert b.genre_group == "文学・小説"


def test_ccode_文庫のコミック():
    b = book(ccode="0979")
    assert b.audience == "一般"
    assert b.form == "コミック"
    assert b.genre == "コミック・劇画"


def test_ccode_児童書の絵本():
    b = book(ccode="8771")
    assert b.audience == "児童"
    assert b.form == "絵本"
    assert b.genre == "絵画・彫刻"


def test_ccode_が無い本():
    b = book(ccode="")
    assert b.audience == "" and b.form == "" and b.genre == ""
    assert b.genre_slug == ""


def test_ccode_が表に無い内容コード():
    b = book(ccode="0088")   # 88 は表に無い
    assert b.genre == ""


# ---------------------------------------------------------------- Book

def test_status():
    today = date(2026, 9, 21)
    assert book(pubdate="20261101").status(today)[0] == "upcoming"
    assert book(pubdate="20260923").status(today)[0] == "soon"
    assert book(pubdate="20260921").status(today) == ("soon", "本日発売")
    assert book(pubdate="20260919").status(today) == ("released", "今週の新刊")
    assert book(pubdate="20260701").status(today) == ("released", "発売中")


def test_full_title_は副題と巻を足す():
    b = book(title="銀河鉄道の夜", subtitle="新装版", volume="3")
    assert b.full_title == "銀河鉄道の夜 新装版 3"
    # すでに書名に入っているものは重ねない
    assert book(title="銀河鉄道の夜 新装版", subtitle="新装版").full_title == "銀河鉄道の夜 新装版"


def test_authors_は文字列でも辞書でも読める():
    assert book(authors=["山田 太郎"]).authors == ["山田 太郎"]
    assert book(authors=[{"name": "山田 太郎", "role": "著"}]).author_label == "山田 太郎（著）"


def test_month_key_と_week_key():
    b = book(pubdate="20260915")
    assert b.month_key() == "2026-09"
    assert b.week_key() == "2026-w38"


def test_normalize_person():
    assert normalize_person("夏目, 漱石, 1867-1916") == "夏目 漱石"
    assert normalize_person("山田太郎／著") == "山田太郎"
    assert normalize_person("  ") == ""


def test_slugify_は同じ名前で同じ結果になる():
    assert slugify("岩波書店") == slugify("岩波書店")
    assert slugify("岩波書店") != slugify("講談社")
    assert slugify("O'Reilly Japan").startswith("o-reilly-japan-")


# ---------------------------------------------------------------- 購入リンク

def test_buy_links_の既定():
    links = buy_links("9784873119038", "Real World HTTP", {})
    names = [l["name"] for l in links]
    assert names == ["Amazon", "楽天ブックス", "honto", "紀伊國屋書店"]
    assert links[0]["url"] == "https://www.amazon.co.jp/dp/4873119030"
    assert "9784873119038" in links[1]["url"]


def test_buy_links_はアフィリエイトを足す():
    aff = {"amazon_tag": "mytag-22", "rakuten_affiliate_url": "https://hb.afl.rakuten.co.jp/hgc/abc/?pc={url}"}
    links = buy_links("9784873119038", "本", aff)
    assert links[0]["url"].endswith("?tag=mytag-22")
    assert links[1]["url"].startswith("https://hb.afl.rakuten.co.jp/hgc/abc/?pc=https%3A%2F%2Fbooks.rakuten")


def test_buy_links_はisbn10が作れない本でamazonを飛ばす():
    names = [l["name"] for l in buy_links("9791234567896", "本", {})]
    assert "Amazon" not in names
    assert "楽天ブックス" in names
