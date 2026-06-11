# -*- coding: utf-8 -*-
"""
防衛関連サイト スクレイピング → Google Sheets 書き込み
GitHub Actions セルフホストランナー（Windows）から実行する

mod.go.jp（報道発表・トピックス・航空ニュース・RSS） … curl_cffi
九州防衛局・新富町 … Playwright別プロセス
防衛省RSS・九州防衛局 … 本文も取得してシートに保存
"""

import asyncio
import os
import re
import sys
import json
import subprocess
from datetime import datetime
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
import gspread

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

CF_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# 本文取得時に除去するノイズセレクタ
NOISE_SELECTORS = [
    "header", "footer", "nav", ".breadcrumb", "#breadcrumb",
    ".side", "#side", ".menu", "#menu", ".gnav", "#gnav",
    "script", "style", "noscript",
]

def get_sheet_client():
    creds_data = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    return gspread.authorize(creds)


# ──────────────────────────────────────────────
# curl_cffi 系
# ──────────────────────────────────────────────

async def fetch_html(session: AsyncSession, url: str) -> BeautifulSoup | None:
    try:
        r = await session.get(url, headers=CF_HEADERS, timeout=30, impersonate="chrome124")
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    [ERROR] {url}: {e}")
        return None

def extract_date(text: str) -> str:
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}\.\d{1,2}\.\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2})', text)
    return m.group(1) if m else ""

def date_from_filename(url: str) -> str:
    m = re.search(r'/(\d{4})(\d{2})(\d{2})', url)
    return f"{m.group(1)}年{int(m.group(2)):02d}月{int(m.group(3)):02d}日" if m else ""

def extract_body_text(soup: BeautifulSoup, max_chars: int = 1000) -> str:
    """HTMLからノイズを除去して本文テキストを抽出"""
    for selector in NOISE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
    # メインコンテンツ候補を優先
    for selector in ["main", "#main", ".main", "#content", ".content", "article", ".article"]:
        main = soup.select_one(selector)
        if main:
            text = main.get_text("\n", strip=True)
            if len(text) > 100:
                return re.sub(r'\n{3,}', '\n\n', text)[:max_chars]
    # フォールバック: body全体
    text = soup.get_text("\n", strip=True)
    return re.sub(r'\n{3,}', '\n\n', text)[:max_chars]

async def fetch_body(session: AsyncSession, url: str) -> str:
    """URLから本文テキストを取得（PDFはスキップ）"""
    if not url or url.endswith(".pdf"):
        return ""
    soup = await fetch_html(session, url)
    if not soup:
        return ""
    return extract_body_text(soup)

NAV_PREFIXES = (
    "統合幕僚監部について", "活動情報", "フォトギャラリー", "調達情報",
    "報道発表", "HOME", "トップ", "サイトマップ", "お問い合わせ",
    "文字サイズ", "English", "ページトップ",
)

async def scrape_js_press(session: AsyncSession) -> list[dict]:
    soup = await fetch_html(session, "https://www.mod.go.jp/js/press/index.html")
    if not soup:
        return []
    result = []
    for a in soup.select("a[href]")[:80]:
        href = a.get("href", "")
        if "/js/pdf/" not in href and "/js/press/" not in href:
            continue
        text = a.get_text(" ", strip=True)
        if len(text) < 6:
            continue
        url = href if href.startswith("http") else "https://www.mod.go.jp" + href
        date = extract_date(text)
        if not date:
            continue
        result.append({
            "date":  date,
            "title": re.sub(r'^\d{4}年\d{1,2}月\d{1,2}日\s*(公表\s*)?', '', text).strip()[:150],
            "url":   url,
            "body":  "",
        })
    return result[:50]

