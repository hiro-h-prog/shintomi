# -*- coding: utf-8 -*-
"""
九州防衛局 新着情報スクレイパー — Playwright専用（別プロセスで実行）
本文も取得してJSONで返す
"""

import asyncio
import re
import sys
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

NOISE_SELECTORS = ["header", "footer", "nav", ".breadcrumb", ".side", "#side", ".menu", "#menu", "script", "style"]

def extract_date(text: str) -> str:
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', text)
    return m.group(1) if m else ""

async def fetch_body_playwright(page, url: str) -> str:
    """Playwrightで本文を取得"""
    if not url or url.endswith(".pdf"):
        return ""
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        # ノイズ要素を非表示化
        for sel in NOISE_SELECTORS:
            await page.evaluate(f"""
                document.querySelectorAll('{sel}').forEach(el => el.remove())
            """)
        # メインコンテンツを優先取得
        for sel in ["main", "#main", ".main", "#content", ".content", "article"]:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.inner_text()
                text = re.sub(r'\n{3,}', '\n\n', text.strip())
                if len(text) > 100:
                    return text[:1000]
        text = await page.inner_text("body")
        return re.sub(r'\n{3,}', '\n\n', text.strip())[:1000]
    except Exception as e:
        return ""

async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="ja-JP",
        )

        # トップページで新着一覧を取得
        page = await ctx.new_page()
        await page.goto(
            "https://www.mod.go.jp/rdb/kyushu/index.html",
            wait_until="networkidle",
            timeout=30000,
        )
        body_text = await page.inner_text("body")
        links = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                text: a.innerText.trim().replace(/\\s+/g,' '),
                url: a.href
            })).filter(x => x.text.length > 5)"""
        )
        await page.close()

        # 新着一覧をパース
        date_pattern = re.compile(r'^\d{4}年\d{1,2}月\d{1,2}日$')
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        result = []
        seen = set()
        i = 0
        while i < len(lines) and len(result) < 30:
            line = lines[i]
            if date_pattern.match(line):
                date = line
                if i + 1 < len(lines):
                    title_line = lines[i + 1]
                    m = re.search(r'[『「](.+?)[』」]', title_line)
                    title = m.group(1) if m else title_line
                    title = title.strip()[:150]
                    if title and title not in seen and len(title) >= 6:
                        seen.add(title)
                        url = ""
                        for link in links:
                            if title[:15] in link["text"] or link["text"][:15] in title:
                                if "mod.go.jp/rdb/kyushu" in link["url"]:
                                    url = link["url"]
                                    break
                        if url or len(title) >= 15:
                            result.append({"date": date, "title": title, "url": url, "body": ""})
                i += 2
            else:
                i += 1

        # 本文取得（上位15件・URLありのみ）
        body_page = await ctx.new_page()
        fetch_count = 0
        for item in result:
            if fetch_count >= 15:
                break
            if item["url"]:
                print(f"  [BODY] {fetch_count+1} {item['url'][:60]}", file=sys.stderr)
                item["body"] = await fetch_body_playwright(body_page, item["url"])
                fetch_count += 1
                await asyncio.sleep(1)
        await body_page.close()
        await browser.close()

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(scrape())
