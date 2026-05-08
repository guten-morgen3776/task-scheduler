# Phase 1：Google Calendar 連携 + 自作タスク管理 詳細設計

> 対象期間：3〜4 日
> ゴール：CLI / curl で「OAuth ログイン → タスク CRUD → カレンダー予定取得」までが一通り動く。
> 参照：`project_plan.md` §1.1（自作タスク管理に方針変更）、§2.2.1（タスクスキーマ）、§4 Phase 1、§8.1（将来移行指針）

---

## 0. このフェーズの位置づけ

**やること：**
- Google OAuth2 認可フロー（ローカル `InstalledAppFlow`）
- リフレッシュトークンの暗号化保存
- Google Calendar API：指定期間の予定取得
- 自作タスク管理（タスク + タスクリストの CRUD）

**やらないこと：**
- スロット生成・最適化エンジン → Phase 2 / 3
- カレンダーへの書き込み → Phase 5
- フロント UI → Phase 6（このフェーズでは curl / pytest で検証）
- マルチユーザー対応（§8.3 通り、`user_id` カラムは持つが値は固定）

---

## 1. 成果物チェックリスト

- [ ] `python -m app.cli auth login` 相当の操作で OAuth フローが完了し、トークンが DB に暗号化保存される
- [ ] `GET /auth/me` で連携中の Google アカウントが返る
- [ ] `POST /lists` `GET /lists` `PATCH /lists/{id}` `DELETE /lists/{id}` が動く
- [ ] `POST /lists/{list_id}/tasks` `GET /lists/{list_id}/tasks` `GET /tasks/{id}` `PATCH /tasks/{id}` `DELETE /tasks/{id}` が動く
- [ ] `POST /tasks/{id}/complete` `POST /tasks/{id}/uncomplete` が動く
- [ ] `GET /calendar/events?start=...&end=...` で実カレンダーから予定が取得できる
- [ ] Alembic マイグレーションがコミットされ、`alembic downgrade -1` → `upgrade head` で往復できる
- [ ] 自動テスト（pytest）：CRUD と認証ハンドラの基本ケースが通る
- [ ] `task-scheduler.http` のような手動検証ファイル（または README のサンプル curl）で全エンドポイントを叩ける

---

## 2. データモデル設計

### 2.1 テーブル一覧（Phase 1 で作るもの）

| テーブル | 用途 |
|---|---|
| `users` | シングルユーザー想定だが §8.1 に従い行は持つ |
| `oauth_credentials` | Google OAuth リフレッシュトークン保存（暗号化） |
| `task_lists` | タスクリスト（Google ToDo の「リスト」相当） |
| `tasks` | タスク本体（自作。§2.2.1 のスキーマ） |

スロット / 最適化結果 / Snapshot 関連のテーブルは Phase 2〜5 で順次追加する。

### 2.2 `users`

| カラム | 型 | 制約 | 備考 |
|---|---|---|---|
| `id` | TEXT (UUID) | PK | |
| `google_email` | TEXT | UNIQUE | OAuth 完了時に登録 |
| `display_name` | TEXT | NULL 可 | |
| `created_at` | DATETIME | NOT NULL | UTC |
| `updated_at` | DATETIME | NOT NULL | UTC |

**設計判断：** §8.1 通り、シングルユーザーでも `users` テーブルは作る。MVP では実質 1 行のみ。
すべての他テーブルに `user_id` FK を最初から持たせ、将来のマルチユーザー化でカラム追加マイグレーションを発生させない。

### 2.3 `oauth_credentials`

| カラム | 型 | 制約 | 備考 |
|---|---|---|---|
| `id` | TEXT (UUID) | PK | |
| `user_id` | TEXT | FK → users.id, UNIQUE | 1 ユーザー 1 認可 |
| `provider` | TEXT | NOT NULL | 当面は `"google"` 固定 |
| `refresh_token_encrypted` | TEXT | NOT NULL | Fernet で暗号化 |
| `access_token` | TEXT | NULL | キャッシュ用、有効期限切れたら再取得 |
| `token_expires_at` | DATETIME | NULL | UTC |
| `scopes` | TEXT | NOT NULL | スペース区切り |
| `created_at` | DATETIME | NOT NULL | |
| `updated_at` | DATETIME | NOT NULL | |

**暗号化：**
- `Fernet`（`cryptography` ライブラリ）を採用。AES-128 + HMAC でシンプル
- 鍵は `.env` の `TOKEN_ENCRYPTION_KEY`
- access_token は短命（1 時間）なので暗号化しない判断もありだが、揃えて暗号化しておく方が後で楽 → **両方暗号化する**（access_token も同じ仕組みで）

