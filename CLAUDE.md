# Best Ban & Pick（BBP）

專案名稱為 **Best Ban & Pick**，縮寫 **BBP**。程式中的套件名稱、repo 名稱使用 `bbp` 或 `best-ban-pick`。

給《Garena 傳說對決》玩家在選角階段使用的建議工具：
- **禁用階段**：建議要禁用哪些英雄，並隨雙方已禁用的英雄即時更新。
- **選角階段**：根據雙方已選英雄、已禁用英雄、剋制／搭配關係、分路與 tier，建議下一隻要選誰，並附上理由。
- **後台**：讓我在自己電腦上新增或修改英雄、分路、tier、剋制與搭配資料。

介面文字一律使用**繁體中文**。程式碼、變數名稱、註解使用英文。

---

## 整體架構

專案分成兩個完全獨立的部分：

| | 本機後台 `admin/` | 公開網站 `site/` |
|---|---|---|
| 用途 | 編輯英雄資料 | 選角頁（給玩家用） |
| 執行位置 | 只在我的電腦 | GitHub Pages |
| 技術 | Python：FastAPI + SQLModel + SQLite + Jinja2 + HTMX | 純靜態：HTML + CSS + 原生 JavaScript（ES modules） |
| 推薦計算 | 不需要 | 在瀏覽器裡用 JS 計算 |

兩者之間唯一的連結是 `site/data/data.json`：後台把資料庫匯出成這個檔案，選角頁讀取它。

**更新流程**：在本機後台改資料（每次修改自動寫入 `data.json`）→ commit 並 push → GitHub Actions 自動部署。

### 重要限制

- **後台不部署、不需要密碼**。後台只能以 uvicorn 預設設定（`127.0.0.1`）啟動，**不可**使用 `--host 0.0.0.0`，也不要寫任何讓後台對外開放的設定。
- **`site/` 必須是純靜態檔案**：不可依賴任何伺服器端程式。
- **`site/` 不使用前端框架或建置工具**：不要 React、npm 套件、TypeScript、打包工具。直接寫瀏覽器能執行的 JS。
- **`site/` 內所有路徑都用相對路徑**（`./data/data.json`、`./avatars/xxx.jpg`），因為 GitHub Pages 會把網站放在 `/<repo名稱>/` 底下。不可使用以 `/` 開頭的絕對路徑。

---

## 目錄結構

```
admin/                       本機後台（不部署）
  main.py                    FastAPI 進入點；掛載 site/avatars 為靜態檔案
  db.py                      engine、session
  models.py                  SQLModel 資料表
  repo.py                    所有資料讀寫（含剋制正負號處理）
  sync.py                    app.db ⇄ data.json 自動匯出／匯入
  routes.py                  後台頁面與 CRUD
  templates/                 Jinja2
  static/                    後台用的 CSS
site/                        部署到 GitHub Pages 的靜態網站
  index.html                 選角頁
  css/style.css
  js/matching.js             分路二分圖匹配（純函式，不碰 DOM）
  js/engine.js               推薦評分（純函式，不碰 DOM）
  js/app.js                  選角頁 UI 與狀態管理
  data/data.json             由 export_data.py 產生，需要 commit
  avatars/                   英雄頭像（{英雄名}.jpg），需要 commit
data/
  heroes.csv                 初始英雄清單
  name_map.csv               台服名稱 ↔ 越南官網名稱對照（抓頭像用）
  app.db                     SQLite 資料庫（加入 .gitignore）
scripts/
  import_heroes.py           從 heroes.csv 匯入英雄
  fetch_avatars.py           抓取英雄頭像
  export_data.py             資料庫 → site/data/data.json
  import_data.py             site/data/data.json → 資料庫（還原用）
tests/
  test_repo.py               pytest：後台資料邏輯
  test_admin.py              pytest：後台頁面與 HTMX 端點
  test_stage2.py             pytest：匯出／匯入腳本、設定頁、匯出頁
  js/                        node --test：推薦引擎（*.test.js）
.github/workflows/deploy.yml
requirements.txt
package.json                 沒有任何相依套件，只宣告 "type": "module" 讓 Node 以 ES module 載入 site/js
pytest.ini
```

**`data/app.db` 不進 git**，`site/data/data.json` 才是存在 git 裡的正式資料。`app.db` 只是本機快取：後台會自動匯出與自動匯入（見「多台電腦同步」），一般情況不需要手動執行 `import_data.py`。

---

## 常用指令

