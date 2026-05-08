# Phase 0：環境構築 詳細設計

> 対象期間：0.5日
> ゴール：Phase 1 以降の実装に着手できる状態（プロジェクト雛形 + DB 初期化 + OAuth クライアント作成 + 環境変数整備）を作る。
> 参照：`project_plan.md` §4 Phase 0、§3 リポジトリ構成、§8 将来移行を見据えた設計指針

---

## 0. このフェーズで「やらないこと」（重要）

実装を最小化するため、以下は Phase 0 では着手しない。

- ビジネスロジック（タスク CRUD、Calendar 連携、最適化）→ Phase 1 以降
- フロントエンドの画面実装（雛形のみ）→ Phase 6
- Docker / CI 設定 → MVP では不要（§2.4）。CI は Phase 4 以降に検討
- マイグレーションの本格化 → 初回マイグレーション（空でも可）まで

---

## 1. 成果物チェックリスト

このフェーズ完了の判定条件。

- [ ] リポジトリのディレクトリ構造が `project_plan.md` §3 に従って作られている
- [ ] `backend/` で `uvicorn app.main:app --reload` が起動し、`GET /health` が `{"status": "ok"}` を返す
- [ ] `frontend/` で `pnpm dev` が起動し、Vite のデフォルト画面が表示される
- [ ] SQLite ファイルが `backend/data/app.db` に作成され、`alembic upgrade head` が成功する
- [ ] Google Cloud Console で OAuth 2.0 クライアント ID（デスクトップアプリ種別）が作成され、`credentials.json` が `backend/secrets/` 配下にある（git 管理外）
- [ ] `.env.example` が整備され、`.env` が `.gitignore` に含まれている
- [ ] `pyproject.toml` / `package.json` の依存が固定されている（`uv lock` / `pnpm-lock.yaml` がコミットされる）
- [ ] `README.md` 末尾に「セットアップ手順」のセクションがあり、新規 clone から起動まで再現できる

---

## 2. リポジトリ初期化

### 2.1 ルートに置くファイル

```
task-scheduler/
├── .gitignore
├── .editorconfig
├── README.md                    # 末尾に Phase 0 のセットアップ手順を追記
├── project_plan.md              # 既存
├── task_scheduler_design.md     # 既存
└── docs/
    ├── phase0_design.md         # このファイル
    └── phase1_design.md
```

### 2.2 `.gitignore`（最低限）

Python / Node / OS / シークレット / DB ファイルをまとめて除外。

```
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Node
node_modules/
dist/
.vite/

# OS
.DS_Store
Thumbs.db

# Secrets
.env
.env.local
backend/secrets/
backend/data/
*.sqlite
*.sqlite-journal
*.db
*.db-journal

# IDE
.vscode/
.idea/
```

### 2.3 `.editorconfig`

Python は 4 スペース、TS は 2 スペース、行末改行 LF を統一。

---

## 3. バックエンド初期化（`backend/`）

### 3.1 ディレクトリ作成

`project_plan.md` §3 の構成に従い、Phase 0 では空ディレクトリと最小限の `__init__.py` のみ作る。

```
backend/
├── app/
│   ├── __init__.py
│   ├── api/__init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py            # Phase 0 で実装
│   │   └── database.py          # Phase 0 で実装
│   ├── models/__init__.py
│   ├── schemas/__init__.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── google/__init__.py
│   │   ├── tasks/__init__.py
│   │   ├── slots/__init__.py
│   │   └── optimizer/__init__.py
│   └── main.py                  # Phase 0 で実装
├── tests/
│   └── __init__.py
├── alembic/                     # alembic init で生成
├── alembic.ini                  # alembic init で生成
├── data/                        # SQLite 配置先（git 管理外）
│   └── .gitkeep
├── secrets/                     # OAuth クライアント JSON 配置先（git 管理外）
│   └── .gitkeep
├── .env.example
└── pyproject.toml
```

### 3.2 パッケージ管理（`uv` を採用）

`uv` を採用する理由：依存解決が速く、`uv lock` で再現性を保証できる。Poetry でも可だが Phase 0 では `uv` を選ぶ。

```bash
cd backend
uv init --package
```

### 3.3 `pyproject.toml`（依存）

Phase 0 で入れる依存だけ。Phase 1 以降の依存は該当フェーズで追加する。

