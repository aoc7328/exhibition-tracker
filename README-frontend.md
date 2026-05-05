# 展覽追蹤前端 · Frontend

這是 `exhibition-tracker` 前端網頁的部分，獨立於後端的 ICS 產生器。
它直接讀 Notion 資料庫、即時顯示展覽列表，並自動同步（每 60 秒輪詢一次，視窗切回前景時也會立刻刷新）。

## 架構

```
你的瀏覽器
    │
    │  GET /api/exhibitions          ← 開頁時 + 每 60 秒 + 切回前景時
    ▼
Cloudflare Pages Function
    │
    │  POST /v1/databases/.../query  ← 帶 Authorization: Bearer NOTION_TOKEN
    ▼
Notion API
```

- 前端是純靜態檔（`index.html` / `styles.css` / `app.js`），跟你後端產的 `.ics` 無關。
- API 端是 Cloudflare Pages Function（`functions/api/exhibitions.js`），它從環境變數讀 Notion Token，所以 token **不會出現在 git、不會出現在前端 bundle**。

## 部署步驟（Cloudflare Pages）

### 1. 建立 Pages 專案

1. 進 Cloudflare Dashboard → **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**。
2. 選你那個 `exhibition-tracker` repo。
3. **Build settings** 全部留空：
   - Build command：（空）
   - Build output directory：`/`（也就是根目錄）
   - Root directory：`/`
4. 點 **Save and Deploy**。

第一次部署完，你會拿到一個 `xxx.pages.dev` 的網址。

### 2. 設定環境變數

部署完進入該專案：

**Settings → Environment variables → Production → Add variable**

| Variable name | Value |
|---|---|
| `NOTION_TOKEN` | 你的 Notion Integration Token（`ntn_…`） |
| `NOTION_DATABASE_ID` | （選填）`f329eabe-5cb8-4f3e-af6f-5f722ab39d13` |

加完後 → **Deployments** → 在最近一次 deployment 旁點 **⋯ → Retry deployment**，讓新環境變數生效。

> `NOTION_DATABASE_ID` 不填的話，程式碼裡的預設值就是上面那個 ID。

### 3. 確認 Notion Integration 有資料庫存取權

進你那個 Notion Integration → **Access** → **Add pages** → 把「展覽追蹤」資料庫加進去（如果你後端 Claude Code 已經能寫入該資料庫，這一步通常已經做過了）。

### 4. 訪問

- 開 `https://你的專案.pages.dev/`
- 應該看到表格載入並顯示資料
- 如果出現「⚠ NOTION_TOKEN 未設定」→ 回去檢查環境變數有沒有設好、有沒有重新部署

## 自訂事項

### 訂閱網址

預設指向 `webcal://aoc7328.github.io/exhibition-tracker/exhibitions.ics`。
如果你 ICS 網址改了，編輯 `index.html` 兩個地方：

```html
<code id="subscribe-url">webcal://...</code>
...
<a id="subscribe-open" href="webcal://...">
```

### 輪詢頻率

`app.js` 開頭：

```js
const POLL_INTERVAL_MS = 60_000; // 改這個
```

### Notion 資料庫 ID

`functions/api/exhibitions.js` 開頭：

```js
const DEFAULT_DATABASE_ID = "f329eabe-5cb8-4f3e-af6f-5f722ab39d13";
```

或者在 Cloudflare 環境變數設 `NOTION_DATABASE_ID` 覆蓋。

## 本地測試（選用）

如果你想在 push 之前先在本地跑：

```bash
npm install -g wrangler
# 在 repo 根目錄執行
wrangler pages dev . --binding NOTION_TOKEN=你的token
```

然後開 `http://localhost:8788`。

## 檔案清單

| 檔案 | 角色 |
|---|---|
| `index.html` | 主頁面結構 |
| `styles.css` | 樣式 |
| `app.js` | 前端邏輯（fetch、輪詢、篩選、渲染） |
| `functions/api/exhibitions.js` | Cloudflare Pages Function（代理 Notion API） |
| `README-frontend.md` | 本文件 |

## 與後端的關係

完全解耦。後端 ICS 產生器繼續跑它的 GitHub Actions、推 ICS 到 GitHub Pages。前端 + Function 部署到 Cloudflare Pages，**唯一的接觸點是同一個 Notion 資料庫**——後端寫入 Notion、前端讀取 Notion，中間沒有檔案傳遞。