```bash
python3 -m venv .venv && source .venv/bin/activate   # 每台電腦各自建立，.venv 不進 git
pip install -r requirements.txt

# 首次建立資料庫
python scripts/import_heroes.py
python scripts/fetch_avatars.py         # 選用

# 啟動後台（只能用預設 host）
uvicorn admin.main:app --reload
# → http://127.0.0.1:8000/admin

# 匯出資料給選角頁（後台已自動匯出，這個指令主要用來確認；會先讀入外部變更，不會蓋掉較新的 data.json）
python scripts/export_data.py

# 從檔案還原資料庫（一般不需要；後台會自動匯入 git pull 帶來的 data.json）
python scripts/import_data.py [backup.json] [--reset] [--yes]

# 本機預覽選角頁（ES modules 不能用 file:// 開啟，必須透過 HTTP）
python -m http.server 8080 --directory site
# → http://127.0.0.1:8080/

# 測試
pytest
node --test tests/js/*.test.js   # Node 24 不接受目錄參數，需列出檔案
```

---

## 遊戲規則（系統必須符合）

- 5v5，分為**藍方**與**紅方**。使用者在一開始選擇我方是哪一方，之後可以切換。
- **禁用**：雙方各禁 5 隻，共 10 隻，**不可重複**，**沒有先後順序**。
- **選角**：藍方首搶。標準順序為 藍1 → 紅2 → 藍2 → 紅2 → 藍2 → 紅1。
- 同一隻英雄在整場（禁用＋選角）只能出現一次。多型態英雄另有規則，見下方「多型態英雄」。
- 五個分路：`凱撒`、`打野`、`中路`、`魔龍`、`輔助`。
- 六種職業：`坦克`、`戰士`、`刺客`、`法師`、`射手`、`輔助`。每隻英雄有主職業，可選填一個副職業。

### 職業 ≠ 分路（重要）

- **職業只用來分類與篩選**，讓使用者在選角頁、後台快速找到英雄。推薦引擎**完全不使用職業**計算分數。
- **分路只來自後台設定的 `HeroLane`**，和職業無關。例如職業是「輔助」的英雄，也可以設定成走中路。
- 注意分路 `輔助` 和職業 `輔助` 是兩個不同的概念，程式中要用不同的型別或常數區分（例如 `Lane.SUPPORT` 與 `HeroClass.SUPPORT`），不可混用。
- **tier 只存在於「英雄 × 分路」**，沒有英雄層級的整體 tier。同一隻英雄在不同分路可以有不同 tier（例如打野 T0、凱撒 T2）。勾選了分路但沒選 tier 視為「未評」。

### 多型態英雄

- 同一隻英雄的不同型態在資料中是**獨立的兩筆英雄**，例如 `元流之子(法師)` 與 `元流之子(射手)`：各自有頭像、分路、tier、剋制與搭配資料。
- 同一隻英雄的各型態屬於同一個**型態群組**（`form_group`，例如 `元流之子`）。規則：
  - **禁用各自獨立**：禁用其中一個型態，不會連帶禁用另一個；兩個型態可以分別被禁用。
  - **選角互斥**：整場（雙方合計）同一個型態群組**只能選一個型態**。任一方選了 `元流之子(法師)` 之後，`元流之子(射手)` 就不能再被任何一方選。
  - 某型態被禁用時，同群組的其他型態**仍然可以被選**。
- 沒有多型態的英雄 `form_group` 為空，不受上述規則影響。
- 在 `engine.js` 提供 `isPickable(h, state)` 統一判斷「可被選」：未被禁用、未被選、且同 `form_group` 沒有任何型態已被選。所有選角相關的計算與 UI 都使用這個函式，不要各自實作。

---

## 後台資料模型（`admin/models.py`）

不保留版本歷史，修改即覆寫。

```python
class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    main_class: str
    sub_class: str | None = None
    avatar: str | None = None        # site/avatars/ 下的檔名
    form_group: str | None = None    # 多型態英雄的群組名稱，例如「元流之子」
    needs_review: bool = False       # 匯入時職業不合法等需人工確認的情況

class HeroLane(SQLModel, table=True):
    hero_id: int = Field(foreign_key="hero.id", primary_key=True)
    lane: str = Field(primary_key=True)       # 凱撒/打野/中路/魔龍/輔助
    tier: str | None = None                   # "T0" | "T1" | "T2" | None(未評)

class Counter(SQLModel, table=True):
    a_id: int = Field(foreign_key="hero.id", primary_key=True)
    b_id: int = Field(foreign_key="hero.id", primary_key=True)
    value: int        # >0：a 剋 b；<0：b 剋 a

class Synergy(SQLModel, table=True):
    a_id: int = Field(foreign_key="hero.id", primary_key=True)
    b_id: int = Field(foreign_key="hero.id", primary_key=True)
    value: int        # >0：好搭（目前只用 +1 / +2）

class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: float
```

### 關係資料的規則

