# -*- coding: utf-8 -*-
"""
九州防衛局 新着情報スクレイパー — Playwright専用（別プロセスで実行）
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

        # 新着情報セクションを取得
        # 「ここから新着情報です」のアンカー以降の要素を対象にする
        items_raw = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => {
                const text = a.innerText.trim().replace(/\\s+/g, ' ');
                return { title: text, url: a.href };
            }).filter(x => x.title.length > 5)"""
        )

        # ページ全体テキストから日付行を抽出（JSレンダリング後）
        body_text = await page.inner_text("body")
        await browser.close()

    result = []
    seen = set()
    date_pattern = re.compile(r'(\d{4}年\d{1,2}月\d{1,2}日)')

    # 日付を含む行を抽出
    for line in body_text.split("\n"):
        line = line.strip()
        if not date_pattern.search(line):
            continue
        if len(line) < 15 or len(line) > 300:
            continue
        if line in seen:
            continue
        seen.add(line)

        date = extract_date(line)
        title = re.sub(r'^\d{4}年\d{1,2}月\d{1,2}日\s*', '', line).strip()
        # 『』で囲まれたタイトル部分を優先抽出
        m = re.search(r'[『「](.+?)[』」]', title)
        if m:
            title = m.group(1)

        # 対応するURLをリンクリストから探す
        url = ""
        for item in items_raw:
            if title[:20] in item["title"] or item["title"][:20] in title:
                url = item["url"]
                break

        result.append({"date": date, "title": title[:150], "url": url})
        if len(result) >= 30:
            break

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(scrape())
