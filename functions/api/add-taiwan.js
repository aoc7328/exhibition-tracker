/**
 * Cloudflare Pages Function: api/add-taiwan
 *
 * 輸入「代號 或 公司名」其中一個 → 去公開資訊觀測站 (MOPS) 抓那家公司的
 * 「真實法說會排程」(法人說明會一覽表) → 寫進 Notion(tag 企業 + 持股,綠色)。
 *
 * 取代舊版「推算每月 10 日月營收」(10 號常落在週末/假日,不可靠)。
 *
 * 端點:POST https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1
 *   - co_id=<代號> 查單一公司(回傳很小,~17KB)
 *   - 不帶 co_id 則回整年一覽表(用來由公司名反查代號)
 *
 * 環境變數:NOTION_TOKEN(必填)、NOTION_DATABASE_ID(選填)
 * Body:{ query: "2330" } 或 { query: "台積電" }(也相容舊的 ticker / name 欄位)
 */

const DEFAULT_DATABASE_ID = "87af4c274b834bc3b7018a4597f79153";
const NOTION_VERSION = "2022-06-28";
const CORPORATE_LABEL = "企業";
const HOLDING_LABEL = "持股";

const MOPS_AJAX = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1";
const MOPS_PAGE = "https://mopsov.twse.com.tw/mops/web/t100sb02_1";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === "OPTIONS") return corsPreflightResponse();
  if (request.method !== "POST") {
    return jsonResponse({ error: "method not allowed,只接受 POST" }, 405);
  }

  const notionToken = env.NOTION_TOKEN;
  const dbId = env.NOTION_DATABASE_ID || DEFAULT_DATABASE_ID;
  if (!notionToken) return jsonResponse({ error: "NOTION_TOKEN 未設定" }, 500);

  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid JSON body" }, 400);
  }

  const query = String(body.query || body.ticker || body.name || "").trim();
  if (!query) return jsonResponse({ error: "請輸入代號或公司名" }, 400);

  let found;
  try {
    found = await resolveConferences(query);
  } catch (e) {
    return jsonResponse({ error: `查 MOPS 失敗:${e?.message || e}` }, 502);
  }

  if (!found.ticker) {
    return jsonResponse({
      ok: false,
      error: `找不到「${query}」對應的上市櫃公司,請確認代號或公司簡稱`,
    });
  }
  if (found.events.length === 0) {
    return jsonResponse({
      ok: false,
      ticker: found.ticker,
      name: found.name,
      error: `已對到 ${found.name}(${found.ticker}),但近期沒有排定中的法說會`,
    });
  }

  let written = 0;
  let writeError = null;
  try {
    written = await writeConferences(notionToken, dbId, found);
  } catch (e) {
    writeError = e?.message || String(e);
  }

  return jsonResponse({
    ok: !writeError,
    ticker: found.ticker,
    name: found.name,
    written,
    writeError,
  });
}

/* ---------- MOPS 抓法說會 ---------- */

async function resolveConferences(query) {
  const isTicker = /^[0-9]{3,6}[A-Z]?$/i.test(query);
  const rocNow = new Date().getFullYear() - 1911;

  let ticker = isTicker ? query.toUpperCase() : null;
  let name = null;

  // 若輸入的是公司名 → 先用整年一覽表反查代號(indexOf,不全文 regex,省 CPU)
  if (!ticker) {
    for (const typek of ["sii", "otc"]) {
      const html = await fetchMops({ TYPEK: typek, year: rocNow });
      const hit = findTickerByName(html, query);
      if (hit) {
        ticker = hit.ticker;
        name = hit.name;
        break;
      }
    }
    if (!ticker) return { ticker: null, name: null, events: [] };
  }

  // 用 co_id 查單一公司(小)— 當年 + 隔年、上市 + 上櫃
  const today = startOfToday();
  const seen = new Set();
  const events = [];
  for (const year of [rocNow, rocNow + 1]) {
    for (const typek of ["sii", "otc"]) {
      let html;
      try {
        html = await fetchMops({ TYPEK: typek, co_id: ticker, year });
      } catch {
        continue;
      }
      for (const row of parseRows(html)) {
        if (row.ticker !== ticker) continue;
        if (!name) name = row.name;
        if (row.date < today) continue;
        const key = isoDate(row.date);
        if (seen.has(key)) continue;
        seen.add(key);
        events.push(row.date);
      }
    }
  }
  events.sort((a, b) => a - b);
  return { ticker, name: name || ticker, events };
}

