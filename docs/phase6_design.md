# Phase 6：フロントエンド UI（最低限） 詳細設計

> 対象期間：3〜5 日
> ゴール：「**curl じゃなく画面で**タスクを追加・最適化・カレンダー反映」できる。
> 参照：`project_plan.md` §2.3（フロント技術）、`docs/phase1〜5_design.md`（バックエンド API）

---

## 0. このフェーズの位置づけ

**やること:**
- バックエンドの主要 API を画面から叩ける状態にする
- 毎日の使用に耐える最低限の UX
- ローカル開発（`http://localhost:5173` から `http://localhost:8000` を叩く）前提

**やらないこと（Phase 6 の polish 段階に回す）:**
- ドラッグ&ドロップでのタスク並び替え（curl の `position` で代替可）
- アニメーション・凝った遷移
- ダークモード切替
- モバイル最適化（PWA 化は後）
- テスト網羅（バックエンドと違って Phase 6 ではスモークテストのみ）

**Phase 5 との関係：**

```
[Phase 5]                         [Phase 6]
バックエンド API 完成      ←─→     React UI が叩く
   ↓                                    ↓
Google Calendar             ←─        反映ボタンで連動
```

---

## 1. 主要設計判断

| 判断 | 値 | 理由 |
|---|---|---|
| **フレームワーク** | React 18 + Vite + TypeScript | Phase 0 で雛形作成済 |
| **UI ライブラリ** | shadcn/ui + Tailwind CSS | Vite と相性◎、コンポーネント単位で取り込めて軽い |
| **状態管理** | TanStack Query + ローカル `useState` | サーバー状態は Query、UI 状態は useState で十分 |
| **ルーティング** | React Router v6 | 画面少ないので軽量に |
| **フォーム** | React Hook Form + Zod | バックエンドの Pydantic スキーマと型を合わせやすい |
| **API クライアント** | 手書き fetch ラッパー（Phase 7 で OpenAPI 自動生成検討） | OpenAPI codegen 入れる手間 vs 画面少ない、手書きで十分 |
| **認証** | バックエンドの `POST /auth/google/local` を画面から叩く | ブラウザが自動で開いて Google にリダイレクトされる仕組み |
| **CORS** | dev のみ：FastAPI 側で `allow_origins=["http://localhost:5173"]` | 本番化は Phase 7 で別検討 |

---

## 2. 画面構成

最低限 4 画面 + 設定:

```
┌──────────────────────────────────────────────────────────────┐
│  Header: アプリ名 / ログイン状態 / 設定リンク                │
├────────────┬─────────────────────────────────────────────────┤
│ Sidebar    │ Main                                            │
│            │                                                 │
│ □ 勉強     │ ┌──────────────────────────────────────────┐   │
│ □ 雑用     │ │ タスク一覧 / 追加フォーム                │   │
│            │ │                                          │   │
│ + リスト   │ │ [Optimize] ボタン                        │   │
│            │ │                                          │   │
│            │ └──────────────────────────────────────────┘   │
│            │ ┌──────────────────────────────────────────┐   │
│            │ │ 最適化結果プレビュー / [Apply to Calendar]│  │
│            │ └──────────────────────────────────────────┘   │
└────────────┴─────────────────────────────────────────────────┘
```

### 2.1 ルート

| パス | 画面 |
|---|---|
| `/login` | OAuth 開始（未ログイン時にリダイレクト） |
| `/` | メイン画面（リスト一覧 + タスク管理 + 最適化結果） |
| `/settings` | 設定（work_hours, day_type, location_commutes, calendar_location_rules） |

ルーティング階層は浅く保つ。

### 2.2 メイン画面の構成要素

1. **TaskListSidebar**：左サイドにタスクリスト一覧（Google ToDo 風）
2. **TaskTable**：選択中リストのタスクを編集可能なテーブルで表示
   - 列：タイトル / 所要時間 / 優先度 / 締切 / 場所 / 完了
   - インライン編集（クリックで入力可）
3. **AddTaskForm**：新規タスクのクイック追加（タイトル + Enter で詳細はデフォルト）
4. **OptimizePanel**：
   - 期間入力（来週いっぱいなど）
   - [Optimize] ボタン
   - 結果が出たら下に表示（タスクごとに `[いつ・どこで・何分]`）
   - [Apply to Calendar] ボタン
   - [Dry-run] チェックボックス

### 2.3 設定画面の構成

