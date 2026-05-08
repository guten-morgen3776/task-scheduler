# API 基本操作 早見表（Phase 0/1）

> 現状実装されているエンドポイントを curl で叩く際のリファレンス。
> 実験・動作確認用。OpenAPI ドキュメント版は http://localhost:8000/docs。

---

## 0. 前提

### サーバー起動

```bash
cd /Users/aokitenju/task-scheduler/backend
uv run uvicorn app.main:app --reload --port 8000
```

別ターミナルで以下を叩く。

### 環境変数（任意）

curl を叩きやすくするために置いておくと便利:

```bash
export TS_BASE=http://localhost:8000
```

以下のサンプルでは `$TS_BASE` を使います。

### 共通仕様

| 項目 | 仕様 |
|---|---|
| Content-Type | `application/json`（POST/PATCH 時） |
| 日時の入力 | ISO8601 + TZ オフセット必須（例 `2026-05-15T23:59:59+09:00`） |
| 日時の出力 | UTC（末尾 `Z`） |
| 認証 | `POST /auth/google/local` 完了後、Cookie/Token 等は不要（サーバー内で永続化） |
| エラー形式 | `{"detail": {"error": "<code>", "message": "<msg>"}}` |

### よく踏むハマり

- **`<...>` プレースホルダはそのまま打たない**：README の `$LIST_ID` 等は **値を埋めて** から実行
- **`+` は URL エンコード必須**（`%2B`）：クエリ文字列で `+09:00` と書くとサーバー側で空白に解釈される
- **TZ なし日時はバリデーションエラー**（`/calendar/events` の `start` `end`）

---

## 1. 認証 `/auth/*`

### 1.1 ローカル OAuth ログイン（ブラウザが開く）

```bash
curl -X POST $TS_BASE/auth/google/local
```

レスポンス例:
```json
{
  "user_id": "62a82c271b69439a8620f50913da3eac",
  "google_email": "takatoshi.aoki0116@gmail.com",
  "scopes": ["https://www.googleapis.com/auth/calendar"],
  "token_expires_at": "2026-05-08T10:00:00Z"
}
```

注意：このエンドポイントは**ローカル開発専用**。叩くとサーバープロセスがブラウザを開くので、SSH 越し等では使えない。

### 1.2 認証状態確認

```bash
curl $TS_BASE/auth/me
```

未ログイン時:
```json
{"detail":{"error":"not_authenticated","message":"No user. Run /auth/google/local."}}
```

### 1.3 ログアウト（DB のトークン削除）

```bash
curl -X DELETE $TS_BASE/auth/google
```

`204 No Content`（再ログインしないと API が使えなくなる）。

---

## 2. タスクリスト `/lists`

### 2.1 一覧

```bash
curl $TS_BASE/lists
```

レスポンス例（各リストに件数が付く）:
```json
[
  {
    "id": "5979b6858d1a4abe97d50eabb6bb5bfa",
    "title": "勉強",
    "position": "000010",
    "created_at": "2026-05-08T08:56:17.986997Z",
    "updated_at": "2026-05-08T08:56:17.987002Z",
    "task_count": 3,
    "completed_count": 1
  }
]
```

### 2.2 作成

```bash
curl -X POST $TS_BASE/lists \
  -H "Content-Type: application/json" \
  -d '{"title":"勉強"}'
```

`201 Created`。`title` のみ必須、`position` は末尾自動。

### 2.3 単件取得

```bash
LIST_ID=5979b6858d1a4abe97d50eabb6bb5bfa
curl $TS_BASE/lists/$LIST_ID
```

### 2.4 更新

```bash
curl -X PATCH $TS_BASE/lists/$LIST_ID \
  -H "Content-Type: application/json" \
  -d '{"title":"新しいタイトル"}'
```

`title` / `position` のいずれか or 両方を指定（部分更新）。

### 2.5 削除（配下のタスクもカスケード削除）

```bash
curl -X DELETE $TS_BASE/lists/$LIST_ID
```

`204 No Content`。

---

## 3. タスク `/lists/{list_id}/tasks` と `/tasks/{id}`

### 3.1 リスト内タスク一覧

未完了のみ（既定）:
```bash
curl $TS_BASE/lists/$LIST_ID/tasks
```

完了済みも含める:
```bash
curl "$TS_BASE/lists/$LIST_ID/tasks?include_completed=true"
```

`position` 順で返る。

### 3.2 タスク作成