async function fetchMops({ TYPEK, year, co_id }) {
  const params = new URLSearchParams({
    encodeURIComponent: "1",
    step: "1",
    firstin: "1",
    off: "1",
    TYPEK,
    year: String(year),
    month: "",
  });
  if (co_id) params.set("co_id", co_id);
  const resp = await fetch(MOPS_AJAX, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": UA,
    },
    body: params.toString(),
  });
  if (!resp.ok) throw new Error(`MOPS HTTP ${resp.status}`);
  return await resp.text();
}

// 整年一覽表 → 用公司名反查代號(找到名字所在,往前抓最近的代號 cell)
function findTickerByName(html, name) {
  const idx = html.indexOf(name);
  if (idx < 0) return null;
  const before = html.slice(Math.max(0, idx - 400), idx);
  const tickers = [...before.matchAll(/<td[^>]*>\s*([0-9]{3,6}[A-Z]?)\s*<\/td>/gi)];
  if (!tickers.length) return null;
  return { ticker: tickers[tickers.length - 1][1].toUpperCase(), name };
}

// 解析 co_id 小回應的表格列 → [{ ticker, name, date }]
function parseRows(html) {
  const rows = [];
  const trRe = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
  let tr;
  while ((tr = trRe.exec(html))) {
    const cells = [];
    const tdRe = /<td[^>]*>([\s\S]*?)<\/td>/gi;
    let td;
    while ((td = tdRe.exec(tr[1]))) {
      cells.push(td[1].replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim());
    }
    if (cells.length < 3) continue;
    const ticker = cells[0];
    if (!/^[0-9]{3,6}[A-Z]?$/i.test(ticker)) continue;
    const date = rocToDate(cells[2]); // 取起始日(含「至」區間時也取前者)
    if (date) rows.push({ ticker: ticker.toUpperCase(), name: cells[1], date });
  }
  return rows;
}

function rocToDate(s) {
  const m = /(\d{2,3})\/(\d{1,2})\/(\d{1,2})/.exec(s);
  if (!m) return null;
  const d = new Date(parseInt(m[1]) + 1911, parseInt(m[2]) - 1, parseInt(m[3]));
  d.setHours(0, 0, 0, 0);
  return isNaN(d.getTime()) ? null : d;
}

/* ---------- 寫 Notion 法說會 ---------- */

async function writeConferences(token, dbId, found) {
  const { ticker, name, events } = found;
  const tags = [CORPORATE_LABEL, HOLDING_LABEL];
  let written = 0;
  for (const date of events) {
    const iso = isoDate(date);
    const title = `${name}(${ticker}) 法說會（${date.getMonth() + 1}/${date.getDate()}）`;
    const resp = await fetch("https://api.notion.com/v1/pages", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        parent: { database_id: dbId },
        properties: {
          展覽名稱: { title: [{ text: { content: title } }] },
          開始日期: { date: { start: iso } },
          結束日期: { date: { start: iso } },
          地點: { select: { name: "臺灣" } },
          狀態: { select: { name: "已確認" } },
          信心度: { select: { name: "🟢 高" } },
          來源層次: { select: { name: "白名單" } },
          產業類別: { multi_select: tags.map((n) => ({ name: n })) },
          主辦單位: { rich_text: [{ text: { content: name } }] },
          官方網址: { url: MOPS_PAGE },
        },
      }),
    });
    if (resp.ok) written++;
  }
  return written;
}

/* ---------- Utility ---------- */

function startOfToday() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

function isoDate(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, no-cache, must-revalidate",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function corsPreflightResponse() {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    },
  });
}
