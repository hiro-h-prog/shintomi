import os
import json
import re
import time
import traceback
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ─────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────
JST = timezone(timedelta(hours=9))
NOW_STR = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TARGETS = [
    {
        "sheet": "統合幕僚監部_報道発表",
        "url": "https://www.mod.go.jp/js/press/index.html",
        "selector": "a",
        "filter_href": "/js/press/",
        "base_url": "https://www.mod.go.jp",
        "date_selector": None,
        "cloudflare": True,
    },
    {
        "sheet": "統合幕僚監部_トピックス",
        "url": "https://www.mod.go.jp/js/about/topics.html",
        "selector": "a",
        "filter_href": "/js/",
        "base_url": "https://www.mod.go.jp",
        "date_selector": None,
        "cloudflare": True,
    },
    {
        "sheet": "航空自衛隊_ニュース",
        "url": "https://www.mod.go.jp/asdf/news/",
        "selector": "a",
        "filter_href": "/asdf/news/",
        "base_url": "https://www.mod.go.jp",
        "date_selector": None,
        "cloudflare": True,
    },
    {
        "sheet": "九州防衛局_新着",
        "url": "https://www.mod.go.jp/rdb/kyushu/index.html",
        "selector": "a",
        "filter_href": "/rdb/kyushu/",
        "base_url": "https://www.mod.go.jp",
        "date_selector": None,
        "cloudflare": True,
    },
    {
        "sheet": "新富町_新着",
        "url": "https://www.town.shintomi.lg.jp/news_list.html",
        "selector": "a.newPageLink",
        "filter_href": None,
        "base_url": "https://www.town.shintomi.lg.jp",
        "date_selector": "span.newPageDate",
        "cloudflare": False,
    },
]

# ─────────────────────────────────────────────
# Google Sheets クライアント初期化
# ─────────────────────────────────────────────
def init_gspread():
    service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client

# ─────────────────────────────────────────────
# シート操作ユーティリティ
# ─────────────────────────────────────────────
def get_or_create_sheet(spreadsheet, sheet_name: str):
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        print(f"  [INFO] シート '{sheet_name}' が存在しないため新規作成します")
        return spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)

def ensure_header(sheet):
    header = ["取得日時", "タイトル", "URL", "日付テキスト"]
    existing = sheet.row_values(1)
    if existing != header:
        sheet.insert_row(header, index=1)

def get_existing_urls(sheet) -> set:
    try:
        url_col = sheet.col_values(3)
        return set(url_col[1:]) if len(url_col) > 1 else set()
    except Exception:
        return set()

def append_rows_to_sheet(sheet, rows: list):
    if not rows:
        return
    sheet.append_rows(rows, value_input_option="USER_ENTERED")

# ─────────────────────────────────────────────
# URL正規化
# ─────────────────────────────────────────────
def normalize_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        match = re.match(r"(https?://[^/]+)", base_url)
        domain = match.group(1) if match else base_url
        return domain + href
    return base_url.rstrip("/") + "/" + href.lstrip("./")

