"""openBD の生データ 1 件を、テンプレートから扱いやすい形（Book）に直す。

openBD の ONIX はそのままだと深くて扱いにくいので、取り込みの時点で必要な項目だけに
削った「素の dict」を data/books/<isbn>.json に置き、ここでそれを Book にする。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------- Cコード
# Cコードは 4 桁。1 桁目＝販売対象、2 桁目＝発行形態、3〜4 桁目＝内容。
# 例: C0093 → 一般 / 単行本 / 日本文学、小説・物語

AUDIENCES: dict[str, str] = {
    "0": "一般",
    "1": "教養",
    "2": "実用",
    "3": "専門",
    "4": "検定教科書・消耗品的読み物",
    "5": "婦人",
    "6": "学参（小・中学）",
    "7": "学参（高校）",
    "8": "児童",
    "9": "雑誌扱い",
}

AUDIENCE_SLUGS: dict[str, str] = {
    "0": "general", "1": "liberal", "2": "practical", "3": "technical", "4": "textbook",
    "5": "women", "6": "study-jhs", "7": "study-hs", "8": "children", "9": "magazine",
}

FORMS: dict[str, str] = {
    "0": "単行本",
    "1": "文庫",
    "2": "新書",
    "3": "全集・双書",
    "4": "ムック・その他",
    "5": "事典・辞典",
    "6": "図鑑",
    "7": "絵本",
    "8": "磁性媒体など",
    "9": "コミック",
}

FORM_SLUGS: dict[str, str] = {
    "0": "tankobon", "1": "bunko", "2": "shinsho", "3": "zenshu", "4": "mook",
    "5": "jiten", "6": "zukan", "7": "ehon", "8": "media", "9": "comic",
}

# 3〜4 桁目（内容）。値は (表示名, slug)
GENRES: dict[str, tuple[str, str]] = {
    "00": ("総記", "general"),
    "01": ("百科事典", "encyclopedia"),
    "02": ("年鑑・雑誌", "yearbook"),
    "04": ("情報科学", "information-science"),
    "10": ("哲学", "philosophy"),
    "11": ("心理学", "psychology"),
    "12": ("倫理学", "ethics"),
    "14": ("宗教", "religion"),
    "15": ("仏教", "buddhism"),
    "16": ("キリスト教", "christianity"),
    "20": ("歴史総記", "history"),
    "21": ("日本歴史", "japanese-history"),
    "22": ("外国歴史", "world-history"),
    "23": ("伝記", "biography"),
    "25": ("地理", "geography"),
    "26": ("旅行", "travel"),
    "30": ("社会科学総記", "social-science"),
    "31": ("政治・国防・軍事", "politics"),
    "32": ("法律", "law"),
    "33": ("経済・財政・統計", "economics"),
    "34": ("経営", "management"),
    "36": ("社会", "society"),
    "37": ("教育", "education"),
    "39": ("民族・風習", "folklore"),
    "40": ("自然科学総記", "natural-science"),
    "41": ("数学", "mathematics"),
    "42": ("物理学", "physics"),
    "43": ("化学", "chemistry"),
    "44": ("天文・地学", "astronomy-earth"),
    "45": ("生物学", "biology"),
    "47": ("医学・薬学", "medicine"),
    "50": ("工学総記", "engineering"),
    "51": ("土木", "civil-engineering"),
    "52": ("建築", "architecture"),
    "53": ("機械", "machinery"),
    "54": ("電気", "electricity"),
    "55": ("電子通信", "electronics"),
    "56": ("海事", "maritime"),
    "57": ("採鉱・冶金", "mining"),
    "58": ("その他の工業", "other-industry"),
    "60": ("産業総記", "industry"),
    "61": ("農林業", "agriculture"),
    "62": ("水産業", "fishery"),
    "63": ("商業", "commerce"),
    "65": ("交通・通信", "transport"),
    "70": ("芸術総記", "art"),
    "71": ("絵画・彫刻", "painting"),
    "72": ("写真・工芸", "photography-craft"),
    "73": ("音楽・舞踊", "music"),
    "74": ("演劇・映画", "theater-film"),
    "75": ("体育・スポーツ", "sports"),
    "76": ("諸芸・娯楽", "hobby"),
    "77": ("家事", "home"),
    "79": ("コミック・劇画", "comics"),
    "80": ("語学総記", "language"),
    "81": ("日本語", "japanese"),
    "82": ("英米語", "english"),
    "84": ("ドイツ語", "german"),
    "85": ("フランス語", "french"),
    "87": ("各国語", "other-language"),
    "90": ("文学総記", "literature"),
    "91": ("日本文学総記", "japanese-literature"),
    "92": ("日本文学・詩歌", "poetry"),
    "93": ("日本の小説・物語", "japanese-novel"),
    "95": ("日本文学・評論・随筆", "essay"),
    "97": ("外国の小説", "foreign-novel"),
    "98": ("外国文学・その他", "foreign-literature"),
    "99": ("その他", "misc"),
}

# トップページ用の大きなくくり。(名前, slug, 含まれる内容コード)
GENRE_GROUPS: list[tuple[str, list[str]]] = [
    ("文学・小説", ["90", "91", "92", "93", "95", "97", "98"]),
    ("コミック・絵本", ["79"]),
    ("ビジネス・経済", ["33", "34", "63", "60"]),
    ("社会・政治・法律", ["30", "31", "32", "36", "37", "39"]),
    ("歴史・地理・旅行", ["20", "21", "22", "23", "25", "26"]),
    ("哲学・宗教・心理", ["10", "11", "12", "14", "15", "16"]),
    ("科学・医学", ["40", "41", "42", "43", "44", "45", "47"]),
    ("工学・技術・産業", ["04", "50", "51", "52", "53", "54", "55", "56", "57", "58", "61", "62", "65"]),
    ("芸術・生活・趣味", ["70", "71", "72", "73", "74", "75", "76", "77"]),
    ("語学", ["80", "81", "82", "84", "85", "87"]),
    ("総記・事典・その他", ["00", "01", "02", "99"]),
]

GENRE_GROUP_OF: dict[str, str] = {code: name for name, codes in GENRE_GROUPS for code in codes}


def genre_name(code: str) -> str:
    return GENRES.get(code, ("その他", "misc"))[0]


def genre_slug(code: str) -> str:
    return GENRES.get(code, ("その他", "misc"))[1]


# ---------------------------------------------------------------- ISBN

def isbn13_to_isbn10(isbn13: str) -> str | None:
    """ISBN13（978 始まりのみ）を ISBN10 に直す。979 始まりや桁数違いは None。

    Amazon の /dp/ は ISBN10 を使うのでこの変換が要る。
    """
    digits = re.sub(r"[^0-9Xx]", "", isbn13 or "")
    if len(digits) != 13 or not digits.startswith("978") or not digits.isdigit():
        return None
    core = digits[3:12]  # 出版者記号＋書名記号の 9 桁
    total = sum((10 - i) * int(c) for i, c in enumerate(core))
    check = (11 - total % 11) % 11
    return core + ("X" if check == 10 else str(check))


def valid_isbn13(isbn13: str) -> bool:
    digits = re.sub(r"\D", "", isbn13 or "")
    if len(digits) != 13:
        return False
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


# ---------------------------------------------------------------- 発売日

def parse_pubdate(value: str | None) -> date | None:
    """openBD の発売日は '20260915' / '202609' / '2026-09' / '2026-09-15' / '[19--]' が混ざる。

    年月までしか無いものはその月の 1 日として扱う。年だけ・読めないものは None。
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 8:
        digits = digits[:8]
    elif len(digits) == 6:
        digits = digits + "01"
    else:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        # 20260931 のような日付は月初に丸める
        try:
            return date(int(digits[:4]), int(digits[4:6]), 1)
        except ValueError:
            return None