- **剋制與搭配都沒有數量限制**：每隻英雄可以和任意多隻英雄有剋制或搭配關係。
- **同一對英雄的剋制與搭配互相獨立**，可以同時存在（例如 A 剋 B，但 A、B 同隊也好搭）。
- **只存一筆**：一律以 `a_id < b_id` 存成標準順序。
  - 剋制是**反對稱**：查 `counter(x, y)` 時，若 `x > y` 就讀 `(y, x)` 並把值取負號。
  - 搭配是**對稱**：`synergy(x, y) == synergy(y, x)`。
  - `value == 0` 時刪除該筆資料，不存 0。
- 剋制：UI 寫入 `-2 ~ +2`（±1 一般、±2 強烈）。搭配：UI 只寫入 `+1 / +2`（好搭／超好搭），不使用負值。欄位都是 int。
- 在 `repo.py` 提供 `get_counter(x, y)`、`set_counter(x, y, v)`、`get_synergy`、`set_synergy`，所有讀寫都經過這裡，不要在其他地方直接處理正負號。
- 刪除英雄時，連同其 `HeroLane`、`Counter`、`Synergy` 一起刪除。

### 設定（權重）預設值

| key | 預設 | 說明 |
|---|---|---|
| `w_tier` | 1.0 | tier 分數權重 |
| `w_counter` | 1.0 | 剋制對方已選英雄 |
| `w_synergy` | 0.7 | 與我方已選英雄搭配 |
| `w_risk` | 0.5 | 被反制風險（扣分） |
| `w_deny` | 0.5 | 搶角價值 |
| `w_ban_threat` | 1.0 | 禁用時：對我方已選英雄的威脅 |
| `tier_T0` | 3 | |
| `tier_T1` | 2 | |
| `tier_T2` | 1 | |
| `tier_none` | 0 | 未評 |

---

## `data.json` 格式

由 `scripts/export_data.py` 產生。英雄以**名稱**作為識別，選角頁不需要資料庫 ID。

```json
{
  "exported_at": "2026-11-04T12:00:00+08:00",
  "heroes": [
    {
      "name": "莉莉安",
      "main_class": "法師",
      "sub_class": "刺客",
      "avatar": "莉莉安.jpg",
      "form_group": null,
      "lanes": { "中路": "T0", "打野": null }
    }
  ],
  "counters":  [["莉莉安", "伯頓", 1]],
  "synergies": [["莉莉安", "伯頓", 1]],
  "settings":  { "w_tier": 1.0, "tier_T0": 3 }
}
```

- `counters` 每筆 `[a, b, v]` 表示 `counter(a, b) = v`，每對只出現一次。
- `synergies` 每筆 `[a, b, v]`，每對只出現一次。
- `lanes` 的值是 tier 字串，`null` 表示有走這路但未評級。沒有任何分路的英雄，`lanes` 為 `{}`。
- `avatar` 沒有頭像時為 `null`。
- `needs_review`（後台用，選角頁忽略）只在為 `true` 時輸出，以便在多台電腦間保留「待確認」狀態。
- 輸出時依名稱排序，並採用**一筆一行**的格式，讓 git diff 與合併容易閱讀：每隻英雄、每筆剋制、每筆搭配各佔一行，`settings` 為一行。不可直接用 `json.dump(indent=2)`（會把每筆關係拆成多行）。輸出仍須是合法 JSON。

```json
{
  "exported_at": "2026-11-05T12:00:00+08:00",
  "heroes": [
    {"name": "伯頓", "main_class": "坦克", "sub_class": "輔助", "avatar": "伯頓.jpg", "form_group": null, "lanes": {"輔助": "T1"}},
    {"name": "莉莉安", "main_class": "法師", "sub_class": "刺客", "avatar": "莉莉安.jpg", "form_group": null, "lanes": {"中路": "T0", "打野": null}}
  ],
  "counters": [
    ["伯頓", "莉莉安", -1],
    ["伯頓", "綺蘿", 1]
  ],
  "synergies": [
    ["伯頓", "莉莉安", 1]
  ],
  "settings": {"tier_T0": 3, "w_tier": 1.0}
}
```

`import_data.py` 做相反的事：清空資料庫後從 `data.json` 重建（執行前要求確認）。

---

## 初始資料匯入：`scripts/import_heroes.py`

讀取 `data/heroes.csv`（UTF-8 with BOM），欄位：

| 欄位 | 說明 |
|---|---|
| `name` | 英雄名稱（台服名稱，多型態英雄以括號區分，例如 `元流之子(法師)`） |
| `classes` | `主職業\|副職業`，可能只有主職業 |