最小（タイトルのみ。`duration_min=60`, `weight=0.5`, `priority=3` が既定値で入る）:
```bash
curl -X POST $TS_BASE/lists/$LIST_ID/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"レポート"}'
```

フル指定:
```bash
curl -X POST $TS_BASE/lists/$LIST_ID/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title":"レポート執筆",
    "notes":"参考資料は Notion 参照",
    "duration_min":90,
    "weight":0.8,
    "priority":4,
    "due":"2026-05-15T17:00:00+09:00",
    "deadline":"2026-05-15T23:59:59+09:00"
  }'
```

| フィールド | 型 | 既定 | 制約 | 用途 |
|---|---|---|---|---|
| `title` | str | （必須） | 1〜512 文字 | |
| `notes` | str/null | null | | メモ |
| `parent_id` | str/null | null | | サブタスク用（同リストの親 ID） |
| `due` | datetime/null | null | TZ 必須 | 表示用期日（柔らかい） |
| `duration_min` | int | 60 | > 0 | 所要時間 |
| `weight` | float | 0.5 | 0〜1 | タスクの重さ |
| `priority` | int | 3 | 1〜5 | 優先度 |
| `deadline` | datetime/null | null | TZ 必須 | MIP のハード制約用 |

### 3.3 タスク詳細（サブタスク含む）

```bash
TASK_ID=056f50eee7a940f68f7219c7d681653b
curl $TS_BASE/tasks/$TASK_ID
```

レスポンス末尾に `"subtasks": [...]`（同レベルで返る）。

### 3.4 部分更新

```bash
curl -X PATCH $TS_BASE/tasks/$TASK_ID \
  -H "Content-Type: application/json" \
  -d '{"weight":0.6,"priority":5}'
```

未指定フィールドは変更されない。

### 3.5 完了 / 取消

```bash
curl -X POST $TS_BASE/tasks/$TASK_ID/complete
curl -X POST $TS_BASE/tasks/$TASK_ID/uncomplete
```

`completed_at` は完了時刻が UTC で自動記録される。

### 3.6 並び替え / リスト移動

別のリストに移す:
```bash
curl -X POST $TS_BASE/tasks/$TASK_ID/move \
  -H "Content-Type: application/json" \
  -d '{"list_id":"<another_list_id>"}'
```

同じリスト内で並び替え（position の値を直接指定）:
```bash
curl -X POST $TS_BASE/tasks/$TASK_ID/move \
  -H "Content-Type: application/json" \
  -d '{"position":"000005"}'
```

### 3.7 削除

```bash
curl -X DELETE $TS_BASE/tasks/$TASK_ID
```

サブタスクはカスケード削除。

### 3.8 サブタスクの作り方

```bash
PARENT_ID=$TASK_ID
curl -X POST $TS_BASE/lists/$LIST_ID/tasks \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"参考文献まとめ\",\"parent_id\":\"$PARENT_ID\"}"
```

- 親と同じリストでないとエラー
- 孫（サブのサブ）は不可

---

## 4. Google Calendar `/calendar/calendars` `/calendar/events`

### 4.0 利用可能なカレンダー一覧

```bash
curl $TS_BASE/calendar/calendars | python -m json.tool
```

レスポンス例:
```json
[
  {
    "id": "takatoshi.aoki0116@gmail.com",
    "summary": "takatoshi.aoki0116@gmail.com",
    "primary": true,
    "access_role": "owner",
    "selected": true,
    "time_zone": "Asia/Tokyo",
    "source": "google"
  },
  {
    "id": "u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com",
    "summary": "https://utas.adm.u-tokyo.ac.jp/.../...ics",
    "primary": false,
    "access_role": "reader",
    "selected": true,
    "time_zone": "UTC",
    "source": "google"
  }
]
```

| フィールド | 意味 |
|---|---|
| `primary` | プライマリ（自分のメイン）かどうか |
| `access_role` | `owner` / `writer` / `reader` / `freeBusyReader` |
| `selected` | Google Calendar UI で表示対象になっているか |
| `summary` | カレンダー名（購読カレンダーは ICS の URL が入ることが多い） |

`/calendar/events?calendar_id=<id>` に渡せば、そのカレンダーの予定が取れます。

### 4.1 期間指定で予定取得（プライマリのみ）

```bash
curl "$TS_BASE/calendar/events?start=2026-05-08T00:00:00%2B09:00&end=2026-05-15T23:59:59%2B09:00"
```

