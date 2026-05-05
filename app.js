/**
 * Exhibition Tracker — Frontend Logic
 *
 * 1. fetch /api/exhibitions（Cloudflare Pages Function 代理 Notion）
 * 2. 渲染表格、套用篩選、計算倒數
 * 3. 自動輪詢 + visibilitychange 切回前景時刷新
 * 4. 訂閱網址複製
 */

const API_ENDPOINT = "/api/exhibitions";
const POLL_INTERVAL_MS = 60_000; // 每 60 秒輪詢一次
const TICK_INTERVAL_MS = 1_000; // 每秒更新「N 秒前」

const state = {
  exhibitions: [],
  filteredCount: 0,
  fetchedAt: null,
  lastError: null,
  filter: {
    type: "all", // all | exhibition | company
    status: "已確認", // 預設只看已確認
    location: "all",
    industry: "all", // 次層產業篩選
    search: "",
  },
  sort: {
    by: "startDate",
    direction: "asc", // asc | desc
  },
  knownIndustries: [], // 記錄已渲染過的產業列表，避免每次資料更新都重生 chip
};

/* ---------- Boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  fetchData();
  startPolling();
  startTicker();
});

/* ---------- Events ---------- */
function bindEvents() {
  // 重新整理
  document.getElementById("refresh-btn").addEventListener("click", () => {
    fetchData(true);
  });

  // 訂閱網址複製
  document.getElementById("subscribe-copy").addEventListener("click", onCopy);

  // 篩選 chips
  document.querySelectorAll("[data-filter-type]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveChip(btn, "data-filter-type");
      state.filter.type = btn.dataset.filterType;
      render();
    });
  });
  document.querySelectorAll("[data-filter-status]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveChip(btn, "data-filter-status");
      state.filter.status = btn.dataset.filterStatus;
      render();
    });
  });
  document.querySelectorAll("[data-filter-location]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveChip(btn, "data-filter-location");
      state.filter.location = btn.dataset.filterLocation;
      render();
    });
  });

  // 搜尋
  document.getElementById("search-input").addEventListener("input", (e) => {
    state.filter.search = e.target.value.trim().toLowerCase();
    render();
  });

  // 日期排序箭頭
  document.querySelectorAll("[data-sort-direction]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.sort.direction = btn.dataset.sortDirection;
      document.querySelectorAll("[data-sort-direction]").forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      render();
    });
  });

  // 視窗從背景切回前景 → 立刻刷新
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      fetchData();
    }
  });
}

function setActiveChip(activeBtn, attr) {
  document.querySelectorAll(`[${attr}]`).forEach((btn) => {
    btn.classList.toggle("active", btn === activeBtn);
  });
}

/* ---------- Polling ---------- */
function startPolling() {
  setInterval(() => {
    if (document.visibilityState === "visible") {
      fetchData();
    }
  }, POLL_INTERVAL_MS);
}

function startTicker() {
  setInterval(updateLastUpdatedLabel, TICK_INTERVAL_MS);
}

/* ---------- Fetch ---------- */
async function fetchData(manual = false) {
  setStatus("loading", manual ? "重新整理中…" : "更新中…");

  try {
    const resp = await fetch(API_ENDPOINT, { cache: "no-store" });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(
        err.error || `HTTP ${resp.status}`,
      );
    }

    const data = await resp.json();
    state.exhibitions = data.exhibitions || [];
    state.fetchedAt = new Date(data.fetchedAt || Date.now());
    state.lastError = null;

    setupIndustryChips();
    render();
    setStatus("ok", "已同步");
    updateLastUpdatedLabel();
  } catch (err) {
    state.lastError = err.message || String(err);
    setStatus("error", "更新失敗");
    showError(state.lastError);
  }
}

/* ---------- Status bar ---------- */
function setStatus(kind, label) {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  const btn = document.getElementById("refresh-btn");

  dot.classList.remove("is-ok", "is-loading", "is-error");
  if (kind === "ok") dot.classList.add("is-ok");
  else if (kind === "loading") dot.classList.add("is-loading");
  else if (kind === "error") dot.classList.add("is-error");

  text.textContent = label;
  btn.classList.toggle("is-loading", kind === "loading");
}

function updateLastUpdatedLabel() {
  const el = document.getElementById("last-updated");
  if (!state.fetchedAt) {
    el.textContent = "最後更新：—";
    return;
  }
  const diff = Math.floor((Date.now() - state.fetchedAt.getTime()) / 1000);
  el.textContent = `最後更新：${formatRelative(diff)}`;
}

