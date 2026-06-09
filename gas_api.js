/**
 * 防衛関連情報 スプレッドシート読み取りAPI
 * Google Apps Script — Difyの「HTTPリクエスト」ノードから呼び出す
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
];

function doGet(e) {
  const p = e.parameter;
  const action = p.action || "summary";
  let result;

  try {
    if (action === "summary") {
      // 全シートの最新N件をまとめて返す（Difyのデフォルト呼び出し）
      result = getSummary(parseInt(p.rows) || 10);
    } else if (action === "sheet") {
      // 特定シートの全データを返す
      result = getSheet(p.name, parseInt(p.rows) || 30);
    } else if (action === "log") {
      result = getLog(parseInt(p.rows) || 20);
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

/** 全シートの最新N件をまとめて返す */
function getSummary(maxRows) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const summary = [];

  for (const name of SHEET_NAMES) {
    const sheet = ss.getSheetByName(name);
    if (!sheet) continue;

    const data = sheet.getDataRange().getValues();
    // 1行目はヘッダー、2行目以降がデータ
    const rows = data.slice(1, maxRows + 1).map(r => ({
      fetched_at: r[0] || "",
      date:       r[1] || "",
      title:      r[2] || "",
      url:        r[3] || "",
    })).filter(r => r.title);

    summary.push({ sheet: name, items: rows });
  }

  // Difyが読みやすいフラットテキストも付加
  const text = summary.map(s =>
    `【${s.sheet}】\n` +
    s.items.map(i => `${i.date} ${i.title} ${i.url}`).join("\n")
  ).join("\n\n");

  return {
    fetched_at: new Date().toISOString(),
    sheets: summary,
    text,
  };
}

/** 特定シートのデータを返す */
function getSheet(name, maxRows) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(name);
  if (!sheet) return { error: "シートが見つかりません: " + name };

  const data = sheet.getDataRange().getValues();
  const items = data.slice(1, maxRows + 1).map(r => ({
    fetched_at: r[0] || "",
    date:       r[1] || "",
    title:      r[2] || "",
    url:        r[3] || "",
  })).filter(r => r.title);

  return {
    sheet_name: name,
    fetched_at: new Date().toISOString(),
    total: items.length,
    items,
    text: items.map(i => `${i.date} ${i.title} ${i.url}`).join("\n"),
  };
}

/** 取得ログを返す */
function getLog(maxRows) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName("取得ログ");
  if (!sheet) return { error: "取得ログシートがありません" };

  const data = sheet.getDataRange().getValues();
  const logs = data.slice(1).reverse().slice(0, maxRows).map(r => ({
    fetched_at:  r[0] || "",
    sheet:       r[1] || "",
    count:       r[2] || 0,
    status:      r[3] || "",
    error:       r[4] || "",
  }));

  return { fetched_at: new Date().toISOString(), logs };
}
