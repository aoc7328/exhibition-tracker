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
  viewMode: "list", // list | calendar
  calendar: {
    // 中央顯示的月份（{ year, month } where month is 0-indexed）
    centerYear: new Date().getFullYear(),
    centerMonth: new Date().getMonth(),
  },
};

/* ---------- Boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  bindAddTaiwanForm();
  fetchData();
  startPolling();
  startTicker();
});

/* ---------- Add Taiwan Company Form ---------- */
function bindAddTaiwanForm() {
  const form = document.getElementById("add-taiwan-form");
  if (!form) return;
  form.addEventListener("submit", onAddTaiwanSubmit);
}

async function onAddTaiwanSubmit(e) {
  e.preventDefault();
  const ticker = document.getElementById("add-tw-ticker").value.trim();
  const name = document.getElementById("add-tw-name").value.trim();
  const industriesStr = document.getElementById("add-tw-industries").value.trim();
  const industries = industriesStr ? industriesStr.split(/\s+/).filter(Boolean) : [];
  const statusEl = document.getElementById("add-tw-status");

  if (!ticker || !name) {
    statusEl.textContent = "請填代號與公司名";
    statusEl.className = "add-tw-status is-error";
    return;
  }

  statusEl.textContent = "處理中…";
  statusEl.className = "add-tw-status is-loading";

  try {
    const resp = await fetch("/api/add-taiwan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, name, industries }),
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      statusEl.textContent = `✓ ${name} 加入成功,寫入 ${data.writtenMonthly} 筆月營收`;
      statusEl.className = "add-tw-status is-success";
      // 清空 form
      document.getElementById("add-tw-ticker").value = "";
      document.getElementById("add-tw-name").value = "";
      document.getElementById("add-tw-industries").value = "";
      // 重新拉資料顯示新加的公司
      setTimeout(() => fetchData(true), 500);
    } else {
      const errs = [data.monthlyError, data.error].filter(Boolean).join(" | ");
      statusEl.textContent = `失敗:${errs || resp.status}`;
      statusEl.className = "add-tw-status is-error";
    }
  } catch (err) {
    statusEl.textContent = `錯誤:${err.message}`;
    statusEl.className = "add-tw-status is-error";
  }
}

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

  // View mode tabs（清單 / 月曆）
  document.querySelectorAll("[data-view-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.viewMode = btn.dataset.viewMode;
      document.querySelectorAll("[data-view-mode]").forEach((b) => {
        const isActive = b === btn;
        b.classList.toggle("active", isActive);
        b.setAttribute("aria-selected", String(isActive));
      });
      render();
    });
  });

  // 月曆月份切換
  document.getElementById("cal-prev").addEventListener("click", () => {
    shiftCalendar(-1);
  });
  document.getElementById("cal-next").addEventListener("click", () => {
    shiftCalendar(1);
  });
  document.getElementById("cal-today").addEventListener("click", () => {
    const now = new Date();
    state.calendar.centerYear = now.getFullYear();
    state.calendar.centerMonth = now.getMonth();
    render();
  });

  // 視窗從背景切回前景 → 立刻刷新
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      fetchData();
    }
  });

  // Day modal 設定
  setupDayModal();
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
  const tableEl = document.getElementById("exh-table");
  const emptyEl = document.getElementById("empty-state");
  const errorEl = document.getElementById("error-state");
  const calendarEl = document.getElementById("calendar-view");
  const countEl = document.getElementById("result-count");

  errorEl.hidden = true;

  const rows = sortByDate(
    state.exhibitions.map(decorateExhibition).filter(matchesFilter)
  );

  state.filteredCount = rows.length;
  countEl.innerHTML = `共 <strong>${rows.length}</strong> / ${state.exhibitions.length} 筆`;

  if (state.viewMode === "calendar") {
    // 切到月曆模式
    tableEl.hidden = true;
    emptyEl.hidden = true;
    calendarEl.hidden = false;
    renderCalendar(rows);
    return;
  }

  // 清單模式：休市日只給月曆看，這裡濾掉
  const listRows = rows.filter((e) => !e.isHoliday);
  tableEl.hidden = false;
  calendarEl.hidden = true;

  if (listRows.length === 0) {
    tbody.innerHTML = "";
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;

  // 計數時也用實際顯示的數字
  countEl.innerHTML = `共 <strong>${listRows.length}</strong> / ${state.exhibitions.length} 筆`;

  tbody.innerHTML = listRows.map(rowHtml).join("");
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
        `<button class="chip chip-industry-filter ${industryColorClass(ind)}${
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
  // 休市日不算商展也不算企業，永遠由月曆模式自己處理
  if (exh.isHoliday) {
    if (state.filter.type !== "all") return false;
  } else if (state.filter.type === "exhibition") {
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

/* ---------- Calendar ---------- */
const MAX_VISIBLE_ROWS = 4; // 每週可見的事件 row 數，超過用 +N
const WEEKDAY_LABELS = ["日", "一", "二", "三", "四", "五", "六"];

function shiftCalendar(delta) {
  // delta = +1 (下個月) or -1 (上個月)
  const d = new Date(state.calendar.centerYear, state.calendar.centerMonth + delta, 1);
  state.calendar.centerYear = d.getFullYear();
  state.calendar.centerMonth = d.getMonth();
  render();
}

function renderCalendar(events) {
  const container = document.getElementById("calendar-months");
  const cy = state.calendar.centerYear;
  const cm = state.calendar.centerMonth;

  // 單月顯示
  const month = (() => {
    const d = new Date(cy, cm, 1);
    return { year: d.getFullYear(), month: d.getMonth() };
  })();

  // 把休市日跟一般事件分開
  const regularEvents = events.filter((e) => !e.isHoliday);
  const holidayEvents = events.filter((e) => e.isHoliday);

  container.innerHTML = monthHtml(month, regularEvents, holidayEvents);

  // 綁定 +N 點擊（顯示該日全部事件）
  container.querySelectorAll(".cal-overflow").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const key = btn.dataset.day;
      showDayModal(key, eventsForDay(events, key));
    });
  });

  // 綁定右下角 + 按鈕（每格一個）
  container.querySelectorAll(".cal-day-add").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const key = btn.dataset.day;
      showDayModal(key, eventsForDay(events, key));
    });
  });

  // 事件條本身保持可點（開官網），不冒泡到任何父層
  container.querySelectorAll(".cal-event-bar").forEach((bar) => {
    bar.addEventListener("click", (e) => {
      e.stopPropagation();
    });
  });
}

function eventsForDay(events, dateKey) {
  const target = new Date(dateKey);
  target.setHours(0, 0, 0, 0);
  return events.filter((exh) => {
    if (!exh.startDate) return false;
    const start = new Date(exh.startDate);
    start.setHours(0, 0, 0, 0);
    const end = exh.endDate ? new Date(exh.endDate) : new Date(exh.startDate);
    end.setHours(0, 0, 0, 0);
    return target >= start && target <= end;
  });
}

function isoDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function monthHtml({ year, month }, allEvents, holidayEvents = []) {
  const today = isoDate(new Date());
  const monthLabel = `${year} 年 ${month + 1} 月`;

  // 計算 42 天（6 週 × 7 天）
  const firstDay = new Date(year, month, 1);
  const startWeekday = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevDays = new Date(year, month, 0).getDate();

  const allDays = [];
  for (let i = startWeekday - 1; i >= 0; i--) {
    allDays.push({
      date: new Date(year, month - 1, prevDays - i),
      isOutside: true,
    });
  }
  for (let day = 1; day <= daysInMonth; day++) {
    allDays.push({
      date: new Date(year, month, day),
      isOutside: false,
    });
  }
  while (allDays.length < 42) {
    const offset = allDays.length - startWeekday - daysInMonth + 1;
    allDays.push({
      date: new Date(year, month + 1, offset),
      isOutside: true,
    });
  }

  // 6 週
  const weeks = [];
  for (let w = 0; w < 6; w++) {
    weeks.push(allDays.slice(w * 7, (w + 1) * 7));
  }

  return `
    <div class="cal-month">
      <div class="cal-month-head">${monthLabel}</div>
      <div class="cal-weekdays">
        ${WEEKDAY_LABELS.map(
          (w, i) =>
            `<div class="cal-weekday${i === 0 || i === 6 ? " is-weekend" : ""}">${w}</div>`,
        ).join("")}
      </div>
      <div class="cal-grid">
        ${weeks.map((wk) => weekHtml(wk, allEvents, today, holidayEvents)).join("")}
      </div>
    </div>
  `;
}

function weekHtml(weekDays, allEvents, todayKey, holidayEvents = []) {
  const weekStart = new Date(weekDays[0].date);
  weekStart.setHours(0, 0, 0, 0);
  const weekEnd = new Date(weekDays[6].date);
  weekEnd.setHours(23, 59, 59, 999);

  // 計算每天的休市市場列表 { dateKey: ["美","台"] }
  // 從事件的 location 推斷市場：「臺灣」→ 台、「世界」→ 美
  const holidayByDay = new Map();
  for (const exh of holidayEvents) {
    if (!exh.startDate) continue;
    const start = new Date(exh.startDate);
    const end = exh.endDate ? new Date(exh.endDate) : new Date(exh.startDate);
    if (end < weekStart || start > weekEnd) continue;
    const market = exh.location === "臺灣" ? "台" : "美";
    const cursor = new Date(Math.max(start.getTime(), weekStart.getTime()));
    cursor.setHours(0, 0, 0, 0);
    const stop = new Date(Math.min(end.getTime(), weekEnd.getTime()));
    stop.setHours(0, 0, 0, 0);
    while (cursor <= stop) {
      const k = isoDate(cursor);
      if (!holidayByDay.has(k)) holidayByDay.set(k, new Set());
      holidayByDay.get(k).add(market);
      cursor.setDate(cursor.getDate() + 1);
    }
  }

  // 收集這週覆蓋的事件
  const weekEvents = [];
  for (const exh of allEvents) {
    if (!exh.startDate) continue;
    const start = new Date(exh.startDate);
    start.setHours(0, 0, 0, 0);
    const end = exh.endDate ? new Date(exh.endDate) : new Date(exh.startDate);
    end.setHours(23, 59, 59, 999);
    if (end >= weekStart && start <= weekEnd) {
      weekEvents.push({ exh, start, end });
    }
  }

  // 排序：開始日早的優先；同天則跨日久的優先（讓長條排前面）
  weekEvents.sort((a, b) => {
    const startDiff = a.start - b.start;
    if (startDiff !== 0) return startDiff;
    const aDur = a.end - a.start;
    const bDur = b.end - b.start;
    return bDur - aDur;
  });

  // 計算每個事件在這週的 segment（startCol 0-6, endCol 0-6）
  const segments = weekEvents.map(({ exh, start, end }) => {
    const segStart = start < weekStart ? weekStart : start;
    const segEnd = end > weekEnd ? weekEnd : end;
    const startCol = segStart.getDay();
    const endCol = segEnd.getDay();
    return {
      exh,
      startCol,
      endCol,
      isContStart: start < weekStart, // 從上週延續來的
      isContEnd: end > weekEnd,       // 延續到下週
      row: -1,
    };
  });

  // Greedy row 分配（不跨 row 重疊）
  const rowOccupied = []; // rowOccupied[r] = [{startCol, endCol}, ...]
  for (const seg of segments) {
    let placedRow = -1;
    for (let r = 0; r < rowOccupied.length; r++) {
      const conflicts = rowOccupied[r].some(
        (s) => !(seg.endCol < s.startCol || seg.startCol > s.endCol),
      );
      if (!conflicts) {
        rowOccupied[r].push(seg);
        placedRow = r;
        break;
      }
    }
    if (placedRow === -1) {
      rowOccupied.push([seg]);
      placedRow = rowOccupied.length - 1;
    }
    seg.row = placedRow;
  }

  // 計算每天的 overflow 數（被擠出 row 0..MAX-1 之外的事件數）
  const overflowByCol = new Array(7).fill(0);
  for (const seg of segments) {
    if (seg.row >= MAX_VISIBLE_ROWS) {
      for (let c = seg.startCol; c <= seg.endCol; c++) {
        overflowByCol[c]++;
      }
    }
  }

  // 生成 HTML
  // 每週一個 grid：7 columns × (1 + MAX_VISIBLE_ROWS + 1) rows
  // row 1 = 日期數字、row 2..MAX+1 = 事件條、row MAX+2 = 「+N」or「+ 按鈕」
  const dayBgCells = weekDays
    .map((d, c) => dayBgCellHtml(d, todayKey, c))
    .join("");
  const dayNumCells = weekDays
    .map((d, c) => dayNumCellHtml(d, c, holidayByDay))
    .join("");
  const eventBars = segments
    .filter((s) => s.row < MAX_VISIBLE_ROWS)
    .map((s) => eventBarHtml(s))
    .join("");
  // overflow 跟 + 按鈕：同一格只有 overflow 顯示時不放 +（避免重複入口）
  const overflowCells = weekDays
    .map((d, c) => overflowCellHtml(d, overflowByCol[c], c))
    .join("");
  const dayAddCells = weekDays
    .map((d, c) => dayAddCellHtml(d, overflowByCol[c], c))
    .join("");

  return `
    <div class="cal-week">
      ${dayBgCells}
      ${dayNumCells}
      ${eventBars}
      ${overflowCells}
      ${dayAddCells}
    </div>
  `;
}

function dayBgCellHtml(d, todayKey, col) {
  const key = isoDate(d.date);
  const isToday = key === todayKey;
  const weekday = d.date.getDay();
  const isWeekend = weekday === 0 || weekday === 6;
  const cls = [
    "cal-day-bg",
    d.isOutside ? "is-outside" : "",
    isToday ? "is-today" : "",
    isWeekend ? "is-weekend" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return `<div class="${cls}" style="grid-column: ${col + 1}; grid-row: 1 / -1"></div>`;
}

function dayNumCellHtml(d, col, holidayByDay = new Map()) {
  const key = isoDate(d.date);
  const today = isoDate(new Date());
  const cls = [
    "cal-day-num",
    key === today ? "is-today" : "",
    d.isOutside ? "is-outside" : "",
  ]
    .filter(Boolean)
    .join(" ");

  // 休市標記：臺/美/臺美
  const markets = holidayByDay.get(key);
  let holidayMark = "";
  if (markets && markets.size > 0) {
    // 排序：台在前、美在後
    const sorted = ["台", "美"].filter((m) => markets.has(m));
    holidayMark = `<span class="cal-holiday-mark">休市:${sorted.join("")}</span>`;
  }

  return `<div class="${cls}" style="grid-column: ${col + 1}; grid-row: 1">${d.date.getDate()}${holidayMark}</div>`;
}

function eventBarHtml(seg) {
  const { exh, startCol, endCol, isContStart, isContEnd, row } = seg;
  const cls = [
    "cal-event-bar",
    exh.isHolding ? "is-holding" : exh.isCompany ? "is-company" : "",
    isContStart ? "is-cont-start" : "",
    isContEnd ? "is-cont-end" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const span = endCol - startCol + 1;
  const url = exh.officialUrl || exh.notionUrl;
  const arrowLeft = isContStart ? "‹ " : "";
  const arrowRight = isContEnd ? " ›" : "";
  return `<a class="${cls}" href="${escapeAttr(url)}" target="_blank" rel="noopener" title="${escapeAttr(exh.name)}" style="grid-column: ${startCol + 1} / span ${span}; grid-row: ${row + 2}">${arrowLeft}${escapeHtml(exh.name)}${arrowRight}</a>`;
}

function overflowCellHtml(d, count, col) {
  if (count <= 0) return "";
  const key = isoDate(d.date);
  return `<button class="cal-overflow" data-day="${key}" type="button" style="grid-column: ${col + 1}; grid-row: ${MAX_VISIBLE_ROWS + 2}">+${count}</button>`;
}

// 右下角 + 按鈕：每一格都有，但若該格已經有 +N（overflow），就不重複放
function dayAddCellHtml(d, overflowCount, col) {
  if (d.isOutside) return ""; // 上下月空白格不放 +
  if (overflowCount > 0) return ""; // 有 +N 時，+N 已是入口，不重複
  const key = isoDate(d.date);
  return `<button class="cal-day-add" data-day="${key}" type="button" aria-label="查看 ${d.date.getDate()} 日" style="grid-column: ${col + 1}; grid-row: ${MAX_VISIBLE_ROWS + 2}">+</button>`;
}

/* ---------- Day Modal（點 +N 展開該日全部事件） ---------- */
function showDayModal(dateKey, events) {
  const modal = document.getElementById("cal-day-modal");
  const dateEl = document.getElementById("cal-day-modal-date");
  const eventsEl = document.getElementById("cal-day-modal-events");

  const [y, m, d] = dateKey.split("-");
  const dateObj = new Date(parseInt(y), parseInt(m) - 1, parseInt(d));
  const weekdayName = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"][dateObj.getDay()];
  dateEl.textContent = `${parseInt(y)} 年 ${parseInt(m)} 月 ${parseInt(d)} 日 ${weekdayName}`;

  if (events.length === 0) {
    eventsEl.innerHTML = `<p class="modal-empty">這天沒有事件。</p>`;
  } else {
    eventsEl.innerHTML = events
      .map((exh) => {
        const cls = exh.isHolding
          ? "modal-event-holding"
          : exh.isCompany
            ? "modal-event-company"
            : "modal-event-exhibition";
        const url = exh.officialUrl || exh.notionUrl;
        let badge = "";
        if (exh.isHolding) {
          badge = `<span class="modal-event-badge modal-event-badge-holding">持股</span>`;
        } else if (exh.isCompany) {
          badge = `<span class="modal-event-badge">企業</span>`;
        }
        const metaItems = [];
        if (exh.location) {
          metaItems.push(
            `<span class="modal-event-meta-tag">${escapeHtml(exh.location)}</span>`,
          );
        }
        if (exh.status) {
          metaItems.push(
            `<span class="modal-event-meta-tag">${escapeHtml(exh.status)}</span>`,
          );
        }
        for (const ind of exh.industries || exh.industry || []) {
          metaItems.push(
            `<span class="modal-event-meta-tag ${industryColorClass(ind)}">${escapeHtml(ind)}</span>`,
          );
        }
        const meta = metaItems.join("");
        const dateRange =
          exh.endDate && exh.endDate !== exh.startDate
            ? `${formatDate(exh.startDate)} – ${formatDate(exh.endDate)}`
            : formatDate(exh.startDate);
        return `
          <a class="modal-event ${cls}" href="${escapeAttr(url)}" target="_blank" rel="noopener">
            <div class="modal-event-head">
              ${badge}
              <span class="modal-event-name">${escapeHtml(exh.name)}</span>
            </div>
            <div class="modal-event-date">${escapeHtml(dateRange)}</div>
            ${exh.organizer ? `<div class="modal-event-org">${escapeHtml(truncate(exh.organizer, 80))}</div>` : ""}
            ${meta ? `<div class="modal-event-meta">${meta}</div>` : ""}
          </a>
        `;
      })
      .join("");
  }

  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}

function setupDayModal() {
  const modal = document.getElementById("cal-day-modal");
  if (!modal || modal._setup) return;
  modal._setup = true;

  // 關閉按鈕
  document.getElementById("cal-day-modal-close").addEventListener("click", () => {
    if (typeof modal.close === "function") modal.close();
    else modal.removeAttribute("open");
  });

  // 點背景關閉
  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      if (typeof modal.close === "function") modal.close();
      else modal.removeAttribute("open");
    }
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
  let badge = "";
  if (exh.isHolding) {
    badge = `<span class="badge-holding" title="持股相關事件">持股</span>`;
  } else if (exh.isCompany) {
    badge = `<span class="badge-company" title="企業相關事件">企業</span>`;
  }
  const name = `<a class="cell-name" href="${escapeAttr(url)}" target="_blank" rel="noopener">${badge}${escapeHtml(exh.name)}</a>`;

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
  return items
    .map(
      (s) =>
        `<span class="tag tag-industry ${industryColorClass(s)}">${escapeHtml(s)}</span>`,
    )
    .join("");
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

// 字串穩定 hash（Java String.hashCode 風格），對短中文字串較分散
function hashString(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

// 給定產業名稱回傳穩定的顏色 class（18 色 palette）
function industryColorClass(name) {
  if (!name) return "";
  return `tag-c${hashString(name) % 18}`;
}

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