`+` は **必ず `%2B` にエンコード**。生で `+` と書くと `start=2026-05-08T00:00:00 09:00` と解釈されて 422 になる。

### 4.2 単一の別カレンダー指定

```bash
curl "$TS_BASE/calendar/events?start=...&end=...&calendar_id=u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com"
```

### 4.2.1 複数カレンダー横断取得（推奨）

「祝日以外の全カレンダー」のような取得は `calendar_ids`（カンマ区切り）で:

```bash
curl "$TS_BASE/calendar/events\
?start=2026-05-08T00:00:00%2B09:00\
&end=2026-05-15T23:59:59%2B09:00\
&calendar_ids=takatoshi.aoki0116@gmail.com,dbf55cb5d907a1ec27f6fddaf7c16e1508967319f5247b657104c49445fe2d41@group.calendar.google.com,u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com"
```

各イベントには **`calendar_id` フィールドが付く**ので、UI で由来を表示できます:

```json
{"id":"...","calendar_id":"u06kh7esai92u...","summary":"物性化学","start":"2026-05-08T05:55:00Z",...}
```

複数カレンダーから取得した場合は **start 時刻順でマージ済み**で返ってきます。

[project_plan.md §1.0](../project_plan.md) の方針通り、最適化エンジンに渡す「忙しい時間」は **祝日系を除く全カレンダー横断**を既定とします。
Phase 2 で `user_settings` に `busy_calendar_ids` を持たせて自動化予定。

### 4.3 レスポンスの正規化フィールド

```json
{
  "id": "civfl387863f9mm3b85jasp5vg",
  "summary": "インターン勤務",
  "description": null,
  "start": "2026-05-08T04:00:00Z",
  "end": "2026-05-08T05:00:00Z",
  "all_day": false,
  "location": null,
  "status": "confirmed",
  "source": "google"
}
```

| フィールド | 備考 |
|---|---|
| `start` / `end` | 常に UTC（`Z` 付き） |
| `all_day` | 終日イベントは `true`、`end` は当日終わりを表す |
| `status` | `confirmed` / `tentative` / `cancelled`（cancelled は取得対象から除外済） |
| `source` | 将来他プロバイダ追加時の判別子。当面 `"google"` 固定 |

### 4.4 エラーの種類

| HTTP | error コード | 状況 |
|---|---|---|
| 400 | `validation_error` | `start` >= `end` / TZ 欠落 |
| 401 | `not_authenticated` | OAuth 未完了 |
| 401 | `reauth_required` | refresh_token 失効 → `/auth/google/local` 再実行 |
| 502 | `calendar_api_error` | Google 側のエラー |

---

## 5. ヘルスチェック

```bash
curl $TS_BASE/health
# {"status":"ok"}
```

---

## 6. 検証用ワンライナー集

### 全リスト + 件数を 1 行で

```bash
curl -s $TS_BASE/lists | python -m json.tool
```

### 一番上のリストの ID を抽出

```bash
LIST_ID=$(curl -s $TS_BASE/lists | python -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
echo $LIST_ID
```

### タスク作成 → ID をすぐ拾う

```bash
TASK_ID=$(curl -s -X POST $TS_BASE/lists/$LIST_ID/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"テスト"}' \
  | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo $TASK_ID
```

### 今週分のカレンダー予定（JST 月曜〜日曜）

```bash
START=$(date -v Mon -u +"%Y-%m-%dT00:00:00")  # macOS
END=$(date -v Sun -v+7d -u +"%Y-%m-%dT00:00:00")
curl -s "$TS_BASE/calendar/events?start=${START}Z&end=${END}Z" | python -m json.tool
```

### 全タスク一覧（全リスト横断）

API としては未提供。リスト一覧 → 各リストの tasks を順に叩く必要あり:
```bash
for id in $(curl -s $TS_BASE/lists | python -c 'import json,sys;[print(r["id"]) for r in json.load(sys.stdin)]'); do
  echo "=== $id ==="
  curl -s "$TS_BASE/lists/$id/tasks?include_completed=true" | python -m json.tool
done
```

---

## 7. OpenAPI / Swagger UI

GUI で叩きたい場合:
- http://localhost:8000/docs ← Swagger UI（試行ボタン付き）
- http://localhost:8000/redoc ← ReDoc（読みやすい）
- http://localhost:8000/openapi.json ← 生スキーマ