| 依存 | 用途 | フェーズ |
|---|---|---|
| `fastapi` | Web フレームワーク | Phase 0 |
| `uvicorn[standard]` | ASGI サーバー | Phase 0 |
| `pydantic-settings` | `.env` から設定読込 | Phase 0 |
| `sqlalchemy[asyncio]>=2.0` | ORM | Phase 0 |
| `aiosqlite` | 非同期 SQLite ドライバ | Phase 0 |
| `alembic` | マイグレーション | Phase 0 |
| `python-dateutil` | 日付処理 | Phase 0（早めに固定） |
| `ruff`（dev） | Lint/Format | Phase 0 |
| `pytest` / `pytest-asyncio`（dev） | テスト基盤 | Phase 0 |

Phase 1 以降で追加する依存（Phase 0 では入れない）：`google-auth-oauthlib`, `google-api-python-client`, `cryptography`（トークン暗号化）, `pulp`（Phase 3）。

### 3.4 `app/core/config.py`（設定の外部化）

`pydantic-settings` で `.env` を読み込む `Settings` クラスを実装する。

**カラム / フィールド設計：**

| フィールド | 型 | 既定値 | 用途 |
|---|---|---|---|
| `app_env` | `Literal["dev", "test", "prod"]` | `"dev"` | 動作モード |
| `database_url` | `str` | `sqlite+aiosqlite:///./data/app.db` | SQLAlchemy 接続文字列 |
| `google_credentials_path` | `Path` | `./secrets/credentials.json` | OAuth クライアント JSON |
| `google_oauth_scopes` | `list[str]` | `["https://www.googleapis.com/auth/calendar"]` | Calendar のみ（Tasks は使わない） |
| `token_encryption_key` | `str` | （`.env` で必須） | refresh_token 暗号化キー（Fernet） |
| `app_timezone` | `str` | `"Asia/Tokyo"` | 表示用 TZ。保存は UTC |

**設計上のポイント（§8.1 準拠）：**
- 絶対パスをハードコードしない。すべて `.env` 経由
- `Settings` インスタンスは `@lru_cache` でシングルトン化（FastAPI の DI で共有）

### 3.5 `app/core/database.py`（SQLAlchemy セッション）

非同期エンジン + セッションファクトリ。Phase 0 では「接続できる」ことだけ確認できれば良い。

- `create_async_engine(settings.database_url)` でエンジン作成
- `async_sessionmaker(...)` でセッションファクトリ
- FastAPI 依存関数 `get_db()` を提供（Phase 1 以降で使用）

### 3.6 `app/main.py`（最小エントリポイント）

```
- FastAPI() インスタンス
- ルート: GET /health → {"status": "ok"}
- CORS は Phase 6 で frontend を実装するときに追加（Phase 0 では不要）
```

### 3.7 Alembic 初期化

```bash
cd backend
uv run alembic init alembic
```

**カスタマイズ：**
- `alembic/env.py` で `Settings.database_url` を読み込むように修正
- `alembic.ini` の `sqlalchemy.url` は空にして、コードから注入
- 初回マイグレーションは「空のリビジョン」を作って `upgrade head` が通ることだけ確認
  ```bash
  uv run alembic revision -m "initial empty"
  uv run alembic upgrade head
  ```
- Phase 1 でテーブルを追加するときに本格的なマイグレーションを書く

### 3.8 ruff 設定

`pyproject.toml` の `[tool.ruff]` に最低限の設定。

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP"]
```

---

## 4. フロントエンド初期化（`frontend/`）

### 4.1 Vite + React + TypeScript

```bash
cd frontend
pnpm create vite . --template react-ts
pnpm install
```

### 4.2 ディレクトリ準備

`project_plan.md` §3 に従い、Phase 1 以降で使う空ディレクトリを先に切る。

```
frontend/src/
├── api/          # 型付き API クライアント（Phase 4 以降）
├── components/   # Phase 6
├── hooks/        # Phase 6
├── pages/        # Phase 6
├── App.tsx
└── main.tsx
```

### 4.3 Phase 0 で入れる依存

Phase 0 では Vite テンプレートのデフォルト依存のみ。`shadcn/ui` / `tailwindcss` / `@tanstack/react-query` などは Phase 6 着手時に追加する。

**例外**：将来のクラウド/モバイル移行を考えると API クライアント層を分離する設計（§8.1）が必要。Phase 0 では空ディレクトリだけ用意しておけば十分。

### 4.4 動作確認

`pnpm dev` で Vite のデフォルト画面が出ることだけ確認。

---

## 5. SQLite ファイルの配置

### 5.1 配置場所

`backend/data/app.db`（git 管理外、`.gitignore` 済み）

**理由：**
- `~/.config/...` のような絶対パスは §8.1 で禁止
- リポジトリ相対のほうがプロジェクト切替が楽
- `data/` ディレクトリごと丸ごとバックアップが取れる

### 5.2 接続文字列

`.env.example`：
```
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
```

実行時の cwd は `backend/` を想定。

### 5.3 PRAGMA 等

§8.1 の方針に従い、SQLite 固有機能には依存しない。
- `PRAGMA foreign_keys = ON` は接続時に毎回設定する（SQLAlchemy の `event.listens_for(Engine, "connect")` で）。これは PostgreSQL 移行時には不要になる程度のもので、ロックインにはならない
- `PRAGMA journal_mode = WAL` は性能要件次第。Phase 0 では入れない（必要になったら入れる）

---

## 6. Google Cloud Console 設定

### 6.1 プロジェクト作成

1. https://console.cloud.google.com/ にアクセス
2. 新規プロジェクト作成（例：`task-scheduler-personal`）
3. 「API とサービス」→「ライブラリ」から **Google Calendar API のみ** を有効化
   - **Google Tasks API は有効化しない**（§1.1 の方針変更により不要）

### 6.2 OAuth 同意画面

- ユーザータイプ：**外部**
- アプリ名：`task-scheduler`
- ユーザーサポートメール：自分のメール
- スコープ：`https://www.googleapis.com/auth/calendar`（読み書き）
- **テストユーザーに自分の Gmail アドレスを追加**（個人利用なので verification は不要、§7 のリスク表参照）