- 職業值必須是六種職業之一。不合法的值（例如分路名稱 `中路`）**不要匯入**，在終端機列出警告，並把該英雄設為 `needs_review = True`。
- 名稱符合 `名稱(型態)` 格式時（例如 `元流之子(法師)`），自動把 `form_group` 設為括號前的名稱。
- 已存在同名英雄時跳過，不覆寫（重複執行要安全）。
- 不匯入分路、tier、剋制、搭配，這些都在後台輸入。
- 同時寫入「設定」的預設權重（若尚未存在）。

## 英雄頭像：`scripts/fetch_avatars.py`

**來源：越南官方網站的英雄列表頁** `https://lienquan.garena.vn/hoc-vien/tuong-skin/`。
這個做法參考自開源專案 aov-scrapecore（MIT License）的 `scrapecore/services/scraper_service.py`，它用以下 CSS selector 解析該頁：

| 資料 | selector |
|---|---|
| 每位英雄 | `.st-heroes__list .st-heroes__item`（`href` 為介紹頁連結） |
| 名稱（越南版／國際版名稱） | `.st-heroes__item--name` |
| 頭像 | `.st-heroes__item--img img` 的 `src` |
| 職業 ID | 英雄項目的 `data-type` 屬性（JSON 陣列） |

職業 ID 對應（同樣來自 aov-scrapecore 的 `constants.py`）：`28` 戰士、`31` 坦克、`29` 法師、`32` 刺客、`30` 輔助、`33` 射手。

**流程：**

1. 抓取上述列表頁，**先確認 selector 仍然有效**（網站可能改版），向我回報抓到的英雄數量與前 5 筆結果，確認後再繼續。
2. 越南版名稱和台服名稱不同，需要一份對照表 `data/name_map.csv`（欄位：`tw_name`, `vn_id`, `vn_name`, `confidence`）。`vn_id` 是越南官網英雄介紹頁網址的最後一段（例如 `.../tuong-skin/d/airi/` 的 `airi`），**以 `vn_id` 比對**，因為多型態英雄的 `vn_name` 會重複（元流之子的兩個型態都叫 `Flowborn`，`vn_id` 分別是 `flowborn-2`（法師）與 `flowborn`（射手））。
   - `data/name_map.csv` 已有一份草稿，`confidence` 為 `高` 或 `中`。請以它為基礎，補上尚未對照的英雄；`中` 與新補上的對照要列出來讓我確認。
   - 我確認並修正對照表之後，才進行下載。
3. 依對照表下載頭像到 `site/avatars/{台服英雄名}.jpg`（依原始副檔名），並更新 `Hero.avatar`。**不要在頁面中直接引用外部圖片網址。**
4. 回報兩份清單：資料庫中有但對照不到的英雄、越南網站有但資料庫沒有的英雄。
5. 已經有頭像的英雄跳過（包含我手動上傳的），除非加上 `--force`。
6. 請求之間加入延遲，避免對官方網站造成負擔。
7. **不要**用越南官網的職業覆寫資料庫：`heroes.csv` 的職業是我整理確定的版本。

對照不到或新出的英雄，由我在後台手動上傳頭像。
沒有頭像時，前端顯示「主職業顏色底 + 英雄名稱首字」的佔位圖。
選角頁底部加一行註明：本工具為非官方粉絲作品，與 Garena 無關；英雄頭像與名稱版權屬於 Garena。

---

## 推薦引擎（`site/js/matching.js`、`site/js/engine.js`）

**純函式**：只接收資料與狀態、回傳結果，不讀寫 DOM、不呼叫 fetch。`app.js` 負責載入 `data.json` 並呼叫它們。這樣才能用 `node --test` 測試。

### 輸入

```js
// DraftState
{
  side: "blue" | "red",
  bansUs: string[],     // 最多 5
  bansThem: string[],
  picksUs: string[],    // 最多 5
  picksThem: string[]
}
```

推薦**只依據目前狀態計算**，不追蹤「現在是第幾步」，所以使用者可以用任意順序填入。

`engine.js` 載入資料時，把 `counters` 與 `synergies` 建成查詢表，提供 `getCounter(x, y)`（反對稱，自動處理正負號）與 `getSynergy(x, y)`（對稱）。不存在的組合回傳 0。

### 分路匹配（`matching.js`）

- 以二分圖最大匹配判斷一組英雄能否各自分配到不同分路（英雄 → 其 `lanes` 中的分路）。
- `feasible(heroes)`：最大匹配數等於英雄數。
- `openLanes(heroes)`：分路 `l` 為「仍可補」的條件是，加入一隻只能走 `l` 的虛擬英雄後仍然 `feasible`。
- `fillableLanes(h, team)`：候選英雄 `h` 加入後仍 `feasible` 時，`h` 可以走的分路集合。
- **尚未填分路的英雄**（`lanes` 為 `{}`）視為可走任何分路、tier 為未評，並在推薦理由中標示「分路資料未填」。

