# -*- coding: utf-8 -*-
"""
防衛関連サイト スクレイピング → Google Sheets 書き込み
GitHub Actions セルフホストランナー（Windows）から実行する

mod.go.jp … curl_cffi で Cloudflare を回避（SelectorEventLoop必須）
新富町    … scrape_shintomi.py を別プロセスで呼び出し（PlaywrightはProactorEventLoop必須）
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

# Windows: 文字化け対策 + curl_cffi 用に SelectorEventLoop を設定
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

def get_sheet_client():
    creds_data = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    return gspread.authorize(creds)


# ──────────────────────────────────────────────
# mod.go.jp 系: curl_cffi で Cloudflare を回避
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

async def scrape_js_press(session: AsyncSession) -> list[dict]:
    """統合幕僚監部 報道発表資料"""
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
        result.append({
            "date":  extract_date(text),
            "title": re.sub(r'^\d{4}年\d{1,2}月\d{1,2}日\s*(公表\s*)?', '', text).strip()[:150],
            "url":   url,
        })
    return result[:50]

async def scrape_js_topics(session: AsyncSession) -> list[dict]:
    """統合幕僚監部 出来事（トピックス）"""
    soup = await fetch_html(session, "https://www.mod.go.jp/js/about/topics.html")
    if not soup:
        return []
    result = []
    for tag in soup.select("li, p, dt, dd"):
        text = tag.get_text(" ", strip=True)
        if len(text) < 15 or len(text) > 300:
            continue
        a = tag.find("a")
        href = a["href"] if a and a.get("href") else ""
        url = ("https://www.mod.go.jp" + href) if href and not href.startswith("http") else href
        result.append({"date": extract_date(text), "title": text[:150], "url": url})
        if len(result) >= 30:
            break
    return result

async def scrape_asdf_news(session: AsyncSession) -> list[dict]:
    """航空自衛隊 ニュース"""
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
        result.append({"date": extract_date(text), "title": text[:150], "url": url})
    return result[:50]

async def scrape_kyushu_rdb(session: AsyncSession) -> list[dict]:
    """九州防衛局 新着情報"""
    soup = await fetch_html(session, "https://www.mod.go.jp/rdb/kyushu/index.html")
    if not soup:
        return []
    result = []
    for a in soup.select("a[href]")[:150]:
        href = a.get("href", "")
        if "/rdb/kyushu" not in href and "/rdb/" not in href:
            continue
        text = a.get_text(" ", strip=True)
        if len(text) < 6 or text in ("トップ", "ホーム", "サイトマップ", "English"):
            continue
        url = href if href.startswith("http") else "https://www.mod.go.jp" + href
        clean = re.sub(r'^\d{4}[年.]\d{1,2}[月.]\d{1,2}日?\s*', '', text).strip()
        result.append({"date": extract_date(text), "title": clean[:150], "url": url})
    if not result:
        for a in soup.select("a[href]")[:200]:
            href = a.get("href", "")
            if not href or href.startswith("#") or href.startswith("mailto"):
                continue
            text = a.get_text(" ", strip=True)
            if len(text) < 10:
                continue
            url = href if href.startswith("http") else "https://www.mod.go.jp" + href
            result.append({"date": extract_date(text), "title": text[:150], "url": url})
            if len(result) >= 30:
                break
    return result[:50]


# ──────────────────────────────────────────────
# 新富町: 別プロセス（scrape_shintomi.py）で実行
# PlaywrightはProactorEventLoopが必要なため分離
# ──────────────────────────────────────────────

def scrape_shintomi_subprocess() -> list[dict]:
    """scrape_shintomi.py を別プロセスで実行してJSONを受け取る"""
    script = os.path.join(os.path.dirname(__file__), "scrape_shintomi.py")
    proc = subprocess.run(
        [sys.executable, script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"scrape_shintomi.py failed:\n{proc.stderr}")
    return json.loads(proc.stdout.strip())


# ──────────────────────────────────────────────
# Sheets 書き込み
# ──────────────────────────────────────────────

def write_to_sheet(spreadsheet, sheet_name: str, items: list[dict], fetched_at: str):
    try:
        ws = spreadsheet.worksheet(sheet_name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(sheet_name, rows=500, cols=4)
    rows = [["取得日時", "日付", "タイトル", "URL"]]
    for item in items:
        rows.append([fetched_at, item.get("date",""), item.get("title",""), item.get("url","")])
    ws.update(rows, "A1")
    print(f"  [WRITE] {sheet_name}: {len(items)}件")

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

    # curl_cffi で mod.go.jp 4サイト
    async with AsyncSession() as session:
        mod_scrapers = [
            ("統合幕僚監部_報道発表",   scrape_js_press),
            ("統合幕僚監部_トピックス", scrape_js_topics),
            ("航空自衛隊_ニュース",     scrape_asdf_news),
            ("九州防衛局_新着",         scrape_kyushu_rdb),
        ]
        for sheet_name, fn in mod_scrapers:
            print(f"\n[TARGET] {sheet_name}")
            try:
                items = await fn(session)
                if items:
                    write_to_sheet(spreadsheet, sheet_name, items, fetched_at)
                    log_rows.append([fetched_at, sheet_name, len(items), "success", ""])
                else:
                    print("  [WARN] 0件")
                    log_rows.append([fetched_at, sheet_name, 0, "warn", "0件"])
            except Exception as e:
                print(f"  [ERROR] {e}")
                log_rows.append([fetched_at, sheet_name, 0, "error", str(e)])
            await asyncio.sleep(2)

    # 新富町: 別プロセスで実行
    print(f"\n[TARGET] 新富町_新着")
    try:
        items = scrape_shintomi_subprocess()
        write_to_sheet(spreadsheet, "新富町_新着", items, fetched_at)
        log_rows.append([fetched_at, "新富町_新着", len(items), "success", ""])
    except Exception as e:
        print(f"  [ERROR] {e}")
        log_rows.append([fetched_at, "新富町_新着", 0, "error", str(e)])

    write_log(spreadsheet, log_rows)
    print(f"\n=== スクレイピング完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

if __name__ == "__main__":
    asyncio.run(main())
