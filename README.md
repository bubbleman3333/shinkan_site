# 新刊ウォッチ

発売したばかりの本とこれから出る本を、openBD の公開 API から毎日取り込み、静的サイトとして
GitHub Pages に配信する。**運用費ゼロ**（API はキー不要、GitHub Actions と Pages は無料枠）。

- 公開先: https://bubbleman3333.github.io/shinkan_site/
- 対象は**発売日が「直近 90 日 〜 これから 60 日」**の本。期間から外れた本は一覧から消えるが、
  ページは残す（リンク切れを作らないため）。
- 内容紹介・目次・書影は出版社が openBD に登録した公式データをそのまま出す（出典を明示）。
  解説記事は不要だが、`data/articles/<ISBN13>.md` を置けば差し込める。

## 仕組み

```
openBD API ──fetch──▶ data/books/<ISBN13>.json ──┐
            └─ data/coverage.txt.gz（前回の全 ISBN）├─build──▶ dist/ ──▶ GitHub Pages
data/articles/<ISBN13>.md（任意のメモ）───────────┘
```

- `shinkan/openbd.py` 取り込み。**初回**は収録 ISBN 全件（約 194 万件）を 1 万件ずつ詳細取得して
  発売日でふるいにかける（約 194 リクエスト・15 分ほど。`data/state.json` に進捗を残すので途中で
  落ちても再開できる）。**2 回目以降**は coverage の差分（増えた ISBN）と、手元にある発売日が
  新しい本だけを取り直す。
- `shinkan/model.py` 生データ → `Book`。ISBN13→ISBN10 の変換、Cコードの読み方（内容分類・
  対象読者・発行形態の表）、発売日の解釈と範囲判定。
- `shinkan/links.py` `config/affiliate.json` のテンプレートから購入リンクを作る。
- `shinkan/articles.py` 任意のメモの読み込みと、簡単な Markdown → HTML。
- `shinkan/build.py` Jinja2 で `dist/` を書き出す。
- `.github/workflows/daily.yml` 毎朝 6 時（JST）に fetch → データをコミット → build → Pages に配信。

### メモリについて

coverage（31 MB・約 194 万件）も 1 万件分の詳細（13 MB）も、**全件をメモリに載せない**。
coverage は gzip のファイルに流し込んで行単位で読み、詳細は 1 バッチ処理したらすぐ捨てる。

## 生成されるページ

| パス | 内容 |
| --- | --- |
| `/` | トップ。今週の新刊・来週発売・発売予定・最近出た本・ジャンル入口 |
| `/b/<ISBN13>/` | 本 1 冊のページ（書影・著者・出版社・発売日・内容紹介・目次・Cコード・購入リンク・同ジャンルの新刊） |
| `/this-week/` `/next-week/` `/upcoming/` `/new/` | 今週の新刊・来週発売・発売予定・新刊一覧（48 冊ずつページ送り） |
| `/g/<slug>/` `/g/` | ジャンル別（Cコードの 3〜4 桁目＝内容分類） |
| `/form/<slug>/` `/form/` | 形態別（Cコードの 2 桁目＝文庫・新書・コミック・絵本など） |
| `/p/<slug>/` `/p/` | 出版社別 |
| `/a/<slug>/` `/a/` | 著者別（2 冊以上ある人だけ） |
| `/monthly/<年-月>/` `/monthly/` | 月ごとの新刊まとめ |
| `/search/` | 書名・著者・出版社・ジャンル・形態・発売で絞り込む（`search.json` を JS で読む） |
| `/feed.xml` `/sitemap.xml` `/robots.txt` `/404.html` `/about/` `/privacy/` | RSS・サイトマップ・固定ページ |

SEO 向けに、全ページに canonical・OGP（書影があれば `og:image` は書影）・構造化データ
（WebSite/SearchAction、Book、BreadcrumbList、CollectionPage/ItemList）を出す。
期間から外れた本のページは noindex。

## コマンド（`.venv` を使う）

```powershell
.\.venv\Scripts\python -u -m shinkan fetch          # openBD から取り込む（初回は 15 分ほど）
.\.venv\Scripts\python -m shinkan build --site-url http://127.0.0.1:8000   # ローカル確認用に生成
.\.venv\Scripts\python -m http.server 8000 -d dist  # ブラウザで http://127.0.0.1:8000/
.\.venv\Scripts\python -m shinkan stats             # 手元のデータの様子を見る
.\.venv\Scripts\python -m shinkan pending --limit 30  # メモがまだ無い本
.\.venv\Scripts\python -m pytest -q
```

初回取り込みは時間がかかるので、別プロセスにしてログを見るとよい。

```powershell
Start-Process .\.venv\Scripts\python.exe -ArgumentList "-u","-m","shinkan","fetch" `
  -WindowStyle Hidden -RedirectStandardOutput fetch.log -RedirectStandardError fetch.err.log
```

やり直したいときは `data/coverage.txt.gz` と `data/state.json` を消す（`data/books/` は残してよい）。

## 期間や件数を変える

`shinkan/openbd.py` の先頭。

| 定数 | 既定 | 意味 |
| --- | --- | --- |
| `PAST_DAYS` | 90 | 発売日がこれだけ前までの本を載せる |
| `FUTURE_DAYS` | 60 | 発売日がこれだけ先までの本を載せる |
| `REFRESH_FROM_DAYS` | 14 | 毎日の更新で、発売日がこれだけ前より新しい本は取り直す（あとから書影・内容紹介が付くことがあるため） |
| `BATCH` | 10000 | 1 リクエストで問い合わせる ISBN 数（API の上限） |

## 購入リンク・広告

`config/affiliate.json`。すべて空のままでも動く（素の書店リンクが出る）。

| キー | 意味 |
| --- | --- |
| `amazon_tag` | Amazon アソシエイトの ID。入れると `?tag=` が付く |
| `rakuten_affiliate_url` | 楽天アフィリエイトのリンク。`{url}` に楽天ブックスの URL が入る |
| `stores` | 購入リンクのテンプレート。`{isbn13}` `{isbn10}` `{title}` が使える |
| `sidebar` `book_top` `book_bottom` `list_bottom` `head` | 広告タグの HTML をそのまま貼る枠 |

既定は Amazon（`/dp/<ISBN10>`）・楽天ブックス・honto・紀伊國屋書店の 4 つ。
ISBN10 に直せない本（979 で始まるもの）では Amazon のリンクを出さない。

## メモを足す

`data/articles/README.md` の形式で `data/articles/<ISBN13>.md` を置く。push すれば Actions が
生成して公開する。

## データについて

openBD には出版社が登録した詳しいレコード（書影・内容紹介・Cコードあり）と、
国立国会図書館由来の最小限のレコード（書名・著者・出版社・発売年月だけ）が混ざっている。
そのため書影や Cコードが無い本が半分以上ある。ジャンル別のページはCコードがある本だけが対象。

## 設定

`config/site.json`。`site_url` は Pages の URL（ビルド時に `--site-url` で上書きできる）。