### 2.4 `task_lists`

| カラム | 型 | 制約 | 備考 |
|---|---|---|---|
| `id` | TEXT (UUID) | PK | |
| `user_id` | TEXT | FK → users.id | |
| `title` | TEXT | NOT NULL | |
| `position` | TEXT | NOT NULL | 並び順（後述 §2.6） |
| `created_at` | DATETIME | NOT NULL | |
| `updated_at` | DATETIME | NOT NULL | |

INDEX：`(user_id, position)`

### 2.5 `tasks`（`project_plan.md` §2.2.1 を実装）

| カラム | 型 | NULL | 既定値 | 備考 |
|---|---|---|---|---|
| `id` | TEXT (UUID) | NO | — | PK |
| `user_id` | TEXT | NO | — | FK → users.id |
| `list_id` | TEXT | NO | — | FK → task_lists.id |
| `title` | TEXT | NO | — | |
| `notes` | TEXT | YES | NULL | |
| `parent_id` | TEXT | YES | NULL | FK → tasks.id（自己参照、サブタスク） |
| `position` | TEXT | NO | — | 並び順 |
| `completed` | BOOLEAN | NO | `false` | |
| `completed_at` | DATETIME | YES | NULL | UTC |
| `due` | DATETIME | YES | NULL | 表示上の期日（Google ToDo 互換） |
| `duration_min` | INTEGER | NO | `60` | 所要時間 |
| `weight` | REAL | NO | `0.5` | 0〜1 |
| `priority` | INTEGER | NO | `3` | 1〜5 |
| `deadline` | DATETIME | YES | NULL | MIP のハード制約用 |
| `scheduled_event_id` | TEXT | YES | NULL | カレンダー反映後の Google Calendar イベント ID |
| `scheduled_start` | DATETIME | YES | NULL | UTC |
| `created_at` | DATETIME | NO | — | UTC |
| `updated_at` | DATETIME | NO | — | UTC |

INDEX：
- `(user_id, list_id, position)` ：リスト内一覧用
- `(user_id, completed, deadline)` ：未完了タスクの締切順検索用（Phase 3 で使う）

CHECK 制約：
- `weight BETWEEN 0 AND 1`
- `priority BETWEEN 1 AND 5`
- `duration_min > 0`

**`due` と `deadline` の使い分け：**
- `due`：Google ToDo 互換、UI 表示・並び順用の柔らかい期日
- `deadline`：最適化のハード制約として使う厳密な締切
- どちらも NULL 可（締切なしタスク）

### 2.6 `position` の運用

Google ToDo と同様の文字列 lexicographic 並び順を採用する。

- 採用方式：**fractional indexing**（`fractional-indexing` 系のアルゴリズム）
- 実装ライブラリ候補：自作（短い文字列で十分）or 簡易な midstring 生成
- 末尾追加は `last_position + "0"` のような擬似的な実装で MVP は十分
- 並び替え時は前後の position の中間値を生成

**MVP 簡易実装：** 当面は `len(items)` ベースの整数を 0 埋め文字列で（例：`"00010"`, `"00020"`）。挿入の余裕を持たせるため間隔 10 で振る。Phase 6 のドラッグ操作で詰まったら fractional indexing に移行。

---

## 3. ディレクトリ構成（Phase 1 完了時）

```
backend/app/
├── api/
│   ├── __init__.py
│   ├── deps.py              # DI（DB セッション、認証済みユーザー取得）
│   ├── auth.py              # /auth/*
│   ├── lists.py             # /lists/*
│   ├── tasks.py             # /lists/{id}/tasks, /tasks/{id}
│   └── calendar.py          # /calendar/events
├── core/
│   ├── config.py            # Phase 0 から拡張
│   ├── database.py          # Phase 0 から拡張
│   ├── crypto.py            # Phase 1 で追加：Fernet ラッパー
│   └── time.py              # UTC ↔ Asia/Tokyo 変換ヘルパ
├── models/
│   ├── __init__.py
│   ├── base.py              # DeclarativeBase + 共通 created_at/updated_at
│   ├── user.py
│   ├── oauth_credential.py
│   ├── task_list.py
│   └── task.py
├── schemas/
│   ├── __init__.py
│   ├── user.py
│   ├── auth.py
│   ├── task_list.py
│   ├── task.py
│   └── calendar.py
├── services/
│   ├── google/
│   │   ├── __init__.py
│   │   ├── oauth.py         # InstalledAppFlow ラッパー、トークン保存/復元
│   │   └── calendar.py      # Calendar API クライアント
│   └── tasks/
│       ├── __init__.py
│       ├── lists.py         # task_lists の CRUD ロジック
│       └── tasks.py         # tasks の CRUD ロジック
└── main.py                  # ルーター登録
```