### 選角評分（候選 `h` 為 `isPickable` 的英雄）

若 `h` 加入我方後不 `feasible`（會撞路），排除；但若所有候選都被排除（資料不完整時），改為不過濾。

```
tier(h)    = max( tierValue(h, l) for l in fillableLanes(h, us) )
counter(h) = Σ_{e ∈ picksThem} getCounter(h, e)
synergy(h) = Σ_{a ∈ picksUs} getSynergy(h, a)
risk(h)    = (enemyRemaining / 5) × Σ_{x ∈ threats(h)} getCounter(x, h)
             threats(h) = isPickable、getCounter(x, h) > 0、
                          且能補對方 openLanes 的英雄 x
             enemyRemaining = 5 - picksThem.length
deny(h)    = Σ_{a ∈ picksUs} max(0, getCounter(h, a))，
             只在 h 能補對方 openLanes 時計算，否則為 0

score = w_tier·tier + w_counter·counter + w_synergy·synergy
        − w_risk·risk + w_deny·deny
```

設計意圖：對方剩越多選角，越要避開容易被反制的英雄，所以藍方首搶會偏向強勢且難被剋的英雄，紅方最後一手則接近純反制。

### 禁用評分

候選為所有未被禁用、未被選的英雄（禁用不受型態互斥影響：同群組另一型態已被選時，這個型態仍可被禁用，但因為已經不可能被選，禁用分數視為 0 並排到最後）：

```
banScore(h) = w_tier · maxTier(h)
            + w_ban_threat · Σ_{a ∈ picksUs} max(0, getCounter(h, a))
```

`maxTier(h)` 是該英雄所有分路中最高的 tier 分數。雙方已禁用的英雄自動排除，所以對方禁用後，我方建議會自動補上下一順位。

### 輸出

回傳**所有**候選英雄（選角時為 `isPickable` 的英雄；禁用時見上方），依分數由高到低排序。每個建議包含：

```js
{
  name: "綺蘿",
  score: 5.3,                 // 總分
  lanes: ["打野"],            // 可補的分路
  pros: [                     // 加分項目，依貢獻由大到小
    { text: "T0 打野", value: 3.0 },
    { text: "剋制 莉莉安", value: 1.0 }
  ],
  cons: [                     // 扣分項目，依影響由大到小
    { text: "被 伯頓 剋", value: -1.0 },
    { text: "對方仍可選 奎倫 反制", value: -0.5 }
  ]
}
```

- `pros` 與 `cons` 列出**所有**非零的貢獻項目，不限數量；剋制、搭配要拆成「每一隻相關英雄一條」，而不是只給加總。
- 分數為 0 的項目不列出。
- 尚未填分路的英雄，在 `cons` 加一條 `分路資料未填`（value 為 0，僅提示）。

另外附上雙方的 `openLanes`。

---

## 選角頁 UI（`site/index.html`、`site/js/app.js`）

橫向版面，參考遊戲內選角畫面：

```
┌───────────────────────────────────────────┐
│ [我方禁用 ×5]   陣營切換／階段／目前格子   [敵方禁用 ×5] │
├────────┬─────────────────────────┬────────┤
│ 我方1  │ 共用篩選：職業｜分路｜搜尋 │  敵方1 │
│ 我方2  ├────────────┬────────────┤  敵方2 │
│ 我方3  │ 建議清單     │ 英雄格子     │  敵方3 │
│ 我方4  │（全部英雄、  │（快速輸入、  │  敵方4 │
│ 我方5  │ 分數＋優缺點）│ 排序切換）   │  敵方5 │
└────────┴─────────────────────────┴────────┘
```

- **我方永遠在左側**；左右欄的顏色依陣營（藍／紅）顯示。
- 左右選角欄寬度較窄（最大約 240px），把空間留給中間區域。
- 頂部中央：陣營切換按鈕（藍方（首搶）／紅方）、「清空」按鈕、目前階段（禁用階段／選角階段）、目前作用中格子的文字提示。
- 每個選角格顯示：頭像、英雄名或「點此填入」、`我方 N 樓 · 第 K 手`（依標準順序與陣營計算）。
- 頁面 `<title>` 與頁首左上角顯示 `Best Ban & Pick`（窄螢幕可只顯示 `BBP`）。後台頁面 `<title>` 為 `BBP 後台`。
- 頁面底部顯示 `data.json` 的 `exported_at`（資料更新時間）、「非官方工具」聲明與 Garena 版權註明。
- `data.json` 載入失敗時，顯示清楚的錯誤訊息，而不是空白頁。

### 輸入流程（自由順序）