def in_window(pub: date | None, today: date, past_days: int, future_days: int) -> bool:
    """発売日が「past_days 日前 〜 future_days 日後」に入るか。"""
    if pub is None:
        return False
    return today - timedelta(days=past_days) <= pub <= today + timedelta(days=future_days)


# ---------------------------------------------------------------- 文字列

def slugify(name: str) -> str:
    """出版社名・著者名 → URL に使える短い文字列。日本語はハッシュに落とす。"""
    base = unicodedata.normalize("NFKC", name or "").strip().lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    digest = hashlib.md5((name or "").encode("utf-8")).hexdigest()[:8]
    if ascii_part and len(ascii_part) <= 40 and re.fullmatch(r"[a-z0-9-]+", ascii_part):
        return f"{ascii_part}-{digest}"
    return digest


def normalize_person(name: str) -> str:
    """'夏目, 漱石, 1867-1916' → '夏目 漱石'。openBD の著者名は表記ゆれが激しい。"""
    name = unicodedata.normalize("NFKC", name or "").strip()
    name = re.sub(r"[,、]?\s*\d{3,4}\s*-\s*\d{0,4}\s*$", "", name)  # 生没年を落とす
    name = re.sub(r"\s*[／/]\s*(著|編|編集|訳|監修|イラスト|写真|絵|作|画|原作|解説|共著|校訂|編著).*$", "", name)
    name = name.replace(",", " ").replace("、", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def clean_text(text: str | None) -> str:
    """内容紹介の中の連続改行・全角空白を整える。"""
    if not text:
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n").replace("　", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def text_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n") if p.strip()]


# ---------------------------------------------------------------- Book