---

## 4. 認証フロー設計

### 4.1 採用：`InstalledAppFlow`

§2.1 と §8.1 の方針に従い、**ローカル開発は `InstalledAppFlow`、将来は Web `Flow` に差し替え可能な構造**にする。

`services/google/oauth.py` に `GoogleOAuthService` クラスを置き、外側から見ると以下のメソッドを持つ：

```
GoogleOAuthService
├── start_local_flow() -> Credentials       # ブラウザを開いて認可、Credentials を返す
├── save_credentials(user_id, creds)        # DB に暗号化保存
├── load_credentials(user_id) -> Credentials  # DB から復号して返す（期限切れなら refresh）
└── get_calendar_client(user_id)            # 認証済み googleapiclient を返す
```

**将来移行（§8.2 Step B）の差し替え点：**
- `start_local_flow()` を `start_web_flow(redirect_uri)` に置き換える
- 他のメソッドは無修正

### 4.2 エンドポイント

Phase 1 ではローカルフローしかないため、API は最小限に。

| メソッド | パス | 動作 |
|---|---|---|
| `POST` | `/auth/google/local` | ローカルフロー起動。サーバープロセス内でブラウザが開き、認可完了で 200 を返す |
| `GET` | `/auth/me` | 現在連携中のユーザー情報（email, scopes, expires_at）を返す |
| `DELETE` | `/auth/google` | DB のトークン削除（ログアウト相当） |

`POST /auth/google/local` はローカル開発専用。本番では使わない（§8.2 Step B 以降は別エンドポイントが入る）想定。

### 4.3 トークン保管・更新

- 取得時：`oauth_credentials` に `INSERT ... ON CONFLICT(user_id) DO UPDATE`
- 利用時：`load_credentials` 内で `creds.expired` をチェック、必要に応じて `creds.refresh(Request())` し、新しい access_token を DB に書き戻す
- スレッドセーフ性：FastAPI の同期/非同期境界に注意。Google ライブラリは同期なので、`run_in_executor` で包む

### 4.4 シングルユーザー前提の簡略化

§8.3 の通り：
- `user_id` は `.env` の `DEFAULT_USER_ID` 等で固定 or「1 行目を取る」運用で十分
- セッション・JWT は実装しない
- 将来 Web フロー化する際は `deps.get_current_user()` を JWT 検証に差し替えるだけ、という構造にしておく（Phase 1 では「DEFAULT_USER_ID を返す」だけの関数）

---

## 5. Google Calendar 連携

### 5.1 取得対象

`GET /calendar/events?start=<ISO>&end=<ISO>&calendar_id=primary`

| パラメータ | 型 | 既定値 | 備考 |
|---|---|---|---|
| `start` | datetime (ISO8601) | 必須 | TZ 付き |
| `end` | datetime (ISO8601) | 必須 | TZ 付き |
| `calendar_id` | str | `"primary"` | カレンダー指定 |

### 5.2 レスポンス（中間表現）

Google API のレスポンスをそのまま返さず、本アプリの中間 DTO に正規化する（§8.1 の API 抽象方針）。

```
CalendarEvent {
  id: str               # Google の event id
  summary: str
  description: str | None
  start: datetime       # UTC
  end: datetime         # UTC
  all_day: bool
  location: str | None
  status: "confirmed" | "tentative" | "cancelled"
  source: "google"      # 将来他プロバイダ追加時の判別子
}
```

**正規化のメリット：**
- TZ を必ず UTC に揃える（§8.1）
- 終日イベント（`date` のみ）と時間指定イベント（`dateTime`）の差を吸収
- フロントエンドが Google API の生フォーマットを知らずに済む

### 5.3 サービス層 API

```
GoogleCalendarService
├── list_events(user_id, start, end, calendar_id) -> list[CalendarEvent]
└── (Phase 5 で追加) create_event / update_event / delete_event
```

### 5.4 エラーハンドリング

| ケース | 挙動 |
|---|---|
| トークン未保存 | 401 + `{"error": "not_authenticated"}` |
| `refresh_token` も期限切れ | 401 + `{"error": "reauth_required"}`（再ログインを促す） |
| API レート制限（429） | 指数バックオフ（最大 3 回） |
| その他 5xx | 1 回だけリトライ、ダメなら 502 |