1. 任一時刻都有一個「作用中格子」，以金色框標示。
2. 預設作用中格子 = 依標準流程的第一個空格（先雙方禁用，再依藍紅選角順序）。
3. 使用者可以點任何格子，手動指定作用中格子。
4. 點中間的英雄 → 填入作用中格子 → 作用中格子回到「下一個空格」。
5. 已填的格子有 × 按鈕可以清除；清除後該格成為作用中格子。
6. 每次狀態改變都重新計算建議。
7. 狀態存在 `sessionStorage`，重新整理後可還原；讀寫都要包在 try/catch 裡。

### 中間區域

由上而下分成：

**共用篩選列**：職業頁籤（全部、坦克、戰士、刺客、法師、射手、輔助）、分路篩選、名稱搜尋。**同時套用到下方的建議清單與英雄格子**（例如選「刺客」時，兩邊都只顯示刺客）。

篩選列下方分成兩塊，寬螢幕時左右並排，寬度比例約 **3:2**（建議清單：英雄格子）；窄螢幕時上下排列。兩塊高度相同且固定，內容超出時**各自在區塊內捲動**（滑鼠滾輪或觸控滑動），頁面本身不跟著捲動。

**A. 建議清單（左）**

- 列出**所有尚未被禁用或選擇的英雄**，依建議分數由高到低排列。
- 區塊標題依作用中格子切換：禁用格 → 「禁用建議」；我方選角格 → 「選角建議」；敵方選角格 → 「敵方選角中（以下為我方下一手參考）」，分數照常計算。標題右側顯示「共 N 隻可選」。
- 每一列顯示：
  - 第一行：排名、頭像、英雄名稱、職業與可補分路（例如 `法師/刺客 · 中路`）、最右側的**分數**（一位小數，正分綠色、負分紅色，並帶 `+`／`−` 符號）。
  - 下方：`pros`（綠色、以 `+` 開頭）與 `cons`（紅色、以 `−` 開頭），每項後面附上該項的分數，例如 `+ 剋制 莉莉安  +1.0`。顏色之外也要有 `+`／`−` 符號，不可只靠顏色區分。
  - `pros`／`cons` 預設各顯示前 2 條，其餘收合，按鈕顯示「更多（+n）」，展開後變成「收合」。
- 前 3 名的排名以金色圓形標示，該列背景略亮。
- 點擊列中的英雄 → 填入作用中格子。

**B. 英雄格子（右）**

- 區塊標題列右側有排序切換（推薦排序／預設）。
- 英雄頭像格子，用來快速點選輸入。推薦排序時依分數排列，前 3 名加上「推薦」角標與金色外框。
- 已禁用或已選的英雄反灰，並標示「已禁」「我方」「敵方」，不可點選（建議清單則直接不顯示這些英雄）。
- 同型態群組已有其他型態被選時，該英雄反灰並標示「型態已選」：作用中格子是**選角格**時不可點選；是**禁用格**時仍可點選（允許禁用）。

### 響應式

以橫向（手機橫拿、平板、電腦）為主要設計目標。窄螢幕直向時改為上下排列：禁用列 → 我方 → 英雄選擇區 → 敵方。

---

## 後台 UI（`admin/`，`http://127.0.0.1:8000/admin`）

### 左側：英雄清單

- 搜尋框、職業篩選。
- 每列顯示：頭像、名稱、各分路與 tier 小標籤；`needs_review` 的英雄加上「待確認」標記；尚未設定分路的英雄加上「未設定分路」標記。
- 最上方「新增英雄」按鈕。
- 清單上方顯示進度統計：已設定分路的英雄數、有剋制資料的英雄數、待確認數。

### 右側：英雄編輯區（新增與修改共用）

1. **基本資料**：名稱、主職業、副職業、型態群組（`form_group`，由名稱自動決定、唯讀顯示）、頭像上傳、「標記為已確認」、刪除按鈕（需二次確認）。
2. **分路與 tier**（和下方的剋制、搭配在**同一個畫面**設定）：
   - 五個分路各一列：勾選框 ＋ `T0 / T1 / T2 / 未評` 選項。勾選後才能選 tier，取消勾選時一併清除該分路的 tier。
   - 每個分路的 tier 各自獨立設定。
   - 變更即時存檔（HTMX），不需要「儲存」按鈕。
   - 區塊旁顯示職業，但標明「職業僅供分類，不影響分路」。
3. **剋制與搭配**：其他所有英雄的頭像格子，可依職業或分路篩選、可搜尋。每格有兩個切換按鈕：
   - **對位**：無 → 剋他(+1) → 超剋他(+2) → 被他剋(−1) → 被他完剋(−2) → 無
   - **搭配**：無 → 好搭(+1) → 超好搭(+2) → 無（不設定難搭）
   - 狀態以顏色與文字同時表示（不可只靠顏色）。
   - 每次點擊立即透過 HTMX 存檔，不需要「儲存」按鈕。

