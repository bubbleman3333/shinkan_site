"""openBD（https://openbd.jp/）から書誌を取ってきて data/books/ に貯める。

API はキー不要・無料。使うのは 2 つだけ。

  GET  /v1/coverage            収録されている全 ISBN13 の配列（約 194 万件・31 MB）
  POST /v1/get?isbn=...        ISBN をカンマ区切りで最大 1 万件まで。ONIX + summary が返る

初回は coverage 全件を 1 万件ずつ詳細取得し、発売日が窓（直近 PAST_DAYS 日〜これから
FUTURE_DAYS 日）に入るものだけを保存する。2 回目以降は coverage の差分（増えた ISBN）と、
手元にある「これから発売・出たばかり」の本だけを取り直す。

このマシンはメモリが少ないので、coverage も詳細も **1 バッチ処理したらすぐ捨てる**。
全件をメモリに載せない（coverage は gzip のファイルに流し込み、行単位で読む）。
"""
from __future__ import annotations

import gzip
import json
import re
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import requests

COVERAGE_URL = "https://api.openbd.jp/v1/coverage"
GET_URL = "https://api.openbd.jp/v1/get"
BATCH = 10000            # 1 リクエストあたりの ISBN 数（API の上限）
PAST_DAYS = 90           # 発売日がこれだけ前までの本を載せる
FUTURE_DAYS = 60         # 発売日がこれだけ先までの本を載せる
REFRESH_FROM_DAYS = 14   # 毎日の更新で、発売日がこれだけ前より新しい本は取り直す

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BOOKS_DIR = DATA / "books"
COVERAGE_FILE = DATA / "coverage.txt.gz"
STATE_FILE = DATA / "state.json"

# ONIX の著者区分コード。よく出るものだけ
ROLES = {
    "A01": "著", "A02": "共著", "A03": "脚本", "A08": "写真", "A12": "イラスト", "A13": "写真",
    "A19": "原作", "A23": "序文", "A24": "解説", "A36": "装丁", "A38": "原著", "A99": "著",
    "B01": "編", "B06": "訳", "B09": "編さん", "B20": "監修", "B25": "編曲",
    "C01": "企画", "E07": "朗読",
}


# ---------------------------------------------------------------- 通信

def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "shinkan-watch/1.0 (static site generator; https://github.com/bubbleman3333/shinkan_site)"
    return s


def post_get(sess: requests.Session, isbns: list[str], tries: int = 5) -> list[dict | None]:
    """ISBN のかたまりを投げて書誌の配列をもらう。失敗したら待って何度か試す。"""
    last: Exception | None = None
    for i in range(tries):
        try:
            r = sess.post(GET_URL, data={"isbn": ",".join(isbns)}, timeout=300)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(5 * (i + 1), 60))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - ネットワーク系は何でも再試行
            last = e
            time.sleep(min(5 * (i + 1), 60))
    raise RuntimeError(f"openBD /v1/get に失敗（{len(isbns)} 件）: {last}")


def stream_coverage(sess: requests.Session) -> Iterator[str]:
    """coverage を丸ごとメモリに載せずに ISBN を 1 件ずつ流す。

    中身は ["9784...","9784...",...] という平らな配列なので、
    受け取ったかたまりから "13 桁" を拾い、切れた末尾だけ次に持ち越す。
    """
    with sess.get(COVERAGE_URL, stream=True, timeout=600) as r:
        r.raise_for_status()
        buf = ""
        for chunk in r.iter_content(chunk_size=1 << 20):
            if not chunk:
                continue
            buf += chunk.decode("ascii", "ignore")
            end = 0
            for m in re.finditer(r'"(\d{13})"', buf):
                yield m.group(1)
                end = m.end()
            buf = buf[end:]