---

## 6. タスク CRUD（自作タスク管理）

### 6.1 タスクリスト（`/lists`）

| メソッド | パス | リクエスト | レスポンス |
|---|---|---|---|
| `GET` | `/lists` | — | `TaskList[]`（position 順） |
| `POST` | `/lists` | `{title}` | `TaskList`（position は末尾） |
| `GET` | `/lists/{id}` | — | `TaskList` |
| `PATCH` | `/lists/{id}` | `{title?, position?}` | `TaskList` |
| `DELETE` | `/lists/{id}` | — | 204（配下のタスクも削除 or 別リストへ移動。MVP は **カスケード削除**） |

`TaskList` スキーマ：
```
{
  id: str,
  title: str,
  position: str,
  task_count: int,         # 一覧時のみ計算
  completed_count: int,    # 一覧時のみ計算
  created_at, updated_at
}
```

### 6.2 タスク（`/lists/{list_id}/tasks` と `/tasks/{id}`）

| メソッド | パス | 用途 |
|---|---|---|
| `GET` | `/lists/{list_id}/tasks?include_completed=false` | 一覧 |
| `POST` | `/lists/{list_id}/tasks` | 作成 |
| `GET` | `/tasks/{id}` | 単件取得 |
| `PATCH` | `/tasks/{id}` | 更新（部分） |
| `DELETE` | `/tasks/{id}` | 削除 |
| `POST` | `/tasks/{id}/complete` | 完了化（`completed=true, completed_at=now`） |
| `POST` | `/tasks/{id}/uncomplete` | 完了取消 |
| `POST` | `/tasks/{id}/move` | リスト変更 / 並び替え（`{list_id?, position?}`） |

### 6.3 リクエストスキーマ（Pydantic）

`TaskCreate`：
```
{
  title: str (required, 1..512),
  notes: str | None,
  parent_id: str | None,
  due: datetime | None,
  duration_min: int = 60,         # > 0
  weight: float = 0.5,            # 0..1
  priority: int = 3,              # 1..5
  deadline: datetime | None
}
```

`TaskUpdate`：すべてオプショナル化したもの。`PATCH` では指定されたフィールドのみ更新。

**バリデーション設計判断：**
- 既定値はサーバー側で付与（DB の DEFAULT に頼らない）。これにより、API レスポンスで「ユーザー未指定でも値が返る」ことを保証
- `duration_min` の上限は当面設けない（極端値は最適化エンジン側で吸収）

### 6.4 レスポンススキーマ

`Task`：
```
{
  id, list_id, title, notes, parent_id, position,
  completed, completed_at,
  due, deadline,
  duration_min, weight, priority,
  scheduled_event_id, scheduled_start,
  subtasks: Task[] | None,    # GET /tasks/{id} のみ。一覧では含めない
  created_at, updated_at
}
```

### 6.5 サブタスク

- 1 階層まで（孫タスクなし）
- 親が削除されたら子も削除（カスケード）
- 親完了 / 子完了は連動させない（Google ToDo 同様の挙動）

---

## 7. 横断的な設計事項

### 7.1 タイムゾーン取り扱い（§8.1 準拠）

- **DB には UTC で保存**
- API のリクエスト・レスポンスは ISO8601 + TZ オフセット必須
- `app/core/time.py` に `utc_now()` `to_app_tz()` `from_iso()` ヘルパを置き、コード内で素の `datetime.now()` を禁止する（ruff ルールで強制可能なら強制）

### 7.2 ID 生成

- すべて UUID v4（`uuid.uuid4().hex`）
- Google Calendar の event id は外部システム ID なので `scheduled_event_id` 列にそのまま入れる

### 7.3 監査列

`models/base.py` に Mixin で `created_at` / `updated_at` を持たせ、全テーブルで使い回し。`updated_at` は SQLAlchemy の `onupdate` で自動更新。

### 7.4 削除方針

Phase 1 では物理削除（hard delete）で進める。
履歴を残す要件が出たら soft delete（`deleted_at` カラム）に切り替えるが、今は不要（YAGNI）。

### 7.5 トランザクション境界

CRUD は 1 リクエスト 1 トランザクション。`api/deps.py` の `get_db()` で `async with session.begin()` のスコープを作り、ハンドラ終了でコミット / 例外でロールバック。

### 7.6 エラーレスポンス

統一フォーマット：
```
{
  "error": "<machine_readable_code>",
  "message": "<human readable>",
  "details": { ... }
}
```

