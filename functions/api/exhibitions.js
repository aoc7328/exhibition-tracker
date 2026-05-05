/**
 * Cloudflare Pages Function：/api/exhibitions
 *
 * 代理 Notion API，把展覽追蹤資料庫的內容轉成乾淨的 JSON 給前端用。
 * Notion Token 從 Cloudflare Pages 環境變數讀取（變數名稱：NOTION_TOKEN）。
 *
 * 部署環境變數：
 *   NOTION_TOKEN     Notion Integration Token（必填）
 *   NOTION_DATABASE_ID  Notion 資料庫 ID（選填，預設為展覽追蹤的 ID）
 */

const DEFAULT_DATABASE_ID = "f329eabe-5cb8-4f3e-af6f-5f722ab39d13";
const NOTION_VERSION = "2022-06-28";

export async function onRequest(context) {
  const { env } = context;

  const token = env.NOTION_TOKEN;
  const databaseId = env.NOTION_DATABASE_ID || DEFAULT_DATABASE_ID;

  if (!token) {
    return jsonResponse(
      {
        error: "NOTION_TOKEN 未設定",
        hint: "請在 Cloudflare Pages 專案的 Settings → Environment variables 加上 NOTION_TOKEN",
      },
      500,
    );
  }

  try {
    const allResults = [];
    let cursor = undefined;

    // Notion API 一次最多 100 筆，做 pagination 以防將來資料超過 100
    do {
      const body = {
        page_size: 100,
        sorts: [{ property: "開始日期", direction: "ascending" }],
      };
      if (cursor) body.start_cursor = cursor;

      const resp = await fetch(
        `https://api.notion.com/v1/databases/${databaseId}/query`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(body),
        },
      );

      if (!resp.ok) {
        const text = await resp.text();
        return jsonResponse(
          {
            error: `Notion API 回應 ${resp.status}`,
            detail: safeParse(text),
          },
          502,
        );
      }

      const data = await resp.json();
      allResults.push(...data.results);
      cursor = data.has_more ? data.next_cursor : undefined;
    } while (cursor);

    const exhibitions = allResults.map(transformPage);

    return jsonResponse({
      exhibitions,
      count: exhibitions.length,
      fetchedAt: new Date().toISOString(),
    });
  } catch (err) {
    return jsonResponse(
      { error: err?.message || "未知錯誤" },
      500,
    );
  }
}

/* ---------- Helpers ---------- */

function transformPage(page) {
  const p = page.properties || {};

  return {
    id: page.id,
    notionUrl: page.url,
    name: getTitle(p["展覽名稱"]),
    startDate: getDateStart(p["開始日期"]),
    endDate: getDateEnd(p["結束日期"]) || getDateStart(p["結束日期"]),
    industry: getMultiSelect(p["產業類別"]),
    confidence: getSelect(p["信心度"]),
    location: getSelect(p["地點"]),
    sourceLevel: getSelect(p["來源層次"]),
    organizer: getRichText(p["主辦單位"]),
    officialUrl: getUrl(p["官方網址"]),
    relatedStocks: getRichText(p["相關個股"]),
    status: getSelect(p["狀態"]),
    lastEdited: page.last_edited_time,
  };
}

function getTitle(prop) {
  if (!prop?.title) return "";
  return prop.title.map((t) => t.plain_text).join("");
}

function getRichText(prop) {
  if (!prop?.rich_text) return "";
  return prop.rich_text.map((t) => t.plain_text).join("");
}

function getSelect(prop) {
  return prop?.select?.name || "";
}

function getMultiSelect(prop) {
  return prop?.multi_select?.map((s) => s.name) || [];
}

function getDateStart(prop) {
  return prop?.date?.start || null;
}

function getDateEnd(prop) {
  return prop?.date?.end || null;
}

function getUrl(prop) {
  return prop?.url || "";
}

function safeParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
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