タブ分け（縦並びでも横並びでも）:
1. **作業時間** — 曜日ごとの slot を編集（HH:MM 入力 + 追加/削除）
2. **日タイプルール** — DSL を JSON エディタで（Phase 6 では JSON のまま、polish 段階で UI 化）
3. **場所ルール** — `calendar_location_rules` をテーブル編集
4. **通学/通勤・linger** — `location_commutes` を場所ごとに数値入力

---

## 3. ディレクトリ構成

```
frontend/src/
├── api/
│   ├── client.ts          fetch ラッパー（baseURL + エラー型 + 401 リダイレクト）
│   ├── auth.ts            POST /auth/google/local, GET /auth/me
│   ├── lists.ts           CRUD
│   ├── tasks.ts           CRUD + complete/uncomplete/move
│   ├── slots.ts           GET /calendar/slots
│   ├── optimize.ts        POST /optimize, snapshots/{id}/apply, /write
│   ├── settings.ts        GET/PUT /settings
│   └── types.ts           ★ バックエンドのスキーマと対応する TS 型を集約
├── hooks/
│   ├── useAuth.ts         ログイン状態のクエリ
│   ├── useLists.ts        TanStack Query wrapper
│   ├── useTasks.ts        同上
│   └── useOptimize.ts     最適化実行 + 結果保持
├── components/
│   ├── layout/
│   │   ├── Header.tsx
│   │   └── Sidebar.tsx
│   ├── task/
│   │   ├── TaskTable.tsx
│   │   ├── TaskRow.tsx
│   │   └── AddTaskForm.tsx
│   ├── optimize/
│   │   ├── OptimizePanel.tsx
│   │   └── ResultPreview.tsx
│   └── settings/
│       ├── WorkHoursForm.tsx
│       ├── DayTypeJsonEditor.tsx
│       ├── LocationRulesTable.tsx
│       └── CommutesForm.tsx
├── pages/
│   ├── LoginPage.tsx
│   ├── MainPage.tsx
│   └── SettingsPage.tsx
├── App.tsx                ルーティング + QueryClientProvider
└── main.tsx
```

---

## 4. API クライアント設計

### 4.1 fetch ラッパー（`api/client.ts`）

```typescript
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (res.status === 401) {
    // 未ログイン or トークン期限切れ → /login へ
    window.location.href = "/login";
    throw new Error("not_authenticated");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export class ApiError extends Error {
  constructor(public status: number, public detail: any) {
    super(detail?.detail?.message ?? "API error");
  }
}
```

### 4.2 型定義（`api/types.ts`）

バックエンドの Pydantic と同期する手書き型:

```typescript
export type Location = "home" | "university" | "office" | "anywhere";

export interface Task {
  id: string;
  list_id: string;
  title: string;
  notes: string | null;
  duration_min: number;
  priority: number;          // 1-5
  deadline: string | null;   // ISO8601
  location: Location | null;
  completed: boolean;
  scheduled_start: string | null;
  scheduled_end: string | null;
  // ...
}

export interface Slot {
  id: string;
  start: string;
  duration_min: number;
  energy_score: number;
  allowed_max_task_duration_min: number;
  day_type: string;
  location: Location;
}

export interface OptimizeResponse {
  status: "optimal" | "feasible" | "infeasible" | "timed_out" | "error";
  objective_value: number | null;
  snapshot_id: string;
  assignments: TaskAssignmentRead[];
  unassigned: { task_id: string; task_title: string }[];
  solve_time_sec: number;
}
// ...
```

OpenAPI から自動生成（`openapi-typescript`）に切り替える選択肢もあるが、Phase 6 は手書き。

### 4.3 TanStack Query の典型的な使い方

```typescript
// hooks/useTasks.ts
export function useTasks(listId: string) {
  return useQuery({
    queryKey: ["tasks", listId],
    queryFn: () => apiFetch<Task[]>(`/lists/${listId}/tasks`),
    enabled: !!listId,
  });
}

export function useCreateTask(listId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TaskCreate) =>
      apiFetch<Task>(`/lists/${listId}/tasks`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", listId] }),
  });
}
```

---

## 5. 認証フロー（ブラウザから）

複雑なので分離して書く。Phase 1 で実装した `POST /auth/google/local` は **サーバー側**でブラウザを開く。これだと dev では同じ Mac なので動くが、UX 的には「フロントの中でボタンを押したら新しいタブで Google 認可画面が開く」が普通。

**MVP 方針：**
- フロントの「ログイン」ボタンを押す → `POST /auth/google/local` を fetch
- バックエンドが `flow.run_local_server(...)` でローカルブラウザを開く（同じ Mac なので問題なし）
- 認可完了 → fetch のレスポンスが返ってくる → フロントが画面遷移

