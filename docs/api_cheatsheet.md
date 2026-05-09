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
| `duration_min` | int | 60 | > 0 | 所要時間。「重さ」も兼ねる（長い = 重い） |
| `priority` | int | 3 | 1〜5 | 優先度 |
| `deadline` | datetime/null | null | TZ 必須 | MIP のハード制約用 |
| `location` | str/null | null | `home`/`university`/`office`/`anywhere` | NULL = anywhere 扱い、配置先 slot の location と合わない場合は配置不可 |

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

## 4.5 設定 `/settings`（Phase 2）

### 4.5.1 現在の設定取得

```bash
curl $TS_BASE/settings | python -m json.tool
```

初回呼び出し時に既定値で行を作って返します。

### 4.5.2 設定の部分更新

```bash
# 祝日カレンダーを除外対象に
curl -X PUT $TS_BASE/settings \
  -H "Content-Type: application/json" \
  -d '{"ignore_calendar_ids":["ja.japanese#holiday@group.v.calendar.google.com"]}'

# 作業可能時間を変更
curl -X PUT $TS_BASE/settings \
  -H "Content-Type: application/json" \
  -d '{"work_hours":{"monday":{"slots":[{"start":"10:00","end":"23:00"}]},"tuesday":{"slots":[{"start":"09:00","end":"22:00"}]},"wednesday":{"slots":[{"start":"09:00","end":"22:00"}]},"thursday":{"slots":[{"start":"09:00","end":"22:00"}]},"friday":{"slots":[{"start":"09:00","end":"22:00"}]},"saturday":{"slots":[{"start":"10:00","end":"22:00"}]},"sunday":{"slots":[{"start":"10:00","end":"22:00"}]},"timezone":"Asia/Tokyo"}}'

# 特定日を手動で日タイプ上書き
curl -X PUT $TS_BASE/settings \
  -H "Content-Type: application/json" \
  -d '{"day_type_overrides":{"2026-05-12":"free_day"}}'

# 既定値にリセット
curl -X POST $TS_BASE/settings/reset
```

### 4.5.3 設定項目（[docs/phase2_design.md §2.1](phase2_design.md) 参照）

| 項目 | 既定 | 用途 |
|---|---|---|
| `work_hours` | 平日 09-22, 土日 10-22 | 曜日ごとの作業可能時間帯 |
| `location_buffers` | 大学/インターン/歯科のルール | 場所キーワード → 前後何分を「埋まっている」扱い |
| `day_type_rules` | intern/uni_heavy/uni_light/free_day | 日タイプ判定の優先順ルール |
| `day_type_default` | normal (energy 0.7) | どのルールにもマッチしない日 |
| `day_type_overrides` | `{}` | `{"2026-05-12":"free_day"}` 形式の手動上書き |
| `busy_calendar_ids` | `[]` | 「忙しい時間」として読むカレンダー ID（空 = 全部対象） |
| `ignore_calendar_ids` | `[]` | 無視するカレンダー（祝日など） |
| `slot_min_duration_min` | 30 | これより短い空きはスロットにしない |
| `slot_max_duration_min` | 120 | これより長い空きは分割 |
| `ignore_all_day_events` | `true` | 終日イベントを忙しさ判定・日タイプ判定の両方から除外する |
| `calendar_location_rules` | UTAS→university, intern→office | カレンダーイベントを場所にタグ付け |
| `location_commutes.<loc>.to_min/from_min` | uni 30/30, office 20/20 | 通学/通勤時間（ウィンドウ境界） |
| `location_commutes.<loc>.linger_after_min` | uni=180, office=0 | 最後の予定後 N 分間「その場所にいる」扱い（放課後図書館滞在）。`commute_from` はウィンドウ末尾に置かれる |

## 4.6 空きスロット `/calendar/slots`（Phase 2）

### 4.6.1 期間指定でスロット生成

```bash
curl "$TS_BASE/calendar/slots?start=2026-05-11T00:00:00%2B09:00&end=2026-05-15T23:59:59%2B09:00" | python -m json.tool
```

各スロットの形式:

```json
{
  "id": "slot-2026-05-11T09:35:00Z-120",
  "start": "2026-05-11T09:35:00Z",
  "duration_min": 120,
  "energy_score": 0.3,
  "allowed_weight_max": 0.5,
  "day_type": "intern_day"
}
```

### 4.6.2 リクエスト単位で min/max を上書き

