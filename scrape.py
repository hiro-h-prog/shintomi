"""
防衛関連サイト スクレイピング → Google Sheets 書き込み
GitHub Actions から実行する
"""

import asyncio
import os
import re
import json
from datetime import datetime
from playwright.async_api import async_playwright, Page
from google.oauth2.service_account import Credentials
import gspread

# ──────────────────────────────
# Google Sheets 設定
# ──────────────────────────────
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

def get_sheet_client():
    creds_data = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    return gspread.authorize(creds)


# ──────────────────────────────
# サイト別スクレイパー
# ──────────────────────────────

async def scrape_js_press(page: Page) -> list[dict]:
    """統合幕僚監部 報道発表資料"""
    await page.goto("https://www.mod.go.jp/js/press/index.html",
                    wait_until="networkidle", timeout=30000)
    items = await page.eval_on_selector_all(
        "ul li a[href*='/js/pdf/'], ul li a[href*='/js/press/']",
        """els => els.map(a => {
            const text = a.innerText.trim().replace(/\\s+/g, ' ');
            return { title: text, url: a.href };
        }).filter(x => x.title.length > 5)"""
    )
    # 日付をタイトルから抽出して整形
    result = []
    for item in items[:50]:
        m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', item["title"])
        result.append({
            "date":  m.group(1) if m else "",
            "title": re.sub(r'^\d{4}年\d{1,2}月\d{1,2}日\s*(公表\s*)?', '', item["title"]).strip(),
            "url":   item["url"],
        })
    return result


async def scrape_js_topics(page: Page) -> list[dict]:
    """統合幕僚監部 出来事（トピックス）"""
    await page.goto("https://www.mod.go.jp/js/about/topics.html",
                    wait_until="networkidle", timeout=30000)
    # 見出し＋本文ブロック構造を取得
    blocks = await page.eval_on_selector_all(
        ".topics-list li, article, .news-item, section p, .content li",
        "els => els.map(e => e.innerText.trim().replace(/\\s+/g,' ').slice(0,200))"
        ".filter(t => t.length > 10)"
    )
    if not blocks:
        # フォールバック：全テキストから段落を抽出
        body = await page.inner_text("body")
        blocks = [p.strip() for p in body.split("\n") if len(p.strip()) > 20][:40]

    return [{"date": "", "title": b[:150], "url": ""} for b in blocks[:30]]


async def scrape_asdf_news(page: Page) -> list[dict]:
    """航空自衛隊 ニュース"""
    await page.goto("https://www.mod.go.jp/asdf/news/",
                    wait_until="networkidle", timeout=30000)
    items = await page.eval_on_selector_all(
        "a[href]",
        """els => els.map(a => ({
            title: a.innerText.trim().replace(/\\s+/g,' '),
            url: a.href
        })).filter(x =>
            x.title.length > 5 &&
            (x.url.includes('/asdf/news') || x.url.includes('/asdf/pdf'))
        )"""
    )
    result = []
    for item in items[:50]:
        m = re.search(r'(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2})', item["title"])
        result.append({
            "date":  m.group(1) if m else "",
            "title": item["title"][:150],
            "url":   item["url"],
        })
    return result


async def scrape_kyushu_rdb(page: Page) -> list[dict]:
    """九州防衛局 新着情報"""
    await page.goto("https://www.mod.go.jp/rdb/kyushu/index.html",
                    wait_until="networkidle", timeout=30000)
    items = await page.eval_on_selector_all(
        "a[href]",
        """els => els.map(a => ({
            title: a.innerText.trim().replace(/\\s+/g,' '),
            url: a.href
        })).filter(x =>
            x.title.length > 5 &&
            x.url.includes('/rdb/kyushu')
        )"""
    )
    result = []
    for item in items[:50]:
        m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}\.\d{1,2}\.\d{1,2})', item["title"])
        result.append({
            "date":  m.group(1) if m else "",
            "title": re.sub(r'^\d{4}[年.]\d{1,2}[月.]\d{1,2}日?\s*', '', item["title"]).strip()[:150],
            "url":   item["url"],
        })
    return result


async def scrape_shintomi(page: Page) -> list[dict]:
    """新富町 新着情報"""
    await page.goto("https://www.town.shintomi.lg.jp/news_list.html",
                    wait_until="networkidle", timeout=30000)
    items = await page.eval_on_selector_all(
        ".news-list a, .list-news a, table.news a, dl a, .info-list a, a[href*='/life/'], a[href*='/topics/']",
        """els => els.map(a => ({
            title: a.innerText.trim().replace(/\\s+/g,' '),
            url: a.href
        })).filter(x => x.title.length > 5)"""
    )
    if not items:
        # フォールバック：全リンクから町のページを抽出
        items = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                title: a.innerText.trim().replace(/\\s+/g,' '),
                url: a.href
            })).filter(x =>
                x.title.length > 8 &&
                x.url.includes('shintomi.lg.jp') &&
                !x.url.includes('index.html') &&
                !x.url.match(/\\.(png|jpg|pdf)$/)
            )"""
        )
    result = []
    for item in items[:50]:
        m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[/\-]\d{1,2}[/\-]\d{1,2})', item["title"])
        result.append({
            "date":  m.group(1) if m else "",
            "title": item["title"][:150],
            "url":   item["url"],
        })
    return result


# ──────────────────────────────
# スクレイパー定義テーブル
# ──────────────────────────────
SCRAPERS = [
    {"sheet": "統合幕僚監部_報道発表",   "fn": scrape_js_press},
    {"sheet": "統合幕僚監部_トピックス", "fn": scrape_js_topics},
    {"sheet": "航空自衛隊_ニュース",     "fn": scrape_asdf_news},
    {"sheet": "九州防衛局_新着",         "fn": scrape_kyushu_rdb},
    {"sheet": "新富町_新着",             "fn": scrape_shintomi},
]


# ──────────────────────────────
# Sheets 書き込み
# ──────────────────────────────
def write_to_sheet(spreadsheet, sheet_name: str, items: list[dict], fetched_at: str):
    try:
        ws = spreadsheet.worksheet(sheet_name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(sheet_name, rows=500, cols=4)

    rows = [["取得日時", "日付", "タイトル", "URL"]]
    for item in items:
        rows.append([fetched_at, item.get("date",""), item.get("title",""), item.get("url","")])
    ws.update("A1", rows)
    print(f"  → {sheet_name}: {len(items)}件 書き込み完了")


def write_log(spreadsheet, log_rows: list):
    try:
        ws = spreadsheet.worksheet("取得ログ")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet("取得ログ", rows=1000, cols=5)
        ws.append_row(["取得日時", "シート名", "件数", "ステータス", "エラー"])
    for row in log_rows:
        ws.append_row(row)


# ──────────────────────────────
# メイン
# ──────────────────────────────
async def main():
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{fetched_at}] スクレイピング開始")

    client = get_sheet_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    log_rows = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )

        for scraper in SCRAPERS:
            sheet_name = scraper["sheet"]
            print(f"\n[{sheet_name}] 取得中...")
            page = await ctx.new_page()
            try:
                items = await scraper["fn"](page)
                write_to_sheet(spreadsheet, sheet_name, items, fetched_at)
                log_rows.append([fetched_at, sheet_name, len(items), "success", ""])
            except Exception as e:
                print(f"  エラー: {e}")
                log_rows.append([fetched_at, sheet_name, 0, "error", str(e)])
            finally:
                await page.close()
            await asyncio.sleep(2)

        await browser.close()

    write_log(spreadsheet, log_rows)
    print(f"\n完了: {fetched_at}")


if __name__ == "__main__":
    asyncio.run(main())
