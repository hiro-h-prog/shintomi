# -*- coding: utf-8 -*-
"""
九州防衛局 新着情報スクレイパー — Playwright専用（別プロセスで実行）
"""

import asyncio
import re
import sys
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

def extract_date(text: str) -> str:
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', text)
    return m.group(1) if m else ""

async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="ja-JP",
        )
        page = await ctx.new_page()
        await page.goto(
            "https://www.mod.go.jp/rdb/kyushu/index.html",
            wait_until="networkidle",
            timeout=30000,
        )

        body_text = await page.inner_text("body")

        # デバッグ: bodyの最初の部分をstderrに出力
        print(f"[DEBUG] body length: {len(body_text)}", file=sys.stderr)
        print(f"[DEBUG] body preview:\n{body_text[:2000]}", file=sys.stderr)

        await browser.close()

    result = []
    seen = set()
    date_pattern = re.compile(r'\d{4}年\d{1,2}月\d{1,2}日')

    for line in body_text.split("\n"):
        line = line.strip()
        if not date_pattern.search(line):
            continue
        if len(line) < 10 or len(line) > 400:
            continue
        if line in seen:
            continue
        seen.add(line)

        date = extract_date(line)
        title = re.sub(r'^\d{4}年\d{1,2}月\d{1,2}日\s*', '', line).strip()
        m_title = re.search(r'[『「](.+?)[』」]', title)
        if m_title:
            title = m_title.group(1)

        if not title:
            continue

        result.append({"date": date, "title": title[:150], "url": ""})
        if len(result) >= 30:
            break

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(scrape())