def download_coverage(sess: requests.Session, path: Path, log=print) -> int:
    """coverage を gzip のテキスト（1 行 1 ISBN）に落とす。戻り値は件数。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.gz")
    n = 0
    with gzip.open(tmp, "wt", encoding="ascii", compresslevel=6) as f:
        for isbn in stream_coverage(sess):
            f.write(isbn + "\n")
            n += 1
            if n % 500000 == 0:
                log(f"  coverage {n} 件")
    tmp.replace(path)
    log(f"coverage: {n} 件を {path.name} に保存")
    return n


def read_coverage(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="ascii") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line


def new_isbns(old_path: Path, new_path: Path) -> list[str]:
    """前回の coverage に無くて今回あるものを返す。

    coverage は ISBN の昇順で返ってくるので、両方を 1 回ずつ流して突き合わせる
    （全件をメモリに置かないため）。順序が崩れていた場合は素直に集合で取り直す。
    """
    old = read_coverage(old_path)
    new = read_coverage(new_path)
    added: list[str] = []
    try:
        o = next(old, None)
        prev_o = prev_n = ""
        for n in new:
            if n < prev_n:
                raise ValueError("coverage が昇順でない")
            prev_n = n
            while o is not None and o < n:
                if o < prev_o:
                    raise ValueError("coverage が昇順でない")
                prev_o = o
                o = next(old, None)
            if o == n:
                o = next(old, None)
            else:
                added.append(n)
        return added
    except ValueError:
        known = set(read_coverage(old_path))
        return [n for n in read_coverage(new_path) if n not in known]


# ---------------------------------------------------------------- ONIX の読み取り

def _first(value):
    """ONIX は 1 件だと dict、複数だと list になる。list に揃える。"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _title_of(dd: dict) -> tuple[str, str]:
    """(書名, 副題)。"""
    title = subtitle = ""
    for td in _first(dd.get("TitleDetail")):
        for te in _first(td.get("TitleElement")):
            if not title:
                title = ((te.get("TitleText") or {}).get("content") or "").strip()
            if not subtitle:
                subtitle = (te.get("Subtitle") or {}).get("content") or ""
                subtitle = subtitle.strip() if isinstance(subtitle, str) else ""
    return title, subtitle


def _collection_of(dd: dict) -> tuple[str, str]:
    """(シリーズ名, 巻数)。"""
    for col in _first(dd.get("Collection")):
        for td in _first(col.get("TitleDetail")):
            for te in _first(td.get("TitleElement")):
                name = ((te.get("TitleText") or {}).get("content") or "").strip()
                if name:
                    return name, (te.get("PartNumber") or "").strip()
    return "", ""


def _contributors_of(dd: dict) -> list[dict]:
    from .model import normalize_person

    out: list[dict] = []
    seen: set[str] = set()
    for c in _first(dd.get("Contributor")):
        name = (c.get("PersonName") or {}).get("content") or ""
        if not name:
            name = (c.get("CorporateName") or {}).get("content") or ""
        name = normalize_person(name)
        if not name or name in seen:
            continue
        seen.add(name)
        roles = [ROLES.get(r, "") for r in _first(c.get("ContributorRole"))]
        out.append({"name": name, "role": next((r for r in roles if r), "")})
        if len(out) >= 12:
            break
    return out


def _ccode_of(dd: dict) -> str:
    for s in _first(dd.get("Subject")):
        if s.get("SubjectSchemeIdentifier") == "78":
            code = re.sub(r"\D", "", str(s.get("SubjectCode") or ""))
            if len(code) == 4:
                return code
    return ""


def _texts_of(cd: dict) -> tuple[str, str]:
    """(内容紹介, 目次)。TextType は 03=長い紹介 / 02=短い紹介 / 23=解説 / 04=目次。"""
    by_type: dict[str, str] = {}
    for t in _first(cd.get("TextContent")):
        tt = str(t.get("TextType") or "")
        text = t.get("Text") or ""
        if isinstance(text, str) and text.strip() and tt not in by_type:
            by_type[tt] = text.strip()
    desc = by_type.get("03") or by_type.get("02") or by_type.get("23") or by_type.get("08") or ""
    return desc, by_type.get("04", "")


def _cover_of(record: dict, cd: dict) -> str:
    cover = ((record.get("summary") or {}).get("cover") or "").strip()
    if cover:
        return cover
    for sr in _first(cd.get("SupportingResource")):
        if str(sr.get("ResourceContentType")) != "01":  # 01 = 書影
            continue
        for rv in _first(sr.get("ResourceVersion")):
            link = (rv.get("ResourceLink") or "").strip()
            if link.startswith("http"):
                return link
    return ""