async def scrape_js_topics(session: AsyncSession) -> list[dict]:
    soup = await fetch_html(session, "https://www.mod.go.jp/js/about/topics.html")
    if not soup:
        return []
    result = []
    seen = set()
    for tag in soup.select("li, p, dt, dd"):
        text = tag.get_text(" ", strip=True)
        if len(text) < 20 or len(text) > 400:
            continue
        if any(text.startswith(p) for p in NAV_PREFIXES):
            continue
        key = text[:40]
        if key in seen:
            continue
        seen.add(key)
        a = tag.find("a")
        href = a["href"] if a and a.get("href") else ""
        url = ("https://www.mod.go.jp" + href) if href and not href.startswith("http") else href
        result.append({"date": extract_date(text), "title": text[:150], "url": url, "body": ""})
        if len(result) >= 20:
            break
    return result

async def scrape_asdf_news(session: AsyncSession) -> list[dict]:
    soup = await fetch_html(session, "https://www.mod.go.jp/asdf/news/")
    if not soup:
        return []
    result = []
    for a in soup.select("a[href]")[:100]:
        href = a.get("href", "")
        if "/asdf/news" not in href and "/asdf/pdf" not in href:
            continue
        text = a.get_text(" ", strip=True)
        if len(text) < 6:
            continue
        url = href if href.startswith("http") else "https://www.mod.go.jp" + href
        date = extract_date(text) or date_from_filename(url)
        result.append({"date": date, "title": text[:150], "url": url, "body": ""})
    return result[:50]

async def scrape_rss(session: AsyncSession, url: str) -> list[dict]:
    """防衛省RSSフィードを取得してパース（本文も取得）"""
    try:
        r = await session.get(url, headers=CF_HEADERS, timeout=30, impersonate="chrome124")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml-xml")
        items = soup.find_all("item")
        result = []
        for item in items[:50]:
            title = item.find("title")
            link  = item.find("link")
            pub   = item.find("pubDate") or item.find("dc:date") or item.find("date")
            title_text = title.get_text(strip=True) if title else ""
            # linkタグはBeautifulSoup(lxml-xml)では次の兄弟テキストノードになる場合がある
            if link:
                link_text = link.get_text(strip=True)
                # 相対URLの場合は絶対URLに補完
                if link_text and not link_text.startswith("http"):
                    link_text = "https://www.mod.go.jp" + link_text
            else:
                link_text = ""
            pub_text   = pub.get_text(strip=True) if pub else ""
            date = ""
            if pub_text:
                m = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', pub_text)
                if m:
                    month_map = {"Jan":"1","Feb":"2","Mar":"3","Apr":"4","May":"5","Jun":"6",
                                 "Jul":"7","Aug":"8","Sep":"9","Oct":"10","Nov":"11","Dec":"12"}
                    mon = month_map.get(m.group(2), m.group(2))
                    date = f"{m.group(3)}年{int(mon):02d}月{int(m.group(1)):02d}日"
                else:
                    date = extract_date(pub_text)
            if title_text:
                result.append({"date": date, "title": title_text[:150], "url": link_text, "body": ""})
        return result
    except Exception as e:
        print(f"    [ERROR] RSS {url}: {e}")
        return []

async def fetch_bodies_for_rss(session: AsyncSession, items: list[dict], max_items: int = 20) -> list[dict]:
    """RSS記事の本文を取得（新着上位N件のみ）"""
    for i, item in enumerate(items[:max_items]):
        url = item.get("url", "")
        if url and not url.endswith(".pdf"):
            print(f"    [BODY] {i+1}/{min(max_items, len(items))} {url[:60]}")
            item["body"] = await fetch_body(session, url)
            await asyncio.sleep(1)
    return items


# ──────────────────────────────────────────────
# Playwright別プロセス系
# ──────────────────────────────────────────────

