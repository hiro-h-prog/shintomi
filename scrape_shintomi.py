# -*- coding: utf-8 -*-
"""
新富町スクレイパー — Playwright専用（別プロセスで実行）
scrape.py から subprocess で呼び出される
結果はJSON形式で stdout に出力する
"""

import asyncio
import re
import sys
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="ja-JP",
        )
        page = await ctx.new_page()
        await page.goto("https://www.town.shintomi.lg.jp/news_list.html",
                        wait_until="networkidle", timeout=30000)
        items = await page.eval_on_selector_all(
            "a.newPageLink",
            """els => els.map(a => ({
                title: a.innerText.trim().replace(/\\s+/g,' '),
                url: a.href
            })).filter(x => x.title.length > 5)"""
        )
        await browser.close()

    result = []
    for item in items[:50]:
        m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2})', item["title"])
        result.append({
            "date":  m.group(1) if m else "",
            "title": item["title"][:150],
            "url":   item["url"],
        })
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(scrape())
