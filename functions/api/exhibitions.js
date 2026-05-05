/**
 * Cloudflare Pages Functionï¼?api/exhibitions
 *
 * ä»?? Notion APIï¼Œæ?å±•è¦½è¿½è¹¤è³‡æ?åº«ç??§å®¹è½‰æ?ä¹¾æ·¨??JSON çµ¦å?ç«¯ç”¨?? * Notion Token å¾?Cloudflare Pages ?°å?è®Šæ•¸è®€?–ï?è®Šæ•¸?ç¨±ï¼šNOTION_TOKENï¼‰ã€? *
 * ?¨ç½²?°å?è®Šæ•¸ï¼? *   NOTION_TOKEN     Notion Integration Tokenï¼ˆå?å¡«ï?
 *   NOTION_DATABASE_ID  Notion è³‡æ?åº?IDï¼ˆé¸å¡«ï??è¨­?ºå?è¦½è¿½è¹¤ç? IDï¼? */

const DEFAULT_DATABASE_ID = "87af4c274b834bc3b7018a4597f79153";
const NOTION_VERSION = "2022-06-28";

export async function onRequest(context) {
  const { env } = context;

  const token = env.NOTION_TOKEN;
  const databaseId = env.NOTION_DATABASE_ID || DEFAULT_DATABASE_ID;

  if (!token) {
    return jsonResponse(
      {
        error: "NOTION_TOKEN ?ªè¨­å®?,
        hint: "è«‹åœ¨ Cloudflare Pages å°ˆæ???Settings ??Environment variables ? ä? NOTION_TOKEN",
      },
      500,
    );
  }

  try {
    const allResults = [];
    let cursor = undefined;

    // Notion API ä¸€æ¬¡æ?å¤?100 ç­†ï???pagination ä»¥é˜²å°‡ä?è³‡æ?è¶…é? 100
    do {
      const body = {
        page_size: 100,
        sorts: [{ property: "?‹å??¥æ?", direction: "ascending" }],
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
            error: `Notion API ?žæ? ${resp.status}`,
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
      { error: err?.message || "?ªçŸ¥?¯èª¤" },
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
    name: getTitle(p["å±•è¦½?ç¨±"]),
    startDate: getDateStart(p["?‹å??¥æ?"]),
    endDate: getDateEnd(p["çµæ??¥æ?"]) || getDateStart(p["çµæ??¥æ?"]),
    industry: getMultiSelect(p["?¢æ¥­é¡žåˆ¥"]),
    confidence: getSelect(p["ä¿¡å?åº?]),
    location: getSelect(p["?°é?"]),
    sourceLevel: getSelect(p["ä¾†æ?å±¤æ¬¡"]),
    organizer: getRichText(p["ä¸»è¾¦?®ä?"]),
    officialUrl: getUrl(p["å®˜æ–¹ç¶²å?"]),
    relatedStocks: getRichText(p["?¸é??‹è‚¡"]),
    status: getSelect(p["?€??]),
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