# ─────────────────────────────────────────────
# Cloudflare 回避用ブラウザコンテキスト生成
# ─────────────────────────────────────────────
def create_context(browser, cloudflare: bool):
    """
    cloudflare=True の場合は人間らしいヘッダーを付与したコンテキストを返す
    """
    common_args = dict(
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        viewport={"width": 1280, "height": 800},
    )
    if cloudflare:
        return browser.new_context(
            **common_args,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,image/avif,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
    else:
        return browser.new_context(
            **common_args,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

# ─────────────────────────────────────────────
# スクレイピング本体
# ─────────────────────────────────────────────
def scrape_site(browser, target: dict) -> list:
    results = []
    url = target["url"]
    selector = target["selector"]
    base_url = target["base_url"]
    filter_href = target.get("filter_href")
    date_selector = target.get("date_selector")
    cloudflare = target.get("cloudflare", False)

    print(f"  [SCRAPE] {url}")

    context = create_context(browser, cloudflare)
    page = context.new_page()

    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")

        if cloudflare:
            # Cloudflare チャレンジの通過を待つ（最大15秒）
            print(f"    [WAIT] Cloudflare チェック待機中...")
            page.wait_for_timeout(5000)

            # Cloudflare ブロック判定
            content = page.content()
            if "Cloudflare" in content and "セキュリティ" in content:
                print(f"    [WARN] Cloudflare にブロックされました: {url}")
                return []
        else:
            page.wait_for_timeout(2000)

        # 要素取得
        elements = page.query_selector_all(selector)
        print(f"    [HIT] selector='{selector}' → {len(elements)}件")

        seen_urls = set()
        for el in elements:
            try:
                href = el.get_attribute("href") or ""
                title = (el.inner_text() or "").strip()

                # タイトルが短すぎるものを除外
                if not title or len(title) < 4:
                    continue

                abs_url = normalize_url(href, base_url)
                if not abs_url:
                    continue

                # filter_href が指定されている場合はパスでフィルタリング
                if filter_href:
                    if filter_href not in abs_url:
                        continue
                    # インデックスページ自体は除外
                    if abs_url.rstrip("/") == url.rstrip("/"):
                        continue

                if abs_url in seen_urls:
                    continue
                seen_urls.add(abs_url)

                # 日付テキストの取得
                date_text = ""
                if date_selector:
                    # 親要素から date_selector で日付を探す
                    try:
                        parent = el.evaluate_handle(
                            "el => el.closest('li') || el.parentElement"
                        )
                        date_el = parent.as_element().query_selector(date_selector) if parent.as_element() else None
                        if date_el:
                            date_text = (date_el.inner_text() or "").strip()
                    except Exception:
                        pass
                else:
                    # 親要素のテキストから日付パターンを抽出
                    try:
                        parent_text = el.evaluate(
                            "el => el.parentElement ? el.parentElement.innerText : ''"
                        )
                        patterns = [
                            r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}",
                            r"令和\d+年\d+月\d+日",
                            r"R\d+[.\-/]\d{1,2}[.\-/]\d{1,2}",
                            r"\d{4}年\d{1,2}月\d{1,2}日",
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, parent_text)
                            if match:
                                date_text = match.group(0)
                                break
                    except Exception:
                        pass

                results.append({
                    "title": title,
                    "url": abs_url,
                    "date_text": date_text,
                })

            except Exception:
                continue

        print(f"    [RESULT] {len(results)}件取得")

    except PlaywrightTimeoutError:
        print(f"  [WARN] タイムアウト: {url}")
    except Exception:
        print(f"  [ERROR] スクレイピング失敗: {url}\n{traceback.format_exc()}")
    finally:
        page.close()
        context.close()

    return results

# ─────────────────────────────────────────────
# ログシート書き込み
# ─────────────────────────────────────────────
def write_log(spreadsheet, log_rows: list):
    sheet = get_or_create_sheet(spreadsheet, "_log")
    header = ["実行日時", "シート名", "取得件数", "新規件数", "ステータス", "エラー詳細"]
    existing = sheet.row_values(1)
    if existing != header:
        sheet.insert_row(header, index=1)
    if log_rows:
        sheet.append_rows(log_rows, value_input_option="USER_ENTERED")

# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────
def main():
    print(f"=== スクレイピング開始: {NOW_STR} ===")

    gc = init_gspread()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    print(f"[INFO] スプレッドシートを開きました: {SPREADSHEET_ID}")

    log_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        for target in TARGETS:
            sheet_name = target["sheet"]
            print(f"\n[TARGET] {sheet_name}")
            status = "SUCCESS"
            error_detail = ""
            new_count = 0
            total_count = 0

            try:
                sheet = get_or_create_sheet(spreadsheet, sheet_name)
                ensure_header(sheet)
                existing_urls = get_existing_urls(sheet)

                articles = scrape_site(browser, target)
                total_count = len(articles)

                new_rows = []
                for article in articles:
                    if article["url"] not in existing_urls:
                        new_rows.append([
                            NOW_STR,
                            article["title"],
                            article["url"],
                            article["date_text"],
                        ])
                        new_count += 1

                if new_rows:
                    append_rows_to_sheet(sheet, new_rows)
                    print(f"  [WRITE] {new_count}件の新規記事を書き込みました")
                else:
                    print(f"  [SKIP] 新規記事なし")

                # サイト間のアクセス間隔（Cloudflareサイトは長めに待機）
                wait_sec = 5 if target.get("cloudflare") else 2
                time.sleep(wait_sec)

            except Exception as e:
                status = "ERROR"
                error_detail = str(e)
                print(f"  [ERROR] {sheet_name}: {traceback.format_exc()}")

            log_rows.append([
                NOW_STR,
                sheet_name,
                total_count,
                new_count,
                status,
                error_detail,
            ])

        browser.close()

    write_log(spreadsheet, log_rows)
    print(f"\n=== スクレイピング完了: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')} ===")

if __name__ == "__main__":
    main()
