/**
 * 防衛関連情報 スプレッドシート読み取りAPI v2
 * - 前回Difyに送信した日時を「送信ログ」シートに記録
 * - 次回以降は新規データのみ返す
 *
 * デプロイ:「デプロイ」→「新しいデプロイ」→「ウェブアプリ」
 * 実行ユーザー: 自分 ／ アクセス: 全員
 */

const SPREADSHEET_ID = "1QO0alKXYlWJVY9S8SlFCDSXmlOVrgSx7cgA2XiNZJwg";

const SHEET_NAMES = [
  "統合幕僚監部_報道発表",
  "統合幕僚監部_トピックス",
  "航空自衛隊_ニュース",
  "九州防衛局_新着",
  "新富町_新着",
  "防衛省_更新情報RSS",
  "防衛省_ニュースRSS",
];

// 送信ログシート名
const SEND_LOG_SHEET = "Dify送信ログ";

function doGet(e) {
  const p = e.parameter;
  const action = p.action || "new_only";
  let result;

  try {
    if (action === "new_only") {
      // 新規データのみ返してログを記録（Difyのデフォルト呼び出し）
      result = getNewItemsAndLog(parseInt(p.rows) || 20);
    } else if (action === "summary") {
      // 全データのサマリー（件数確認用・ログ記録なし）
      result = getSummary(parseInt(p.rows) || 10);
    } else if (action === "send_log") {
      // 送信ログを確認
      result = getSendLog(parseInt(p.rows) || 20);
    } else if (action === "reset") {
      // 送信ログをリセット（全データを再送したい場合）
      result = resetSendLog();
    } else {
      result = { error: "不明なaction: " + action };
    }
  } catch (err) {
    result = { error: err.toString() };
  }

  return ContentService
    .createTextOutput(JSON.stringify(result, null, 2))
    .setMimeType(ContentService.MimeType.JSON);
}


/**
 * 前回送信日時以降の新規データのみ返し、送信ログを記録する
 */
function getNewItemsAndLog(maxRows) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sentAt = new Date().toISOString();

  // 送信ログシートを取得または作成
  let logSheet = ss.getSheetByName(SEND_LOG_SHEET);
  if (!logSheet) {
    logSheet = ss.insertSheet(SEND_LOG_SHEET);
    logSheet.appendRow(["送信日時", "シート名", "件数", "最新データ日付"]);
  }

  // 前回の送信日時を取得（シートごとに最後の送信日時を管理）
  const lastSentMap = getLastSentMap(logSheet);

  const results = [];
  let totalNew = 0;

  for (const name of SHEET_NAMES) {
    const sheet = ss.getSheetByName(name);
    if (!sheet) continue;

    const data = sheet.getDataRange().getValues();
    if (data.length < 2) continue;

    // ヘッダー行をスキップしてデータ取得
    // カラム: [取得日時, 日付, タイトル, URL]
    const lastSent = lastSentMap[name] || null;

    const newItems = [];
    for (let i = 1; i < data.length; i++) {
      const row = data[i];
      const fetchedAt = row[0] ? String(row[0]) : "";
      const title = row[2] ? String(row[2]) : "";

      if (!title || title === "取得日時") continue;

      // 前回送信日時より新しいデータのみ
      if (lastSent && fetchedAt <= lastSent) continue;

      newItems.push({
        fetched_at: fetchedAt,
        date:       row[1] ? String(row[1]) : "",
        title:      title,
        url:        row[3] ? String(row[3]) : "",
      });

      if (newItems.length >= maxRows) break;
    }

    // 送信ログに記録
    const latestDate = newItems.length > 0 ? newItems[0].date : "";
    logSheet.appendRow([sentAt, name, newItems.length, latestDate]);

    totalNew += newItems.length;
    results.push({ sheet: name, new_count: newItems.length, items: newItems });
  }

  // Difyが読みやすいフラットテキストも生成
  const text = results
    .filter(s => s.items.length > 0)
    .map(s =>
      `【${s.sheet}】（${s.new_count}件の新着）\n` +
      s.items.map(i => `${i.date} ${i.title} ${i.url}`).join("\n")
    ).join("\n\n");

  return {
    sent_at:   sentAt,
    total_new: totalNew,
    has_new:   totalNew > 0,
    sheets:    results,
    text:      text || "新規データはありません。",
  };
}


/**
 * 送信ログからシートごとの最終送信日時を取得
 */
function getLastSentMap(logSheet) {
  const data = logSheet.getDataRange().getValues();
  const map = {};

  // 最新順に走査してシートごとの最終送信日時を取得
  for (let i = data.length - 1; i >= 1; i--) {
    const sentAt  = String(data[i][0]);
    const sheetName = String(data[i][1]);
    if (!map[sheetName]) {
      map[sheetName] = sentAt;
    }
  }
  return map;
}


/**
 * 全データのサマリー（件数確認用・ログ記録なし）
 */
function getSummary(maxRows) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const summary = [];

  for (const name of SHEET_NAMES) {
    const sheet = ss.getSheetByName(name);
    if (!sheet) continue;
    const data = sheet.getDataRange().getValues();
    const rows = data.slice(1, maxRows + 1).map(r => ({
      fetched_at: String(r[0] || ""),
      date:       String(r[1] || ""),
      title:      String(r[2] || ""),
      url:        String(r[3] || ""),
    })).filter(r => r.title && r.title !== "取得日時");

    summary.push({ sheet: name, items: rows });
  }

  const text = summary.map(s =>
    `【${s.sheet}】\n` +
    s.items.map(i => `${i.date} ${i.title} ${i.url}`).join("\n")
  ).join("\n\n");

  return { fetched_at: new Date().toISOString(), sheets: summary, text };
}


/**
 * 送信ログの確認
 */
function getSendLog(maxRows) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SEND_LOG_SHEET);
  if (!sheet) return { error: "送信ログシートがまだありません" };

  const data = sheet.getDataRange().getValues();
  const logs = data.slice(1).reverse().slice(0, maxRows).map(r => ({
    sent_at:     String(r[0] || ""),
    sheet:       String(r[1] || ""),
    count:       r[2] || 0,
    latest_date: String(r[3] || ""),
  }));

  return { fetched_at: new Date().toISOString(), logs };
}


/**
 * 送信ログをリセット（全データを再送したい場合）
 */
function resetSendLog() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = ss.getSheetByName(SEND_LOG_SHEET);
  if (sheet) {
    sheet.clearContents();
    sheet.appendRow(["送信日時", "シート名", "件数", "最新データ日付"]);
  }
  return { result: "送信ログをリセットしました" };
}