```bash
curl "$TS_BASE/calendar/slots?start=...&end=...&max_duration_min=60&min_duration_min=15"
```

### 4.6.3 既知の挙動

- **終日（all-day）イベントは既定で無視**（`ignore_all_day_events=true`）— 「白衣ゴーグル」のようなリマインダーは忙しさ判定にも日タイプ判定にも入りません。終日イベントを「終日忙しい」扱いに戻したい場合は `PUT /settings` で `{"ignore_all_day_events": false}`
- **`day_type` は 1 日単位** — 朝はインターン、夕方は free にしたい場合は今のところ不可。Phase 3 のソフト制約で時間帯重み付けを検討
- **重い予定の連続マージ** — バッファで重なれば 1 つの busy 区間として扱われ、間の隙間も塞がる仕様

## 4.7 最適化 `/optimize` `/optimizer/snapshots`（Phase 3）

### 4.7.1 最適化を実行

```bash
curl -X POST $TS_BASE/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "start": "2026-05-11T00:00:00+09:00",
    "end":   "2026-05-17T23:59:59+09:00"
  }'
```

レスポンス例:

```json
{
  "status": "optimal",
  "objective_value": 24.579,
  "snapshot_id": "4c6b18a6...",
  "assignments": [
    {
      "task_id": "...",
      "task_title": "物性化学レポート",
      "fragments": [{"slot_id":"slot-2026-05-12T08:00:00Z-120","start":"2026-05-12T08:00:00Z","duration_min":120}],
      "total_assigned_min": 120
    }
  ],
  "unassigned": [],
  "solve_time_sec": 0.107,
  "notes": []
}
```

### 4.7.2 リスト・タスク絞り込み

```bash
# 特定リストのみ
curl -X POST $TS_BASE/optimize -H "Content-Type: application/json" \
  -d '{"start":"...","end":"...","list_ids":["<list_id>"]}'

# 特定タスクのみ
curl -X POST $TS_BASE/optimize -H "Content-Type: application/json" \
  -d '{"start":"...","end":"...","task_ids":["<task_id>","<task_id>"]}'
```

### 4.7.3 設定の上書き（部分）

```bash
# energy_match の重みを上げて朝/夜のマッチをより強く効かせる
curl -X POST $TS_BASE/optimize -H "Content-Type: application/json" \
  -d '{
    "start":"...","end":"...",
    "config_overrides":{
      "weights":{"energy_match":0.2,"unassigned_penalty":10.0},
      "min_fragment_min":45,
      "max_fragments_per_task":3
    }
  }'

# 特定の制約を無効化
curl -X POST $TS_BASE/optimize -H "Content-Type: application/json" \
  -d '{"start":"...","end":"...",
       "config_overrides":{"enabled_constraints":["all_or_nothing","slot_capacity","deadline","min_fragment_size"]}}'
```

### 4.7.4 スナップショット

```bash
# 一覧
curl $TS_BASE/optimizer/snapshots | python -m json.tool

# 単件詳細（入出力すべて）
curl $TS_BASE/optimizer/snapshots/<id> | python -m json.tool

# 別 config で再実行（新しい snapshot が作られる）
curl -X POST $TS_BASE/optimizer/snapshots/<id>/replay \
  -H "Content-Type: application/json" \
  -d '{"config_overrides":{"weights":{"energy_match":0.5}},"note":"energy 強めで実験"}'

# 削除
curl -X DELETE $TS_BASE/optimizer/snapshots/<id>

# 結果をタスクに反映（scheduled_start / scheduled_end を書き込む）
curl -X POST $TS_BASE/optimizer/snapshots/<id>/apply
# → {"updated_task_count": 6, "snapshot_id": "..."}
```

apply 後は各タスクに `scheduled_start` / `scheduled_end` が入ります。
完了は `POST /tasks/{id}/complete` で。`scheduled_end` までに complete されなかったタスクは
未完了扱いのまま、次の `/optimize` 呼び出しで再考慮されます。

### 4.7.5 設定項目（既定値）

| キー | 既定 | 意味 |
|---|---|---|
| `weights.priority` | 1.0 | 高優先度タスクの加点 |
| `weights.urgency` | 1.0 | 締切が近いほど加点（1/(days+1)） |
| `weights.energy_match` | 0.05 | weight × energy のマッチ加点（分単位重み付け） |
| `weights.unassigned_penalty` | 5.0 | 未配置の減点（高優先度ほど痛い） |
| `min_fragment_min` | 30 | 1 断片の最小サイズ（これ未満は許可しない） |
| `max_fragments_per_task` | 5 | 1 タスクの分割上限 |
| `time_limit_sec` | 30 | ソルバーの時間制限 |
| `enabled_constraints` | 6 個全部 | 動的に切り替え可能 |
| `enabled_objectives` | 4 個全部 | 同上 |