| HTTP | error コード例 |
|---|---|
| 400 | `validation_error` |
| 401 | `not_authenticated` / `reauth_required` |
| 404 | `not_found` |
| 409 | `conflict`（並び替え競合など） |
| 500 | `internal_error` |

### 7.7 ロギング

`logging.getLogger("app")` をベースに、外部 API 呼び出し（Google）は別ロガー `app.google` に分離。Phase 1 ではコンソール出力のみで十分。

---

## 8. テスト戦略（Phase 1）

### 8.1 ユニットテスト

| 対象 | 確認内容 |
|---|---|
| `core.crypto` | 暗号化・復号で元に戻る、鍵が違うと復号失敗 |
| `core.time` | UTC ↔ Asia/Tokyo 変換が逆転で一致 |
| `services.tasks.tasks` | CRUD ロジック（DB は in-memory SQLite） |
| `services.google.calendar` | Google API クライアントをモックし、正規化が正しい |

### 8.2 統合テスト（FastAPI TestClient）

- タスクリスト + タスクの CRUD を一通り叩く E2E（in-memory SQLite）
- 認証関連は `deps.get_current_user` をオーバーライドしてテスト用ユーザーを返す

### 8.3 手動検証

`docs/phase1_manual_check.http`（VS Code REST Client 互換）を作り、全エンドポイントのサンプルを置く。または README に curl 例を書く。

---

## 9. マイグレーション計画

Alembic リビジョン分割（Phase 1 内で 2〜3 個に分けて履歴を見やすく）：

1. `001_create_users_and_oauth.py` — `users`, `oauth_credentials`
2. `002_create_task_lists.py` — `task_lists`
3. `003_create_tasks.py` — `tasks`（CHECK 制約・INDEX 含む）

**運用ルール：**
- マイグレーションは必ず `downgrade` も書く
- 各リビジョン適用後 `alembic downgrade -1 && alembic upgrade head` で往復確認

---

## 10. 実装順（おすすめ）

1. `models/base.py` + 4 テーブルのモデル定義
2. Alembic マイグレーション 001〜003 作成 + 往復確認
3. `core/crypto.py`（Fernet ラッパー） + ユニットテスト
4. `services/google/oauth.py`（ローカルフロー）+ `auth.py` ルーター
5. `services/google/calendar.py` + `calendar.py` ルーター
6. `services/tasks/lists.py` + `lists.py` ルーター
7. `services/tasks/tasks.py` + `tasks.py` ルーター
8. 統合テスト + 手動検証ファイル整備
9. README に Phase 1 動作手順追記

---

## 11. Phase 1 完了の動作確認シナリオ

```bash
# 1. サーバー起動
cd backend
uv run uvicorn app.main:app --reload

# 2. OAuth ログイン（ブラウザが開く）
curl -X POST http://localhost:8000/auth/google/local

# 3. 認証確認
curl http://localhost:8000/auth/me
# → {"google_email":"...", "scopes":[...], "expires_at":"..."}

# 4. リスト作成
curl -X POST http://localhost:8000/lists -H "Content-Type: application/json" \
  -d '{"title":"勉強"}'
# → {"id":"<list_id>", ...}

# 5. タスク作成
curl -X POST http://localhost:8000/lists/<list_id>/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"レポート執筆","duration_min":90,"weight":0.8,"priority":4,"deadline":"2026-05-15T23:59:59+09:00"}'

# 6. タスク一覧
curl http://localhost:8000/lists/<list_id>/tasks

# 7. カレンダー予定取得
curl "http://localhost:8000/calendar/events?start=2026-05-08T00:00:00%2B09:00&end=2026-05-15T23:59:59%2B09:00"

# 8. タスク完了
curl -X POST http://localhost:8000/tasks/<task_id>/complete
```

すべて期待通りに動けば Phase 1 完了 → Phase 2（スロット生成エンジン）へ。

---

## 12. このフェーズで残す未解決事項（Phase 2 以降への申し送り）

- **`scheduled_event_id` / `scheduled_start` の更新ロジック**：Phase 5（カレンダー書き込み）で実装。Phase 1 では NULL のまま
- **`extendedProperties` による冪等性**：Phase 5 で実装。Phase 1 のイベント取得時は無視
- **Google Calendar の watch / push 通知**：MVP では使わない（ポーリングで十分）
- **設定テーブル**：`user_settings`（最適化重み、作業可能時間帯、location_buffer）は Phase 2 でスロット生成に必要になった時点で追加
- **シナリオ Snapshot テーブル**：Phase 3 で追加
