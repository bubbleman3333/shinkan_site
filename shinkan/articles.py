"""本ごとの追記記事（任意）と、固定ページの Markdown を HTML にする。

新刊ウォッチは「解説文を書かないと成り立たないサイト」にはしない。内容紹介は出版社が
openBD に登録した公式文をそのまま出す（出典を明示する）。そのうえで、補助金ウォッチと
同じように `data/articles/<ISBN13>.md` を置けばその本のページに差し込めるようにしてある。

Markdown は見出し・段落・箇条書き・リンク・強調だけの簡単なものに対応する
（外部ライブラリを増やさないため）。
"""
from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLE_DIR = ROOT / "data" / "articles"

_INLINE = [
    (re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)"), r'<a href="\2" rel="noopener" target="_blank">\1</a>'),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
]


def inline(text: str) -> str:
    out = html.escape(text)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out


def md_to_html(text: str) -> str:
    """見出し・段落・箇条書き・引用だけの簡単な Markdown → HTML。"""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    mode: str | None = None

    def close() -> None:
        nonlocal mode
        if mode in ("ul", "ol"):
            out.append(f"</{mode}>")
        mode = None

    for line in lines:
        s = line.rstrip()
        if not s.strip():
            close()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close()
            level = min(len(m.group(1)) + 1, 6)  # 記事内の見出しは h2 から
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^\s*[-*+]\s+(.*)$", s)
        if m:
            if mode != "ul":
                close()
                out.append("<ul>")
                mode = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", s)
        if m:
            if mode != "ol":
                close()
                out.append("<ol>")
                mode = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        m = re.match(r"^>\s?(.*)$", s)
        if m:
            close()
            out.append(f"<blockquote>{inline(m.group(1))}</blockquote>")
            continue
        close()
        out.append(f"<p>{inline(s.strip())}</p>")
    close()
    return "\n".join(out)


def text_to_html(text: str) -> str:
    """出版社の内容紹介（ただの改行区切りテキスト）を段落にする。"""
    paras = [p.strip() for p in (text or "").split("\n") if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in paras)


def toc_to_html(text: str) -> str:
    """目次を箇条書きにする。"""
    items = [p.strip() for p in (text or "").split("\n") if p.strip()]
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"


def article_for(isbn: str, article_dir: Path = ARTICLE_DIR) -> dict:
    """`data/articles/<ISBN13>.md` があれば読み込む。無ければ空。

    1 行目が `# 見出し` ならそれを見出しとして使う。
    """
    path = article_dir / f"{isbn}.md"
    if not path.exists():
        return {"written": False, "title": "", "body_html": ""}
    text = path.read_text(encoding="utf-8").strip()
    title = ""
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        text = "\n".join(lines[1:])
    return {"written": True, "title": title, "body_html": md_to_html(text)}


def pending(books, limit: int | None = None, article_dir: Path = ARTICLE_DIR) -> list:
    """記事がまだ無い本を、発売日が新しい順に返す。"""
    rows = [b for b in books if not (article_dir / f"{b.isbn}.md").exists()]
    rows.sort(key=lambda b: b.pubdate or date.min, reverse=True)
    return rows[:limit] if limit else rows