### 其他頁面

- **設定**：編輯權重與 tier 分數。
- **匯出**：按鈕執行與 `export_data.py` 相同的匯出，完成後顯示匯出的英雄數與關係筆數，並提醒「記得 commit 並 push」。

---

## 部署：`.github/workflows/deploy.yml`

push 到 `main` 時，直接把 `site/` 資料夾發佈到 GitHub Pages（不需要建置步驟）：

```yaml
name: Deploy to GitHub Pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - uses: actions/deploy-pages@v4
        id: deployment
```

另外新增一個測試 workflow（push 與 pull request 時執行 `pytest` 和 `node --test tests/js/*.test.js`）。

---

## 測試（至少涵蓋）

**pytest（後台）**
- `get_counter` / `set_counter` 的反對稱與標準順序；`synergy` 的對稱；`value == 0` 時刪除。
- 刪除英雄時一併刪除相關資料。
- 匯出再匯入後，資料完全相同。

**node --test（推薦引擎）**
- 分路匹配：`feasible`、`openLanes`、多分路英雄、未填分路的英雄。
- 選角評分：撞路的英雄被排除；剋制與搭配會對所有已選英雄加總；`enemyRemaining` 越多，`risk` 影響越大。
- 輸出：回傳所有未被禁用、未被選的英雄；`pros` 的 value 皆 > 0、`cons` 皆 ≤ 0；`score` 等於所有項目加總。
- 禁用評分：已禁用、已選的英雄不出現在建議中。
- 多型態：禁用一個型態後，另一型態仍 `isPickable`；選了一個型態後，另一型態不再 `isPickable`（雙方皆然），但仍可被禁用；`threats` 與 `openLanes` 的預測也排除不可選的型態。

## 開發順序

1. 後台：資料模型、`repo.py`、`import_heroes.py`、英雄清單與編輯（基本資料、分路 tier、剋制搭配），以及自動同步所需的匯出／匯入核心（寫入後自動匯出、`data.json` 變更時自動匯入）。
2. `export_data.py`、`import_data.py` 命令列腳本、後台匯出按鈕與設定頁。
3. 推薦引擎（`matching.js`、`engine.js`）與測試。
4. 選角頁 UI。
5. `fetch_avatars.py`（照上方「先檢查再下載」的流程）。
6. GitHub Actions 部署與測試 workflow。

每完成一個階段先停下來，讓我確認再進行下一個。

---

## 已確認的實作決定（2026-11-05）

以下為規格討論後確認的補充，與上方規格同等效力。

### 第 1 階段（後台）

- **主職業不合法**（`import_heroes.py`）：若副職業合法，將副職業升為主職業；否則 `main_class` 存空字串。兩種情況都設 `needs_review = True` 並在終端機警告。後台編輯時強制要求補上主職業。
- **副職業不可與主職業相同**；副職業不合法時留空並設 `needs_review = True`。
- **英雄改名**：同時把 `site/avatars/` 下的頭像檔改名為新名稱，並更新 `Hero.avatar`。
- **頭像上傳**：接受 jpg / png / webp，依原始副檔名存成 `{英雄名}.{ext}`；若已有不同副檔名的舊檔則刪除。不做縮圖、不依賴 Pillow。頁面引用時加 `?v={mtime}` 避免快取。
- **HTMX**：下載 `htmx.min.js` 放在 `admin/static/`，不使用 CDN。
- **進度統計「有剋制資料的英雄數」**：英雄只要出現在任何一筆 `Counter`（不論是 `a_id` 或 `b_id`）就計入。
- **禁止英雄與自己建立剋制或搭配關係**（`repo.py` 遇到 `x == y` 時拋出錯誤）。
- **分路勾選後 tier 預設為「未評」**（`None`）。
- **剋制／搭配強度**：剋制按鈕循環五種狀態、搭配按鈕循環三種狀態（見「後台 UI」），±2 以較深的實心底色顯示；超出範圍的值點擊時先視為最接近的合法值再往下循環，搭配若有舊的負值則點擊後清除。
- **刪除英雄時一併刪除頭像檔**。
- **英雄名稱驗證**：不可為空、不可含 `/ \ : * ? " < > |`，前後空白自動去除；全形括號 `（）` 自動轉為半形 `()`（匯入與後台編輯皆適用）。
- **`form_group` 完全由名稱決定，不可手動輸入**：名稱為 `名稱(型態)` 時 `form_group` = 括號前的名稱，否則為 `None`。匯入、新增、改名時都由 `repo.py` 統一計算；後台只唯讀顯示。
- **權重預設值**：後台每次啟動時檢查 `Setting`，缺少的 key 補上預設值，已存在的不動。
- **主職業為空時「標記為已確認」不可點**，並提示先補主職業。

