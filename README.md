# task-scheduler

Google Calendar の空き時間に MIP（整数計画法）で自動配置する個人用タスク管理アプリ。

設計ドキュメント:
- [project_plan.md](project_plan.md) — 全体計画・技術選定
- [task_scheduler_design.md](task_scheduler_design.md) — 設計概要
- [docs/phase0_design.md](docs/phase0_design.md) — Phase 0 詳細
- [docs/phase1_design.md](docs/phase1_design.md) — Phase 1 詳細

---

## セットアップ（Phase 0）

### 必要なもの

- Python 3.11+（推奨：3.13）
- Node.js 20+
- [uv](https://docs.astral.sh/uv/)（`brew install uv` または `curl -LsSf https://astral.sh/uv/install.sh | sh`）
- pnpm（`npm i -g pnpm`）

### 1. ユーザー側で行うこと

#### Google Cloud Console

1. https://console.cloud.google.com/ で新規プロジェクトを作成（例：`task-scheduler-personal`）
2. 「API とサービス」→「ライブラリ」で **Google Calendar API のみ** を有効化
3. 「OAuth 同意画面」
   - ユーザータイプ：**外部**
   - スコープに `https://www.googleapis.com/auth/calendar` を追加
   - テストユーザーに自分の Gmail アドレスを追加
4. 「認証情報」→「OAuth 2.0 クライアント ID を作成」
   - 種類：**デスクトップアプリ**
   - JSON をダウンロードして `backend/secrets/credentials.json` に配置

#### `.env` の準備

```bash
cd backend
cp .env.example .env
```

`TOKEN_ENCRYPTION_KEY` 用に Fernet 鍵を生成して `.env` に貼る:

```bash
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

出力された鍵を `.env` の `TOKEN_ENCRYPTION_KEY=` の右側に貼り付けてください（Phase 1 の OAuth トークン暗号化に必須）。

### 2. バックエンド起動

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 47823
```

別ターミナルで動作確認:

```bash
curl http://localhost:47823/health
# → {"status":"ok"}
```

### 3. フロントエンド起動

```bash
cd frontend
pnpm install
pnpm dev
```

ブラウザで http://localhost:47824 にアクセスして Vite の初期画面が表示されれば OK。

---

## Phase 1 動作確認

Phase 1 の機能（OAuth + タスク CRUD + Calendar 取得）は curl で検証できます。

```bash
# 1. サーバー起動
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 47823
```

別ターミナルで:

```bash
# 2. OAuth ログイン（ブラウザが開いて Google 認可ページに飛ぶ）
curl -X POST http://localhost:47823/auth/google/local

# 3. ログイン状態確認
curl http://localhost:47823/auth/me
# → {"user_id":"...","google_email":"...","scopes":[...],"token_expires_at":"..."}

# 4. タスクリスト作成
LIST_ID=$(curl -s -X POST http://localhost:47823/lists \
  -H "Content-Type: application/json" \
  -d '{"title":"勉強"}' | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "list: $LIST_ID"

# 5. タスク作成
TASK_ID=$(curl -s -X POST "http://localhost:47823/lists/$LIST_ID/tasks" \
  -H "Content-Type: application/json" \
  -d '{"title":"レポート執筆","duration_min":90,"weight":0.8,"priority":4,"deadline":"2026-05-15T23:59:59+09:00"}' \
  | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "task: $TASK_ID"

# 6. タスク一覧
curl "http://localhost:47823/lists/$LIST_ID/tasks"

# 7. カレンダー予定取得（URL エンコードに注意）
curl "http://localhost:47823/calendar/events?start=2026-05-08T00:00:00%2B09:00&end=2026-05-15T23:59:59%2B09:00"

# 8. タスク完了 / 取消
curl -X POST "http://localhost:47823/tasks/$TASK_ID/complete"
curl -X POST "http://localhost:47823/tasks/$TASK_ID/uncomplete"

# 9. ログアウト（DB のトークンを削除）
curl -X DELETE http://localhost:47823/auth/google
```

OpenAPI ドキュメント: http://localhost:47823/docs

### カレンダー取得ポリシー（重要）

このアプリは Google ToDo / Tasks と**同期しません**（[project_plan.md §1.1](project_plan.md)）。
代わりに **Google Calendar の複数カレンダーから「埋まっている時間」を読み取って最適化の入力にします**。

複数カレンダーの扱い方針（[project_plan.md §1.0](project_plan.md) の正本）:

| カレンダー種別 | 例 | 取得対象 |
|---|---|---|
| プライマリ | 個人メイン（インターン勤務、私用予定） | **必須** |
| セカンダリ | 「試験対策 計画」等自作 | **必須** |
| 購読（iCal） | **大学時間割（UTAS など）** | **必須** |
| 公的 | 「日本の祝日」 | **対象外**（忙しさに無関係） |

`GET /calendar/calendars` でカレンダー一覧を取得し、`GET /calendar/events?calendar_ids=a,b,c` で複数指定取得できます。
Phase 2 で `user_settings.busy_calendar_ids` / `ignore_calendar_ids` を導入し、毎回パラメータを渡さなくても済むようにします。

### Phase 2 動作確認（スロット生成）

```bash
# 現在の設定確認（初回は既定値で作成）
curl http://localhost:47823/settings | python -m json.tool

# 祝日カレンダーを ignore に追加
curl -X PUT http://localhost:47823/settings \
  -H "Content-Type: application/json" \
  -d '{"ignore_calendar_ids":["ja.japanese#holiday@group.v.calendar.google.com"]}'

# 来週分のスロット生成（祝日以外の全カレンダー横断）
curl "http://localhost:47823/calendar/slots\
?start=2026-05-11T00:00:00%2B09:00\
&end=2026-05-17T23:59:59%2B09:00" | python -m json.tool
```

詳細: [docs/phase2_design.md](docs/phase2_design.md) / [docs/api_cheatsheet.md §4.5–§4.6](docs/api_cheatsheet.md)

### Phase 3 動作確認（最適化）

```bash
# タスクを 5-10 個入れた状態で
curl -X POST http://localhost:47823/optimize \
  -H "Content-Type: application/json" \
  -d '{"start":"2026-05-11T00:00:00+09:00","end":"2026-05-17T23:59:59+09:00"}' \
  | python -m json.tool

# スナップショット一覧
curl http://localhost:47823/optimizer/snapshots

# 設定変えて同じ入力で再実行（同じ snapshot を replay）
curl -X POST http://localhost:47823/optimizer/snapshots/<id>/replay \
  -H "Content-Type: application/json" \
  -d '{"config_overrides":{"weights":{"energy_match":0.2}}}'
```

詳細: [docs/phase3_design.md](docs/phase3_design.md) / [docs/api_cheatsheet.md §4.7](docs/api_cheatsheet.md)

### テスト

```bash
cd backend
uv run pytest -v
```
