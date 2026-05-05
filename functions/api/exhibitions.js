/**
 * Cloudflare Pages Function：/api/exhibitions
 *
 * Notion 2025-09-03 API（data sources endpoint）。
 *
 * v2 變更：
 * - 新增 isCompany boolean（產業類別是否包含「企業」）
 * - 新增 industries array（過濾掉「企業」之後的真正產業類別）
 * - 同時保留 industry array 作向後相容
 *
 * 環境變數：
 *   NOTION_TOKEN              Notion Integration Token（必填）
 *   NOTION_DATA_SOURCE_ID     Notion data source ID（選填）
 */

const DEFAULT_DATA_SOURCE_ID = "f329eabe-5cb8-4f3e-af6f-5f722ab39d13";
const NOTION_VERSION = "2025-09-03";
const COMPANY_TAG = "\u4F01\u696D"; // 「企業」

export async function onRequest(context) {
  const { env } = context;

  const token = env.NOTION_TOKEN;
  const dataSourceId =
    env.NOTION_DATA_SOURCE_ID ||
    env.NOTION_DATABASE_ID ||
    DEFAULT_DATA_SOURCE_ID;

  if (!token) {
    return jsonResponse(
      {
        error: "NOTION_TOKEN not configured",
        hint: "Set NOTION_TOKEN in Cloudflare Pages environment variables",
      },
      500,
    );
  }

  try {
    const allResults = [];
    let cursor = undefined;

    do {
      const body = { page_size: 100 };
      if (cursor) body.start_cursor = cursor;

      const resp = await fetch(
        `https://api.notion.com/v1/data_sources/${dataSourceId}/query`,
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
            error: `Notion API responded ${resp.status}`,
            detail: safeParse(text),
          },
          502,
        );
      }

      const data = await resp.json();
      allResults.push(...data.results);
      cursor = data.has_more ? data.next_cursor : undefined;
    } while (cursor);

    const exhibitions = allResults
      .map(transformPage)
      .sort(sortByStartDate);

    return jsonResponse({
      exhibitions,
      count: exhibitions.length,
      fetchedAt: new Date().toISOString(),
    });
  } catch (err) {
    return jsonResponse(
      { error: err?.message || "Unknown error" },
      500,
    );
  }
}

/* ---------- Helpers ---------- */

function transformPage(page) {
  const p = page.properties || {};

  // 「產業類別」這個欄位名 Notion 上可能用「產」(U+7522) 或「産」(U+7523)，兩個都試
  const INDUSTRY_KEYS = ["\u7522\u696D\u985E\u5225", "\u7523\u696D\u985E\u5225", "Industry"];
  const allTags = getMultiSelect(findProp(p, INDUSTRY_KEYS)) || [];
  // 拆分：「企業」獨立成 isCompany；其餘為真正產業類別
  const isCompany = allTags.includes(COMPANY_TAG);
  const industries = allTags.filter((t) => t !== COMPANY_TAG);

  return {
    id: page.id,
    notionUrl: page.url,
    name: getTitle(findProp(p, ["展覽名稱", "Name", "Title"])),
    startDate: getDateStart(findProp(p, ["開始日期", "Start", "Start Date"])),
    endDate:
      getDateEnd(findProp(p, ["結束日期", "End", "End Date"])) ||
      getDateStart(findProp(p, ["結束日期", "End", "End Date"])),
    industries,
    industry: industries, // 向後相容
    isCompany,
    confidence: getSelect(findProp(p, ["信心度", "Confidence"])),
    location: getSelect(findProp(p, ["地點", "Location"])),
    sourceLevel: getSelect(findProp(p, ["來源層次", "Source"])),
    organizer: getRichText(findProp(p, ["主辦單位", "Organizer"])),
    officialUrl: getUrl(findProp(p, ["官方網址", "URL", "Website"])),
    relatedStocks: getRichText(findProp(p, ["相關個股", "Stocks"])),
    status: getSelect(findProp(p, ["狀態", "Status"])),
    lastEdited: page.last_edited_time,
  };
}

function findProp(props, names) {
  for (const n of names) {
    if (props[n] !== undefined) return props[n];
  }
  return undefined;
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

function sortByStartDate(a, b) {
  const aDate = a.startDate || "9999-12-31";
  const bDate = b.startDate || "9999-12-31";
  return aDate.localeCompare(bDate);
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
