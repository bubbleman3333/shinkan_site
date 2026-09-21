"""openBD の ONIX から必要な項目だけを抜き出せること（通信はしない）。"""
from datetime import date
from pathlib import Path

from shinkan.model import parse_pubdate
from shinkan.openbd import extract, new_isbns, save_book

RECORD = {
    "onix": {
        "RecordReference": "9784873119038",
        "DescriptiveDetail": {
            "TitleDetail": {"TitleType": "01", "TitleElement": {
                "TitleElementLevel": "01",
                "TitleText": {"content": "Real World HTTP"},
                "Subtitle": {"content": "歴史とコードに学ぶインターネットとウェブ技術"}}},
            "Contributor": [
                {"SequenceNumber": "1", "ContributorRole": ["A01"],
                 "PersonName": {"content": "渋川, よしき, 1980-"}},
                {"SequenceNumber": "2", "ContributorRole": ["B06"], "PersonName": {"content": "山田 花子"}},
            ],
            "Collection": {"CollectionType": "10", "TitleDetail": {"TitleElement": [
                {"TitleElementLevel": "02", "PartNumber": "3", "TitleText": {"content": "オライリー実践"}}]}},
            "Subject": [{"SubjectSchemeIdentifier": "79", "SubjectCode": "07"},
                        {"SubjectSchemeIdentifier": "78", "SubjectCode": "3055"}],
            "Extent": [{"ExtentType": "11", "ExtentValue": "500", "ExtentUnit": "03"}],
        },
        "CollateralDetail": {
            "TextContent": [{"TextType": "04", "Text": "1章 HTTP/1.0"},
                            {"TextType": "03", "Text": "HTTP の歴史をたどる。"}],
            "SupportingResource": [{"ResourceContentType": "01", "ResourceVersion": [
                {"ResourceLink": "https://cover.openbd.jp/9784873119038.jpg"}]}],
        },
        "PublishingDetail": {
            "Imprint": {"ImprintName": "オライリー"},
            "Publisher": {"PublisherName": "オライリー・ジャパン"},
            "PublishingDate": [{"PublishingDateRole": "11", "Date": "202004"},
                               {"PublishingDateRole": "01", "Date": "20260918"}],
        },
        "ProductSupply": {"SupplyDetail": {"Price": [{"PriceType": "01", "PriceAmount": "3600"}]}},
    },
    "summary": {"isbn": "9784873119038", "title": "Real World HTTP", "publisher": "オライリー",
                "pubdate": "202004", "cover": "", "author": "渋川よしき"},
}


def test_extract():
    raw = extract(RECORD)
    assert raw["isbn"] == "9784873119038"
    assert raw["title"] == "Real World HTTP"
    assert raw["subtitle"] == "歴史とコードに学ぶインターネットとウェブ技術"
    assert raw["series"] == "オライリー実践" and raw["volume"] == "3"
    assert raw["authors"] == [{"name": "渋川 よしき", "role": "著"}, {"name": "山田 花子", "role": "訳"}]
    assert raw["publisher"] == "オライリー・ジャパン"     # Publisher が Imprint より優先
    assert raw["pubdate"] == "20260918"                   # Role 01 が Role 11 より優先
    assert raw["cover"] == "https://cover.openbd.jp/9784873119038.jpg"
    assert raw["ccode"] == "3055"                         # SubjectSchemeIdentifier 78 だけを見る
    assert raw["description"] == "HTTP の歴史をたどる。"   # TextType 03
    assert raw["toc"] == "1章 HTTP/1.0"                    # TextType 04
    assert raw["price"] == 3600 and raw["pages"] == 500
    assert "onix" not in raw                               # ONIX 全体は保存しない


def test_extract_は中身の薄いレコードでも落ちない():
    raw = extract({"summary": {"isbn": "9784065442265", "title": "神様と初恋. 1",
                               "publisher": "講談社", "pubdate": "202607", "author": "山田太郎"},
                   "onix": {"DescriptiveDetail": {}, "CollateralDetail": {}, "PublishingDetail": {}}})
    assert raw["title"] == "神様と初恋. 1"
    assert raw["publisher"] == "講談社"
    assert parse_pubdate(raw["pubdate"]) == date(2026, 7, 1)
    assert raw["authors"] == [{"name": "山田太郎", "role": ""}]
    assert raw["ccode"] == "" and raw["cover"] == ""


def test_extract_は空や_isbn_なしを弾く():
    assert extract(None) is None
    assert extract({}) is None
    assert extract({"summary": {"isbn": "1234", "title": "本"}}) is None
    assert extract({"summary": {"isbn": "9784873119038", "title": ""}, "onix": {}}) is None


def test_save_book_は初めて見た日を残す(tmp_path: Path):
    raw = extract(RECORD)
    assert save_book(dict(raw), date(2026, 9, 1), tmp_path) is True
    assert save_book(dict(raw), date(2026, 9, 21), tmp_path) is False
    import json
    saved = json.loads((tmp_path / "9784873119038.json").read_text(encoding="utf-8"))
    assert saved["_meta"] == {"first_seen": "20260901", "fetched_at": "20260921"}


def _gz(path: Path, isbns: list[str]) -> Path:
    import gzip
    with gzip.open(path, "wt", encoding="ascii") as f:
        f.write("".join(i + "\n" for i in isbns))
    return path


def test_new_isbns_は増えた分だけ返す(tmp_path: Path):
    old = _gz(tmp_path / "old.gz", ["9784000000001", "9784000000003", "9784000000005"])
    new = _gz(tmp_path / "new.gz", ["9784000000001", "9784000000002", "9784000000003",
                                    "9784000000005", "9784000000009"])
    assert new_isbns(old, new) == ["9784000000002", "9784000000009"]


def test_new_isbns_は順不同でも動く(tmp_path: Path):
    old = _gz(tmp_path / "old.gz", ["9784000000005", "9784000000001"])
    new = _gz(tmp_path / "new.gz", ["9784000000005", "9784000000001", "9784000000007"])
    assert new_isbns(old, new) == ["9784000000007"]
