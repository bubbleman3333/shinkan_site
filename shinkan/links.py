"""購入リンクを config/affiliate.json のテンプレートから組み立てる。

テンプレートに使える差し込み:
  {isbn13}  13 桁の ISBN
  {isbn10}  10 桁の ISBN（978 始まりのみ。作れないときはその店を飛ばす）
  {title}   書名（URL エンコード済み）

Amazon は `amazon_tag` があれば `?tag=` を足す。楽天は `rakuten_affiliate_url`
（`{url}` を含むテンプレート）があれば、そのリンクで包む。
どちらも空なら素の URL が出るだけで、設定しなくてもサイトは成り立つ。
"""
from __future__ import annotations

from urllib.parse import quote

from .model import isbn13_to_isbn10

DEFAULT_STORES = [
    {"name": "Amazon", "url": "https://www.amazon.co.jp/dp/{isbn10}", "kind": "amazon"},
    {"name": "楽天ブックス", "url": "https://books.rakuten.co.jp/search?sitem={isbn13}", "kind": "rakuten"},
    {"name": "honto", "url": "https://honto.jp/netstore/search.html?k={isbn13}", "kind": ""},
    {"name": "紀伊國屋書店", "url": "https://www.kinokuniya.co.jp/disp/CSfDispListPage_001.jsp?qs=true&ptk=01&q={isbn13}", "kind": ""},
]


def buy_links(isbn13: str, title: str, aff: dict) -> list[dict]:
    """[{'name': 'Amazon', 'url': '...'}, ...] を返す。"""
    stores = aff.get("stores") or DEFAULT_STORES
    isbn10 = isbn13_to_isbn10(isbn13)
    out: list[dict] = []
    for store in stores:
        template = store.get("url") or ""
        if "{isbn10}" in template and not isbn10:
            continue  # 979 始まりなど ISBN10 に直せない本は Amazon の /dp/ が作れない
        url = template.format(isbn13=isbn13, isbn10=isbn10 or "", title=quote(title or ""))
        kind = store.get("kind") or ""
        if kind == "amazon" and aff.get("amazon_tag"):
            url += ("&" if "?" in url else "?") + "tag=" + quote(aff["amazon_tag"])
        if kind == "rakuten" and aff.get("rakuten_affiliate_url"):
            wrapper = aff["rakuten_affiliate_url"]
            url = wrapper.format(url=quote(url, safe="")) if "{url}" in wrapper else wrapper
        out.append({"name": store.get("name") or "購入", "url": url})
    return out