def run_subprocess(script_name: str) -> list[dict]:
    script = os.path.join(os.path.dirname(__file__), script_name)
    proc = subprocess.run(
        [sys.executable, script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{script_name} failed:\n{proc.stderr[-500:]}")
    return json.loads(proc.stdout.strip())


# ──────────────────────────────────────────────
# Sheets 書き込み（本文列を追加）
# ──────────────────────────────────────────────

def write_to_sheet(spreadsheet, sheet_name: str, items: list[dict], fetched_at: str, with_body: bool = False):
    try:
        ws = spreadsheet.worksheet(sheet_name)
        ws.clear()
    except gspread.WorksheetNotFound:
        cols = 5 if with_body else 4
        ws = spreadsheet.add_worksheet(sheet_name, rows=500, cols=cols)

    if with_body:
        rows = [["取得日時", "日付", "タイトル", "URL", "本文"]]
        for item in items:
            rows.append([
                fetched_at,
                item.get("date", ""),
                item.get("title", ""),
                item.get("url", ""),
                item.get("body", ""),
            ])
    else:
        rows = [["取得日時", "日付", "タイトル", "URL"]]
        for item in items:
            rows.append([fetched_at, item.get("date",""), item.get("title",""), item.get("url","")])

    ws.update(rows, "A1")
    print(f"  [WRITE] {sheet_name}: {len(items)}件{'（本文あり）' if with_body else ''}")

def write_log(spreadsheet, log_rows: list):
    try:
        ws = spreadsheet.worksheet("取得ログ")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet("取得ログ", rows=1000, cols=5)
        ws.append_row(["取得日時", "シート名", "件数", "ステータス", "エラー"])
    for row in log_rows:
        ws.append_row(row)


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────

async def main():
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== スクレイピング開始: {fetched_at} ===")

    client = get_sheet_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    log_rows = []

    async with AsyncSession() as session:

        # ── 本文不要の3サイト ──
        for sheet_name, fn in [
            ("統合幕僚監部_報道発表",   scrape_js_press),
            ("統合幕僚監部_トピックス", scrape_js_topics),
            ("航空自衛隊_ニュース",     scrape_asdf_news),
        ]:
            print(f"\n[TARGET] {sheet_name}")
            try:
                items = await fn(session)
                if items:
                    write_to_sheet(spreadsheet, sheet_name, items, fetched_at, with_body=False)
                    log_rows.append([fetched_at, sheet_name, len(items), "success", ""])
                else:
                    print("  [WARN] 0件")
                    log_rows.append([fetched_at, sheet_name, 0, "warn", "0件"])
            except Exception as e:
                print(f"  [ERROR] {e}")
                log_rows.append([fetched_at, sheet_name, 0, "error", str(e)])
            await asyncio.sleep(2)

        # ── 本文あり: 防衛省RSS 2件 ──
        for sheet_name, rss_url in [
            ("防衛省_更新情報RSS", "https://www.mod.go.jp/j/rss/update.xml"),
            ("防衛省_ニュースRSS", "https://www.mod.go.jp/j/rss/news.xml"),
        ]:
            print(f"\n[TARGET] {sheet_name}（本文取得あり）")
            try:
                items = await scrape_rss(session, rss_url)
                if items:
                    # 本文取得（上位20件）
                    items = await fetch_bodies_for_rss(session, items, max_items=20)
                    write_to_sheet(spreadsheet, sheet_name, items, fetched_at, with_body=True)
                    log_rows.append([fetched_at, sheet_name, len(items), "success", ""])
                else:
                    print("  [WARN] 0件")
                    log_rows.append([fetched_at, sheet_name, 0, "warn", "0件"])
            except Exception as e:
                print(f"  [ERROR] {e}")
                log_rows.append([fetched_at, sheet_name, 0, "error", str(e)])
            await asyncio.sleep(2)

    # ── Playwright別プロセス ──
    # 九州防衛局は scrape_kyushu.py 側で本文も取得
    for sheet_name, script, with_body in [
        ("九州防衛局_新着", "scrape_kyushu.py",   True),
        ("新富町_新着",     "scrape_shintomi.py",  False),
    ]:
        print(f"\n[TARGET] {sheet_name}")
        try:
            items = run_subprocess(script)
            write_to_sheet(spreadsheet, sheet_name, items, fetched_at, with_body=with_body)
            log_rows.append([fetched_at, sheet_name, len(items), "success", ""])
        except Exception as e:
            print(f"  [ERROR] {e}")
            log_rows.append([fetched_at, sheet_name, 0, "error", str(e)])

    write_log(spreadsheet, log_rows)
    print(f"\n=== スクレイピング完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

if __name__ == "__main__":
    asyncio.run(main())