### 4.7.6 エラーコード

| HTTP | error コード | 状況 |
|---|---|---|
| 400 | `validation_error` | 期間不正 / TZ 欠落 |
| 401 | `not_authenticated` / `reauth_required` | スロット生成段階で認証必要 |
| 422 | `no_tasks` | 対象タスクが空（フィルタで全部除外された） |
| 422 | `no_slots` | 期間中にスロットが生成されない |
| 502 | `calendar_api_error` | Google API エラー |

## 4.8 カレンダー書き込み `/optimizer/snapshots/{id}/write`（Phase 5）

最適化結果を実際の Google Calendar に予定として書き込む。冪等性のため、
書き込んだ event には `extendedProperties.private.task_scheduler="1"` のマーカーが
付き、再書き込み時は **既存マーカー付き event を全削除 → 新規作成** で同期される。

### 4.8.1 書き込み（dry-run）

書く前に「何が書かれるか」を確認:

```bash
SNAP=4c6b18a6...
curl -X POST $TS_BASE/optimizer/snapshots/$SNAP/write \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true}' | python -m json.tool
```

レスポンス:
```json
{
  "snapshot_id": "4c6b18a6...",
  "dry_run": true,
  "target_calendar_id": "primary",
  "deleted_event_count": 6,
  "created_events": [
    {
      "task_id": "...",
      "task_title": "物性化学レポート",
      "event_id": null,
      "start": "2026-05-12T03:10:00Z",
      "end":   "2026-05-12T05:10:00Z",
      "fragment_index": 0
    }
  ]
}
```

dry_run のときは `event_id` は `null`、`deleted_event_count` は「もし書いたら消されるはずの数」。

### 4.8.2 実際に書き込み

```bash
curl -X POST $TS_BASE/optimizer/snapshots/$SNAP/write \
  -H "Content-Type: application/json" \
  -d '{"dry_run":false}'
```

書き込み完了後:
- 各 event は `[task-scheduler] <タスク名>` 接頭辞で表示される
- 通知（reminders）は無効（一斉に大量に書いても push が鳴らない）
- 各タスクの `tasks.scheduled_event_id` に最初の fragment の event id が入る

### 4.8.3 書き込み先カレンダーの変更

省略時は `primary`（プライマリ）に書く。別カレンダーに書きたい場合:

```bash
curl -X POST $TS_BASE/optimizer/snapshots/$SNAP/write \
  -H "Content-Type: application/json" \
  -d '{"dry_run":false,"target_calendar_id":"<calendar_id>"}'
```

### 4.8.4 取消（書いたものを全削除）

このアプリが書いた全 event（マーカー付き）を消す:

```bash
curl -X DELETE "$TS_BASE/optimizer/snapshots/$SNAP/write"
# → {"deleted_event_count": 6, "target_calendar_id": "primary"}
```

特定 snapshot 由来の event だけ消したい場合:

```bash
curl -X DELETE "$TS_BASE/optimizer/snapshots/$SNAP/write?only_this_snapshot=true"
```

書き込み先を切り替えていた場合は同じ `target_calendar_id` をクエリで渡す:

```bash
curl -X DELETE "$TS_BASE/optimizer/snapshots/$SNAP/write?target_calendar_id=<id>"
```

### 4.8.5 再書き込みの挙動

| 操作 | カレンダーの最終状態 |
|---|---|
| 同じ snapshot を 2 回 `write` | 重複しない（既存削除→再作成） |
| 別 snapshot を `write` | 前回分が消えて新規分のみが残る |
| `DELETE /write` | アプリ書き込み分が全て消える（手動予定はそのまま） |

「最新の最適化結果が常にカレンダーの状態」になる単純戦略。

### 4.8.6 エラーコード

| HTTP | error コード | 状況 |
|---|---|---|
| 401 | `not_authenticated` / `reauth_required` | OAuth 期限切れ |
| 404 | `not_found` | snapshot が存在しない |
| 422 | `nothing_to_write` | snapshot に assignments が無い（infeasible 等） |
| 502 | `calendar_api_error` | Google Calendar API エラー |

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
