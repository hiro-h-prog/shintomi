# -*- coding: utf-8 -*-
"""
九州防衛局 新着情報スクレイパー — Playwright専用（別プロセスで実行）
トップページの新着セクションからタイトル・日付・説明文を取得する。
個別ページはCloudflareブロックのためアクセスしない。
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
        links = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                text: a.innerText.trim().replace(/\\s+/g,' '),
                url: a.href
            })).filter(x => x.text.length > 5)"""
        )
        await browser.close()

    # 日付だけの行を検出し、次の行をタイトル、その次の行を説明文として取得
    date_pattern = re.compile(r'^\d{4}年\d{1,2}月\d{1,2}日$')
    # 「〜のページを更新しました」「〜を掲載しました」のような説明文パターン
    desc_pattern = re.compile(r'(しました|について|のお知らせ|のご案内|公告|公開|掲載|更新)。?$')

    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
    result = []
    seen = set()
    i = 0

    while i < len(lines) and len(result) < 30:
        line = lines[i]
        if date_pattern.match(line):
            date = line
            title = ""
            body = ""

            if i + 1 < len(lines):
                title_line = lines[i + 1]
                # 『』「」で囲まれた部分を優先抽出
                m = re.search(r'[『「](.+?)[』」]', title_line)
                title = m.group(1) if m else title_line
                title = title.strip()[:150]

                # 次の次の行が説明文っぽければ本文として使う
                if i + 2 < len(lines):
                    next_line = lines[i + 2]
                    # 次の行が日付でなく、説明文パターンにマッチすれば本文に
                    if not date_pattern.match(next_line) and (
                        desc_pattern.search(next_line) or len(next_line) > 20
                    ):
                        body = next_line[:300]

            if title and title not in seen and len(title) >= 6:
                seen.add(title)
                # URLをリンクリストから探す
                url = ""
                for link in links:
                    if title[:15] in link["text"] or link["text"][:15] in title:
                        if "mod.go.jp/rdb/kyushu" in link["url"]:
                            url = link["url"]
                            break

                if url or len(title) >= 15:
                    result.append({
                        "date":  date,
                        "title": title,
                        "url":   url,
                        "body":  body,
                    })
            i += 2
        else:
            i += 1

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(scrape())
