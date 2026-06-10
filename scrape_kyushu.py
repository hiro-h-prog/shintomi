# -*- coding: utf-8 -*-
"""
九州防衛局 新着情報スクレイパー — Playwright専用（別プロセスで実行）
日付と本文が別行になっているため、日付行の次の行をタイトルとして取得する
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

        # URLも取得しておく
        links = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                text: a.innerText.trim().replace(/\\s+/g,' '),
                url: a.href
            })).filter(x => x.text.length > 5)"""
        )
        await browser.close()

    date_pattern = re.compile(r'^\d{4}年\d{1,2}月\d{1,2}日$')
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]

    result = []
    seen = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        # 日付だけの行を検出
        if date_pattern.match(line):
            date = line
            # 次の行がタイトル
            if i + 1 < len(lines):
                title_line = lines[i + 1]
                # 『』「」で囲まれた部分を優先抽出
                m = re.search(r'[『「](.+?)[』」]', title_line)
                title = m.group(1) if m else title_line
                title = title.strip()[:150]

                if title and title not in seen:
                    seen.add(title)
                    # 対応URLをリンクリストから探す
                    url = ""
                    for link in links:
                        if title[:15] in link["text"] or link["text"][:15] in title:
                            if "mod.go.jp/rdb/kyushu" in link["url"]:
                                url = link["url"]
                                break
                    result.append({"date": date, "title": title, "url": url})
            i += 2
        else:
            i += 1
        if len(result) >= 30:
            break

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(scrape())