function formatRelative(seconds) {
  if (seconds < 5) return "剛剛";
  if (seconds < 60) return `${seconds} 秒前`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} 分鐘前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小時前`;
  const d = Math.floor(h / 24);
  return `${d} 天前`;
}

/* ---------- Render ---------- */
function render() {
  const tbody = document.getElementById("exh-tbody");
  const emptyEl = document.getElementById("empty-state");
  const errorEl = document.getElementById("error-state");
  const countEl = document.getElementById("result-count");

  errorEl.hidden = true;

  const rows = sortByDate(
    state.exhibitions.map(decorateExhibition).filter(matchesFilter)
  );

  state.filteredCount = rows.length;

  countEl.innerHTML = `共 <strong>${rows.length}</strong> / ${state.exhibitions.length} 筆`;

  if (rows.length === 0) {
    tbody.innerHTML = "";
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;

  tbody.innerHTML = rows.map(rowHtml).join("");
}

function showError(msg) {
  const errorEl = document.getElementById("error-state");
  document.getElementById("error-text").textContent = `⚠ ${msg}`;
  errorEl.hidden = false;
}

/* ---------- Decoration: compute derived fields ---------- */
function decorateExhibition(exh) {
  const today = startOfDay(new Date());
  const start = exh.startDate ? startOfDay(new Date(exh.startDate)) : null;
  const end = exh.endDate ? startOfDay(new Date(exh.endDate)) : start;

  let phase = "unknown"; // future / imminent / ongoing / past
  let countdownLabel = "—";

  if (start && end) {
    const daysToStart = Math.round((start - today) / 86_400_000);
    const daysToEnd = Math.round((end - today) / 86_400_000);

    if (daysToEnd < 0) {
      phase = "past";
      countdownLabel = `已結束 ${Math.abs(daysToEnd)}d`;
    } else if (daysToStart <= 0 && daysToEnd >= 0) {
      phase = "ongoing";
      countdownLabel = `進行中`;
    } else if (daysToStart <= 7) {
      phase = "imminent";
      countdownLabel = `T-${daysToStart}d`;
    } else {
      phase = "future";
      countdownLabel = `T-${daysToStart}d`;
    }
  }

  return { ...exh, _phase: phase, _countdownLabel: countdownLabel };
}

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

/* ---------- Industry chips (次層產業篩選) ---------- */
function setupIndustryChips() {
  // 從目前資料抽出所有曾出現的產業（已排除「企業」，因為後端 industries 已過濾）
  const seen = new Set();
  for (const exh of state.exhibitions) {
    const items = exh.industries || exh.industry || [];
    for (const i of items) seen.add(i);
  }
  const sorted = [...seen].sort((a, b) => a.localeCompare(b, "zh-Hant"));

  // 如果產業列表跟上次相同，不重生 chip（避免閃動）
  const same =
    sorted.length === state.knownIndustries.length &&
    sorted.every((v, i) => v === state.knownIndustries[i]);
  if (same) return;
  state.knownIndustries = sorted;

  const container = document.getElementById("industry-chips");
  const allBtn = `<button class="chip chip-industry-filter${
    state.filter.industry === "all" ? " active" : ""
  }" data-filter-industry="all">全部</button>`;
  const otherBtns = sorted
    .map(
      (ind) =>
        `<button class="chip chip-industry-filter${
          state.filter.industry === ind ? " active" : ""
        }" data-filter-industry="${escapeAttr(ind)}">${escapeHtml(ind)}</button>`,
    )
    .join("");
  container.innerHTML = allBtn + otherBtns;

  container.querySelectorAll("[data-filter-industry]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveChip(btn, "data-filter-industry");
      state.filter.industry = btn.dataset.filterIndustry;
      render();
    });
  });
}

/* ---------- Filter ---------- */
function matchesFilter(exh) {
  // Type filter（最前面的篩選）
  // exhibition：不含「企業」標籤 → 純商展（不論有無產業類別）
  // company：含「企業」標籤 → 法說會、月營收、年度發表會
  if (state.filter.type === "exhibition") {
    if (exh.isCompany) return false;
  } else if (state.filter.type === "company") {
    if (!exh.isCompany) return false;
  }

  // Status filter
  if (state.filter.status !== "all") {
    if (state.filter.status === "已過期") {
      // 「已過期」籃：狀態欄為「已過期」 OR 結束日已經過了
      const isExpiredByDate = exh._phase === "past";
      const isExpiredByStatus = exh.status === "已過期";
      if (!isExpiredByDate && !isExpiredByStatus) return false;
    } else if (exh.status !== state.filter.status) {
      return false;
    }
  }

  // Location filter
  if (state.filter.location !== "all" && exh.location !== state.filter.location) {
    return false;
  }

  // Industry filter（次層篩選，跟主要篩選 AND 並存）
  if (state.filter.industry !== "all") {
    const items = exh.industries || exh.industry || [];
    if (!items.includes(state.filter.industry)) return false;
  }

  // Search filter
  const q = state.filter.search;
  if (q) {
    const haystack = [
      exh.name,
      exh.organizer,
      exh.relatedStocks,
      ...(exh.industries || exh.industry || []),
      exh.isCompany ? "企業" : "",
      exh.sourceLevel,
    ]
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(q)) return false;
  }

  return true;
}