@dataclass
class Book:
    isbn: str
    title: str
    subtitle: str
    series: str
    volume: str
    contributors: list[dict]
    author_line: str
    publisher: str
    pubdate: date | None
    pubdate_raw: str
    cover: str
    ccode: str
    description: str
    toc: str
    price: int
    pages: int
    first_seen: date | None
    fetched_at: date | None

    @classmethod
    def from_raw(cls, raw: dict) -> "Book":
        meta = raw.get("_meta") or {}
        contributors = []
        for a in raw.get("authors") or []:
            if isinstance(a, str):
                a = {"name": a, "role": ""}
            if (a.get("name") or "").strip():
                contributors.append({"name": a["name"].strip(), "role": (a.get("role") or "").strip()})
        return cls(
            isbn=raw["isbn"],
            title=(raw.get("title") or "").strip(),
            subtitle=(raw.get("subtitle") or "").strip(),
            series=(raw.get("series") or "").strip(),
            volume=(raw.get("volume") or "").strip(),
            contributors=contributors,
            author_line=(raw.get("author_line") or "").strip(),
            publisher=(raw.get("publisher") or "").strip() or "出版社不明",
            pubdate=parse_pubdate(raw.get("pubdate")),
            pubdate_raw=(raw.get("pubdate") or "").strip(),
            cover=(raw.get("cover") or "").strip(),
            ccode=(raw.get("ccode") or "").strip(),
            description=clean_text(raw.get("description")),
            toc=clean_text(raw.get("toc")),
            price=int(raw.get("price") or 0),
            pages=int(raw.get("pages") or 0),
            first_seen=parse_pubdate(meta.get("first_seen")),
            fetched_at=parse_pubdate(meta.get("fetched_at")),
        )

    # ---- URL ----
    @property
    def path(self) -> str:
        return f"b/{self.isbn}/"

    @property
    def authors(self) -> list[str]:
        return [c["name"] for c in self.contributors]

    def author_slug(self, name: str) -> str:
        return slugify(name)

    @property
    def author_label(self) -> str:
        """'夏目 漱石（著）・森 鴎外（編）' のような 1 行。"""
        bits = [c["name"] + (f"（{c['role']}）" if c["role"] else "") for c in self.contributors[:4]]
        more = len(self.contributors) - 4
        return "・".join(bits) + (f" ほか{more}名" if more > 0 else "")

    @property
    def isbn10(self) -> str | None:
        return isbn13_to_isbn10(self.isbn)

    # ---- Cコード ----
    @property
    def audience_code(self) -> str:
        return self.ccode[0] if len(self.ccode) == 4 else ""

    @property
    def form_code(self) -> str:
        return self.ccode[1] if len(self.ccode) == 4 else ""

    @property
    def genre_code(self) -> str:
        return self.ccode[2:4] if len(self.ccode) == 4 else ""

    @property
    def audience(self) -> str:
        return AUDIENCES.get(self.audience_code, "")

    @property
    def form(self) -> str:
        return FORMS.get(self.form_code, "")

    @property
    def genre(self) -> str:
        return GENRES[self.genre_code][0] if self.genre_code in GENRES else ""

    @property
    def genre_slug(self) -> str:
        return GENRES[self.genre_code][1] if self.genre_code in GENRES else ""

    @property
    def genre_group(self) -> str:
        return GENRE_GROUP_OF.get(self.genre_code, "")

    @property
    def form_slug(self) -> str:
        return FORM_SLUGS.get(self.form_code, "")

    # ---- 表示 ----
    @property
    def full_title(self) -> str:
        t = self.title
        if self.subtitle and self.subtitle not in t:
            t = f"{t} {self.subtitle}"
        if self.volume and self.volume not in t:
            t = f"{t} {self.volume}"
        return t.strip()

    @property
    def publisher_slug(self) -> str:
        return slugify(self.publisher)

    def is_released(self, today: date) -> bool:
        return self.pubdate is not None and self.pubdate <= today

    def days_until(self, today: date) -> int | None:
        if self.pubdate is None:
            return None
        return (self.pubdate - today).days

    def status(self, today: date) -> tuple[str, str]:
        """('released'|'soon'|'upcoming', 表示ラベル)"""
        d = self.days_until(today)
        if d is None:
            return "released", "発売日不明"
        if d > 7:
            return "upcoming", "発売予定"
        if d > 0:
            return "soon", f"あと{d}日で発売"
        if d == 0:
            return "soon", "本日発売"
        if d >= -7:
            return "released", "今週の新刊"
        return "released", "発売中"

    def week_key(self) -> str | None:
        if self.pubdate is None:
            return None
        y, w, _ = self.pubdate.isocalendar()
        return f"{y}-w{w:02d}"

    def month_key(self) -> str | None:
        if self.pubdate is None:
            return None
        return self.pubdate.strftime("%Y-%m")

    def summary_text(self, limit: int = 110) -> str:
        """一覧や meta description に使う短い紹介文。"""
        src = self.description or self.toc
        if src:
            one = re.sub(r"\s+", " ", src)
            return one[:limit] + ("…" if len(one) > limit else "")
        bits = [self.publisher]
        if self.author_line:
            bits.insert(0, self.author_line)
        if self.genre:
            bits.append(self.genre)
        return " / ".join(b for b in bits if b)


def week_range(key: str) -> tuple[date, date]:
    """'2026-w39' → その週の月曜日と日曜日。"""
    y, w = key.split("-w")
    monday = date.fromisocalendar(int(y), int(w), 1)
    return monday, monday + timedelta(days=6)


def today_jst() -> date:
    return datetime.now(JST).date()