### 6.3 OAuth クライアント ID 作成

- 種類：**デスクトップアプリ**（`InstalledAppFlow` を使うため。§2.1 採用技術）
- 名前：`task-scheduler-desktop`
- 作成後、JSON をダウンロードして `backend/secrets/credentials.json` として配置

**注意（§8.1 準拠）：**
- ファイルパスを Python コードに直書きしない。`.env` の `GOOGLE_CREDENTIALS_PATH` 経由で読み込む
- 将来 Web フローに移行するときも、設定切替で対応できるようにする

### 6.4 リダイレクト URI

`InstalledAppFlow` を使う場合、ローカルで `http://localhost:<random_port>/` がランタイムで使われる。Cloud Console 側での URI 登録は不要。

将来 Web フローに移行する際に登録する想定（§8.2 Step B）。

---

## 7. `.env.example` 整備

`backend/.env.example`：

```dotenv
# 動作環境
APP_ENV=dev

# データベース
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# Google OAuth
GOOGLE_CREDENTIALS_PATH=./secrets/credentials.json
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/calendar

# トークン暗号化（Fernet 鍵を生成して入れる）
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=

# タイムゾーン
APP_TIMEZONE=Asia/Tokyo
```

`.env` 自体は git 管理外。新規セットアップ時は `.env.example` をコピーして作る。

---

## 8. README セットアップ手順

`README.md` 末尾に追記する内容：

```
## セットアップ（Phase 0）

### 必要なもの
- Python 3.11+
- Node.js 20+ / pnpm
- uv（`curl -LsSf https://astral.sh/uv/install.sh | sh`）

### バックエンド
1. `cd backend`
2. `uv sync`
3. `cp .env.example .env` して必要項目を埋める
4. Google Cloud Console で取得した `credentials.json` を `backend/secrets/` に配置
5. `uv run alembic upgrade head`
6. `uv run uvicorn app.main:app --reload`
7. `curl http://localhost:8000/health` で `{"status":"ok"}` を確認

### フロントエンド
1. `cd frontend`
2. `pnpm install`
3. `pnpm dev`
```

---

## 9. Phase 0 完了の動作確認シナリオ

ターミナル A：
```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

ターミナル B：
```bash
curl http://localhost:8000/health
# → {"status":"ok"}

cd backend
uv run alembic current
# → 初回 revision が表示される

ls -la data/app.db
# → ファイルが存在する
```

ターミナル C：
```bash
cd frontend
pnpm dev
# ブラウザで http://localhost:5173 にアクセスし、Vite のデフォルト画面が出る
```

すべて通れば Phase 0 完了 → Phase 1 へ。

---

## 10. このフェーズで意識する将来移行対応（§8 抜粋）

Phase 0 段階で守るべき設計判断（実装コスト ≒ ゼロ）：

| 項目 | この段階での対応 |
|---|---|
| DB 抽象 | SQLAlchemy 経由で書く（生 SQL 禁止）。後で PostgreSQL に切替可能 |
| 設定外部化 | すべて `pydantic-settings` 経由。コード内に絶対パス・URL を書かない |
| 認証ファイル | `credentials.json` のパスを `.env` で指定。直書き禁止 |
| TZ | 内部は UTC 想定。`APP_TIMEZONE` は表示用 |
| シークレット | `.gitignore` で除外。`Fernet` で暗号化する仕組みは Phase 1 で実装 |