def _pubdate_of(pd: dict, summary: dict) -> str:
    """発売日（数字だけの文字列）。PublishingDateRole 01（発行日）を優先。"""
    dates: dict[str, str] = {}
    for d in _first(pd.get("PublishingDate")):
        role = str(d.get("PublishingDateRole") or "")
        value = re.sub(r"\D", "", str(d.get("Date") or ""))
        if value and role not in dates:
            dates[role] = value
    for role in ("01", "11", "09", "12"):
        if dates.get(role):
            return dates[role]
    if dates:
        return next(iter(dates.values()))
    return re.sub(r"\D", "", str(summary.get("pubdate") or ""))


def _price_of(ps: dict) -> int:
    for sd in _first(ps.get("SupplyDetail")):
        for p in _first(sd.get("Price")):
            amount = re.sub(r"\D", "", str(p.get("PriceAmount") or ""))
            if amount:
                return int(amount)
    return 0


def _pages_of(dd: dict) -> int:
    for e in _first(dd.get("Extent")):
        if str(e.get("ExtentType")) in ("11", "00", "10"):
            value = re.sub(r"\D", "", str(e.get("ExtentValue") or ""))
            if value:
                return int(value)
    return 0


def extract(record: dict) -> dict | None:
    """openBD の 1 レコード → 保存する形（必要な項目だけ）。ONIX 全体は捨てる。"""
    if not record:
        return None
    summary = record.get("summary") or {}
    onix = record.get("onix") or {}
    isbn = (summary.get("isbn") or onix.get("RecordReference") or "").strip()
    if not re.fullmatch(r"\d{13}", isbn):
        return None
    dd = onix.get("DescriptiveDetail") or {}
    cd = onix.get("CollateralDetail") or {}
    pd = onix.get("PublishingDetail") or {}
    ps = onix.get("ProductSupply") or {}

    title, subtitle = _title_of(dd)
    title = title or (summary.get("title") or "").strip()
    if not title:
        return None
    series, volume = _collection_of(dd)
    contributors = _contributors_of(dd)
    if not contributors and summary.get("author"):
        from .model import normalize_person

        contributors = [{"name": normalize_person(a), "role": ""}
                        for a in re.split(r"[ 　]+", summary["author"]) if normalize_person(a)][:12]
    publisher = ((pd.get("Publisher") or {}).get("PublisherName") or "").strip()
    publisher = publisher or ((pd.get("Imprint") or {}).get("ImprintName") or "").strip()
    publisher = publisher or (summary.get("publisher") or "").strip()
    description, toc = _texts_of(cd)

    return {
        "isbn": isbn,
        "title": title,
        "subtitle": subtitle,
        "series": series or (summary.get("series") or "").strip(),
        "volume": volume or (summary.get("volume") or "").strip(),
        "authors": contributors,
        "author_line": (summary.get("author") or "").strip(),
        "publisher": publisher,
        "pubdate": _pubdate_of(pd, summary),
        "cover": _cover_of(record, cd),
        "ccode": _ccode_of(dd),
        "description": description,
        "toc": toc,
        "price": _price_of(ps),
        "pages": _pages_of(dd),
    }


# ---------------------------------------------------------------- 保存

def book_path(isbn: str) -> Path:
    return BOOKS_DIR / f"{isbn}.json"


def save_book(raw: dict, today: date, books_dir: Path = BOOKS_DIR) -> bool:
    """保存する。戻り値は「新しく増えたか」。"""
    books_dir.mkdir(parents=True, exist_ok=True)
    path = books_dir / f"{raw['isbn']}.json"
    stamp = today.strftime("%Y%m%d")
    first_seen = stamp
    is_new = True
    if path.exists():
        is_new = False
        old = json.loads(path.read_text(encoding="utf-8"))
        first_seen = (old.get("_meta") or {}).get("first_seen") or stamp
    raw["_meta"] = {"first_seen": first_seen, "fetched_at": stamp}
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return is_new


def load_state(path: Path = STATE_FILE) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"phase": "initial", "done": 0, "kept": 0}


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 取り込み