開発環境で Mac ローカル運用前提なら **これで十分**。クラウド化したくなったら Phase 7 で proper Web flow に移行（[project_plan.md §8.2 Step B](../project_plan.md)）。

---

## 6. CORS 対応

バックエンドに以下を追加（`app/main.py`）:

```python
from fastapi.middleware.cors import CORSMiddleware

if settings.app_env == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

`prod` では制限。

---

## 7. ページ別仕様

### 7.1 LoginPage

シンプル:
- 「Google でログイン」ボタン 1 つ
- 押したら `POST /auth/google/local` → 完了したらホームへ
- すでにログイン済 (`GET /auth/me` 200) なら `/` にリダイレクト

### 7.2 MainPage

#### 構成
- 左：`TaskListSidebar`
- メイン上部：`TaskTable` + `AddTaskForm`
- メイン下部：`OptimizePanel`

#### TaskTable のインライン編集
- 各セルクリックで input になる
- onBlur or Enter で `PATCH /tasks/{id}` 実行
- TanStack Query の `optimisticUpdate` で即時反映、失敗したらロールバック

#### OptimizePanel のフロー
1. 期間入力（既定：今日〜7 日後）
2. [Optimize] ボタン → loading 表示
3. レスポンスを `ResultPreview` に渡して表示
4. [Apply to Tasks] でタスクの `scheduled_*` を埋める
5. [Write to Calendar] で実カレンダーに反映 (`POST /optimizer/snapshots/{id}/write`)
6. [Dry run] チェックがあれば書き込みなし

### 7.3 SettingsPage

- タブで切り替え（タブ自体は CSS で簡易実装）
- 各セクションに「保存」ボタン → `PUT /settings` で部分更新
- 通常時は read mode、編集ボタン押すと edit mode

#### 既定値リセット
- 設定画面の隅に [既定値に戻す] ボタン → `POST /settings/reset`
- 確認ダイアログ表示

---

## 8. 開発・運用

### 8.1 起動コマンド

```bash
# ターミナル A
cd backend
uv run uvicorn app.main:app --reload --port 8000

# ターミナル B
cd frontend
pnpm dev
# → http://localhost:5173 を開く
```

### 8.2 環境変数

`frontend/.env`（任意）：

```
VITE_API_BASE=http://localhost:8000
```

未設定なら `http://localhost:8000` を既定で使う。

---

## 9. テスト戦略

Phase 6 はテストを最小化:
- バックエンドのテストはすでに 84 件あるので、UI 側はスモークテストのみ
- Vitest で API クライアントの fetch ラッパーをモックテスト（401 リダイレクト動作の確認程度）
- E2E（Playwright）は Phase 6 の polish 段階で導入検討

---

## 10. 実装順

1. shadcn/ui + Tailwind 導入（ボイラープレート整備）
2. ルーティング + QueryClientProvider 設定
3. `api/` 層（fetch ラッパー + 各エンドポイントの関数 + 型）
4. LoginPage（最小）
5. TaskListSidebar + useLists hook
6. TaskTable + useTasks hook（読み取りのみ）
7. AddTaskForm（作成）
8. TaskTable のインライン編集（更新）
9. OptimizePanel + ResultPreview（最適化結果表示）
10. Apply to Tasks ボタン
11. Calendar Write ボタン（Phase 5 の API を呼ぶ）
12. SettingsPage（最低限の編集 UI）
13. CORS 追加 + 本番モードで弾く設定
14. スモークテスト + ドキュメント更新

---

## 11. Phase 6 完了の判定

- [ ] ブラウザで `http://localhost:5173` を開いてログインできる
- [ ] タスクを追加・編集・削除・完了できる
- [ ] [Optimize] を押すと結果が画面に出る
- [ ] [Write to Calendar] を押すと実カレンダーに予定が入る
- [ ] [Settings] で work_hours と location_commutes を画面から編集できる
- [ ] iPhone から同じ Wi-Fi 経由で Mac の IP を直叩きすれば動く（CORS 対応済）

---

## 12. このフェーズで残す未解決事項（Phase 7+）

- **PWA 化**：iPhone のホーム画面に追加できる
- **ドラッグ&ドロップ**：dnd-kit でタスク並び替え
- **アニメーション**：framer-motion で遷移
- **ダークモード**：Tailwind の dark variant
- **モバイル最適化**：レスポンシブ + タッチ操作
- **OpenAPI 自動生成**：`openapi-typescript` で型を自動同期
- **クラウドホスティング**：Fly.io / Cloud Run（[project_plan.md §8.2](../project_plan.md)）