/* ---------- Sort ---------- */
function sortByDate(rows) {
  const dir = state.sort.direction === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const aDate = a.startDate || (dir > 0 ? "9999-12-31" : "0000-01-01");
    const bDate = b.startDate || (dir > 0 ? "9999-12-31" : "0000-01-01");
    return dir * aDate.localeCompare(bDate);
  });
}

/* ---------- Row HTML ---------- */
function rowHtml(exh) {
  const rowClass = [
    exh._phase === "past" ? "is-expired" : "",
    exh._phase === "imminent" ? "is-imminent" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return `
    <tr class="${rowClass}">
      <td class="col-name" data-label="名稱">
        ${nameCell(exh)}
      </td>
      <td class="col-date" data-label="日期">
        ${dateCell(exh)}
      </td>
      <td class="col-countdown" data-label="倒數">
        <span class="cell-countdown is-${exh._phase}">${escapeHtml(exh._countdownLabel)}</span>
      </td>
      <td class="col-industry" data-label="產業">
        ${industryCell(exh)}
      </td>
      <td class="col-location" data-label="地點">
        ${locationCell(exh)}
      </td>
      <td class="col-confidence" data-label="信心">
        <span class="confidence-mark">${confidenceMark(exh.confidence)}</span>
      </td>
      <td class="col-status" data-label="狀態">
        ${statusCell(exh)}
      </td>
      <td class="col-source" data-label="來源">
        <span class="tag tag-source">${escapeHtml(exh.sourceLevel || "—")}</span>
      </td>
    </tr>
  `;
}

function nameCell(exh) {
  const url = exh.officialUrl || exh.notionUrl;
  const companyBadge = exh.isCompany
    ? `<span class="badge-company" title="企業相關事件">企業</span>`
    : "";
  const name = `<a class="cell-name" href="${escapeAttr(url)}" target="_blank" rel="noopener">${companyBadge}${escapeHtml(exh.name)}</a>`;

  let parts = [name];
  if (exh.organizer) {
    parts.push(`<span class="cell-organizer">${escapeHtml(truncate(exh.organizer, 60))}</span>`);
  }
  if (exh.relatedStocks) {
    parts.push(`<span class="cell-stocks">${escapeHtml(exh.relatedStocks)}</span>`);
  }
  return parts.join("");
}

function dateCell(exh) {
  if (!exh.startDate) return `<span class="cell-date">—</span>`;
  const start = formatDate(exh.startDate);
  const end = exh.endDate && exh.endDate !== exh.startDate ? formatDate(exh.endDate) : null;
  return `
    <span class="cell-date">${start}</span>
    ${end ? `<span class="cell-date-end">– ${end}</span>` : ""}
  `;
}

function formatDate(iso) {
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}/${m}/${day}`;
}

function industryCell(exh) {
  // 用 industries（已過濾掉「企業」），避免重複顯示
  const items = exh.industries || exh.industry || [];
  if (items.length === 0) return `<span class="tag tag-empty">—</span>`;
  return items.map((s) => `<span class="tag tag-industry">${escapeHtml(s)}</span>`).join("");
}

function locationCell(exh) {
  if (!exh.location) return `<span class="tag">—</span>`;
  const cls = exh.location === "臺灣" ? "tag-location-tw" : "tag-location-world";
  return `<span class="tag ${cls}">${escapeHtml(exh.location)}</span>`;
}

function statusCell(exh) {
  const map = {
    "已確認": "tag-status-ok",
    "待確認": "tag-status-warn",
    "已過期": "tag-status-expired",
  };
  const cls = map[exh.status] || "";
  return `<span class="tag ${cls}">${escapeHtml(exh.status || "—")}</span>`;
}

function confidenceMark(c) {
  // c 例如 "🟢 高" / "🟡 中" / "🔴 低"
  if (!c) return "—";
  // 用 startsWith 比 regex 安全（emoji 是 surrogate pair，無 u flag 的 regex 會拆掉變亂碼）
  if (c.startsWith("🟢")) return "🟢";
  if (c.startsWith("🟡")) return "🟡";
  if (c.startsWith("🔴")) return "🔴";
  return c;
}

/* ---------- Subscribe copy ---------- */
async function onCopy() {
  const url = document.getElementById("subscribe-url").textContent.trim();
  const btn = document.getElementById("subscribe-copy");
  try {
    await navigator.clipboard.writeText(url);
    const original = btn.textContent;
    btn.textContent = "已複製 ✓";
    btn.classList.add("is-copied");
    setTimeout(() => {
      btn.textContent = original;
      btn.classList.remove("is-copied");
    }, 1600);
  } catch {
    // Fallback: select & prompt
    window.prompt("複製這段網址：", url);
  }
}

/* ---------- Util ---------- */
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
function escapeAttr(s) {
  return escapeHtml(s);
}
function truncate(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "…" : s;
}