def batched(items: Iterator[str], size: int) -> Iterator[list[str]]:
    buf: list[str] = []
    for it in items:
        buf.append(it)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def ingest(sess: requests.Session, isbns: Iterator[str], today: date, *, books_dir: Path = BOOKS_DIR,
           batch: int = BATCH, sleep: float = 0.4, log=print, on_batch=None) -> tuple[int, int]:
    """ISBN の流れを 1 万件ずつ詳細取得し、発売日が窓に入るものだけ保存する。

    戻り値は (保存した件数, 見た件数)。
    """
    from .model import in_window, parse_pubdate

    kept = seen = 0
    for chunk in batched(isbns, batch):
        data = post_get(sess, chunk)
        for record in data:
            raw = extract(record)
            if raw is None:
                continue
            if not in_window(parse_pubdate(raw["pubdate"]), today, PAST_DAYS, FUTURE_DAYS):
                continue
            save_book(raw, today, books_dir)
            kept += 1
        seen += len(chunk)
        del data
        if on_batch:
            on_batch(seen, kept)
        log(f"  {seen} 件を確認 / {kept} 冊を保存")
        time.sleep(sleep)
    return kept, seen


def sync(today: date | None = None, *, data_dir: Path = DATA, batch: int = BATCH, limit_batches: int | None = None,
         log=print) -> dict:
    """取り込みの入口。初回は全件走査、2 回目以降は差分だけ。"""
    from .model import parse_pubdate, today_jst

    today = today or today_jst()
    books_dir = data_dir / "books"
    coverage = data_dir / "coverage.txt.gz"
    state_file = data_dir / "state.json"
    sess = session()
    state = load_state(state_file)

    # ---- 初回: coverage 全件を頭から舐める（途中で落ちても done から再開できる） ----
    if state.get("phase") != "ready":
        if not coverage.exists():
            log("coverage を取得する")
            state["total"] = download_coverage(sess, coverage, log=log)
            state["done"] = 0
            state["kept"] = 0
            save_state(state, state_file)
        done = int(state.get("done", 0))
        log(f"初回取り込み: {done} 件目から")
        stream = read_coverage(coverage)
        for _ in range(done):  # 済んだ分は読み飛ばす
            next(stream, None)
        batches = 0
        for chunk in batched(stream, batch):
            data = post_get(sess, chunk)
            kept = 0
            for record in data:
                raw = extract(record)
                if raw is None:
                    continue
                pub = parse_pubdate(raw["pubdate"])
                if pub is None or not (today - timedelta(days=PAST_DAYS) <= pub <= today + timedelta(days=FUTURE_DAYS)):
                    continue
                save_book(raw, today, books_dir)
                kept += 1
            del data
            done += len(chunk)
            state["done"] = done
            state["kept"] = int(state.get("kept", 0)) + kept
            save_state(state, state_file)
            batches += 1
            log(f"  {done}/{state.get('total', '?')} 件を確認 / 累計 {state['kept']} 冊")
            if limit_batches and batches >= limit_batches:
                log("（--limit-batches で打ち切り）")
                return state
            time.sleep(0.4)
        state["phase"] = "ready"
        save_state(state, state_file)
        log(f"初回取り込み完了: {state['kept']} 冊")
        return state

    # ---- 2 回目以降: coverage の差分 ＋ 手元の新しい本の取り直し ----
    new_path = data_dir / "coverage.new.txt.gz"
    total = download_coverage(sess, new_path, log=log)
    added = new_isbns(coverage, new_path)
    log(f"新しく増えた ISBN: {len(added)} 件")

    refresh = []
    cut = today - timedelta(days=REFRESH_FROM_DAYS)
    for path in books_dir.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pub = parse_pubdate(raw.get("pubdate"))
        if pub is not None and pub >= cut:
            refresh.append(raw["isbn"])
    log(f"取り直す手元の本: {len(refresh)} 冊（発売日が {cut} 以降）")

    targets = added + [i for i in refresh if i not in set(added)]
    kept, seen = ingest(sess, iter(targets), today, books_dir=books_dir, batch=batch, log=log)
    new_path.replace(coverage)
    state.update(phase="ready", total=total, last_added=len(added), last_kept=kept,
                 updated=today.strftime("%Y%m%d"))
    save_state(state, state_file)
    log(f"更新完了: {kept} 冊を保存（確認 {seen} 件）")
    return state