### 第 2 階段（匯出／匯入、設定、匯出頁）

- **`export_data.py` 與後台「立即匯出」共用 `sync.export_now`**：先執行同步檢查（若 `data.json` 被外部改動就先匯入），再匯出；內容沒變時不重寫檔案。
- **`import_data.py`**：預設從 `site/data/data.json` 重建；可指定其他檔案還原，此時同時覆寫 `site/data/data.json`。執行前顯示內容摘要並要求輸入 `y`（`--yes` 略過）。預設保留既有英雄的 id（後台開著也不受影響）；`--reset` 會刪除並重建所有資料表，需先停止後台。
- **設定頁**：每個欄位變更即時存檔（HTMX），數值限制在 −100 ~ 100，顯示預設值與「已修改」標記，提供「恢復預設值」（需確認）。
- **匯出頁**：顯示 `data.json` 的英雄數、剋制／搭配筆數、資料時間，以及 `site/` 底下尚未 commit 的檔案與尚未 push 的 commit（唯讀執行 `git status`），並附上建議指令。
- 後台頁首加入「英雄／設定／匯出」導覽。

### 第 3 階段（推薦引擎）

- **API**：`matching.js` 的函式接收「每隻英雄可走的分路陣列」（空陣列＝未填分路＝任何分路）：`feasible`、`openLanes`、`fillableLanes(candidateLanes, teamLaneLists)`、`assignLanes`。`engine.js` 提供 `createEngine(data)`，回傳 `getCounter`、`getSynergy`、`isPickable(name, state)`、`openLanes(state)`、`pickSuggestions(state)` → `{ suggestions, openLanes: { us, them } }`、`banSuggestions(state)` → `{ suggestions }`。
- **理由文字**：剋制 ±1／±2 分別為「剋制 X」「超剋 X」／「被 X 剋」「被 X 完剋」；搭配為「與 X 好搭」「與 X 超好搭」；搶角為「搶角：避免對方用來剋 X」；禁用威脅為「剋制我方 X」「超剋我方 X」；同群組其他型態已被選時，禁用建議的 `cons` 為「同英雄的其他型態已被選」，並帶 `blocked: true`。
- **同分排序**：分數相同時依名稱（字碼順序）排序，結果固定。
- **型態群組與反制風險**：候選 `h` 的同群組其他型態不算 `h` 的威脅（選了 `h` 之後它們就不能被選）。
- **state 中的未知英雄名稱**（例如資料改名後 sessionStorage 的舊狀態）直接忽略。
- **tier 分數為 0 的項目不列出**；未填分路的英雄 tier 文字為「未評（分路未填）」（只在 `tier_none` 被設為非 0 時出現）。

### 之後階段

- `pros` / `cons` 的 `value` 為**乘上權重後**的值，使 `score` 等於所有項目加總。
- 第 3 階段需要 Node.js（20 以上）。

### 多台電腦同步（兩台皆為 WSL，以 git pull / push 同步）

`data.json` 是唯一正式資料，`app.db` 為可隨時重建的本機快取，不進 git。

- **自動匯出**：後台每次寫入（英雄、分路、剋制、搭配、設定、頭像）成功後，立即重寫 `site/data/data.json`。因此資料庫永遠不會有「尚未匯出的修改」。
- **自動匯入**：資料庫記錄上次同步時 `data.json` 的內容雜湊。後台啟動時、以及每次請求時（先比對檔案 mtime，有變才算雜湊）發現 `data.json` 被外部改動（例如 `git pull`），就自動清空資料庫並從 `data.json` 重建，並在頁面顯示提示橫幅。
- `data.json` 不存在時（全新環境），以現有資料庫匯出一次；兩者都沒有時提示先執行 `import_heroes.py`。
- `data.json` 格式錯誤（例如合併衝突標記沒清乾淨）時，**不要**覆寫資料庫也不要覆寫檔案，在後台顯示錯誤並停止寫入，直到修好為止。
- `.gitattributes` 設定 `* text=auto eol=lf`。

### Git

- **所有 git commit 與 push 由使用者自行執行**。Claude 不執行 `git add` / `commit` / `push` 等會改變 git 狀態的指令，只在每個段落完成時提供建議的 commit 訊息與指令。
- 預設分支為 `main`（部署 workflow 依此觸發）。

## 不在第一版範圍

- 使用者帳號、多人共用資料、線上編輯。
- 版本歷史。
- 自動抓取勝率或對戰數據。
- 機器學習模型。
