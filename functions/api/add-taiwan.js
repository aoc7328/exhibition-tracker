/**
 * Cloudflare Pages Function: api/add-taiwan
 *
 * 接收前端輸入的台股公司,只寫進 Notion(12 筆月營收)。
 * 不再 commit yaml — 持股常變動,不做長期追蹤。
 *
 * 不做的事:
 *   - 寫 yaml(長期追蹤清單)
 *   - 季度法說會(要 Claude CLI,本機跑 add_taiwan_company.py)
 *   - .ics 重產 + push gh-pages(本機跑 run_ics_only.bat)
 *
 * 環境變數:
 *   NOTION_TOKEN          (必填)
 *   NOTION_DATABASE_ID    (選填,預設展覽追蹤 DB)
 *
 * Body:
 *   { ticker: "2454", name: "聯發科", industries: ["AI", "半導體", "5G/6G"] }
 */

const DEFAULT_DATABASE_ID = "87af4c274b834bc3b7018a4597f79153";
const NOTION_VERSION = "2022-06-28";
const CORPORATE_LABEL = "企業";

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === "OPTIONS") {
    return corsPreflightResponse();
  }
  if (request.method !== "POST") {
    return jsonResponse({ error: "method not allowed,只接受 POST" }, 405);
  }

  const notionToken = env.NOTION_TOKEN;
  const dbId = env.NOTION_DATABASE_ID || DEFAULT_DATABASE_ID;

  if (!notionToken) {
    return jsonResponse({ error: "NOTION_TOKEN 未設定" }, 500);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid JSON body" }, 400);
  }

  const ticker = (body.ticker || "").trim();
  const name = (body.name || "").trim();
  const industries = Array.isArray(body.industries)
    ? body.industries.map((s) => String(s).trim()).filter(Boolean)
    : [];

  if (!ticker || !name) {
    return jsonResponse({ error: "需要 ticker 跟 name" }, 400);
  }

  // 寫 Notion 12 筆月營收
  let writtenMonthly = 0;
  let monthlyError = null;
  try {
    writtenMonthly = await writeMonthlyRevenue(
      notionToken, dbId, ticker, name, industries,
    );
  } catch (e) {
    monthlyError = e?.message || String(e);
  }

  return jsonResponse({
    ok: !monthlyError,
    ticker, name, industries,
    writtenMonthly,
    monthlyError,
    note: "需要正式法說會與 ICS push 請本機跑 scripts/add_taiwan_company.py 或 run_ics_only.bat",
  });
}

/* ---------- 寫 Notion 月營收 ---------- */

async function writeMonthlyRevenue(token, dbId, ticker, name, industries) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const events = [];
  for (let i = 0; i <= 12; i++) {
    const announceDate = new Date(today.getFullYear(), today.getMonth() + i, 10);
    if (announceDate < today) continue;

    const month = announceDate.getMonth() + 1; // 1~12
    const year = announceDate.getFullYear();
    const revYear = month > 1 ? year : year - 1;
    const revMonth = month > 1 ? month - 1 : 12;

    const dateIso = isoDate(announceDate);
    events.push({
      title: `${name}(${ticker}) ${revYear}-${pad2(revMonth)} 月營收公布`,
      date: dateIso,
    });
  }

  const allIndustries = sortedUnique([CORPORATE_LABEL, ...industries]);
  const url = `https://mops.twse.com.tw/mops/web/t146sb05?co_id=${ticker}`;

  let written = 0;
  for (const ev of events) {
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
          展覽名稱: { title: [{ text: { content: ev.title } }] },
          開始日期: { date: { start: ev.date } },
          結束日期: { date: { start: ev.date } },
          地點: { select: { name: "臺灣" } },
          狀態: { select: { name: "已確認" } },
          信心度: { select: { name: "🟢 高" } },
          來源層次: { select: { name: "白名單" } },
          產業類別: {
            multi_select: allIndustries.map((n) => ({ name: n })),
          },
          主辦單位: { rich_text: [{ text: { content: name } }] },
          官方網址: { url },
        },
      }),
    });
    if (resp.ok) written++;
  }
  return written;
}

/* ---------- Utility ---------- */

function pad2(n) {
  return String(n).padStart(2, "0");
}

function isoDate(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function sortedUnique(arr) {
  return Array.from(new Set(arr)).sort();
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
