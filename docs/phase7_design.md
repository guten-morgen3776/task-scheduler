# Phase 7：クラウドホスティング + モバイル常時アクセス 詳細設計

> 対象期間：2〜4 日（コードを書く時間 + デプロイの待ち時間）
> ゴール：**Mac を起動していなくてもスマホから 24/365 で使える**状態にする。
> 参照：[`project_plan.md` §8](../project_plan.md)（移行ロードマップ）、各 phase 設計

---

## 0. このフェーズの位置づけ

**やること:**
- バックエンド (FastAPI + SQLite) を **Fly.io** にホスト（SQLite を永続ボリュームに置く）
- フロントエンド (Vite ビルド成果物) を **Cloudflare Pages** にデプロイ
- OAuth を `InstalledAppFlow` (Desktop) → **Web Application Flow** に書き換え
- HTTPS 化（ホスト側で自動取得）
- PWA 化（manifest + 最低限の Service Worker）→ スマホのホーム画面に追加できるように

**やらないこと（Phase 8+ に回す）:**
- ネイティブモバイルアプリ（Capacitor / React Native）
- プッシュ通知（後述。PWA + Web Push なら手は届くが今はスキップ）
- マルチユーザー対応（自分専用なので user_id 固定で OK）
- レート制限・WAF・監査ログ（個人利用に過剰）

**Phase 6 との関係：**

```
[Phase 6]                         [Phase 7]
React on Vite (localhost:47824)   →  Cloudflare Pages (静的配信)
FastAPI (localhost:47823)         →  Fly.io (常時稼働)
SQLite (./data/app.db)            →  Fly Volume の SQLite
OAuth InstalledAppFlow            →  Web redirect flow
```

URL は最終的に:
- フロント: `https://task-scheduler.<your-subdomain>.pages.dev`（または独自ドメイン）
- バックエンド: `https://task-scheduler.fly.dev`（または独自ドメイン）

---

## 1. アーキテクチャ選定

### 1.1 ホスティングの選び方

| 候補 | コスト | 良いところ | 悩むところ |
|---|---|---|---|
| **Fly.io** (推奨) | 無料枠で 3 マシン + 3GB ボリューム | SQLite + 永続ボリュームが楽、リージョン Tokyo 可、`fly deploy` 一発 | 無料枠の今後の縮小リスク |
| Cloud Run + Cloud SQL | 数百円/月〜 | Google 提供で堅牢 | Cloud SQL が安くない、SQLite 不可 |
| Railway | 月 $5 クレジット | UI 楽 | 無料枠縮小傾向 |
| Render | 無料あり (休眠あり) | UI 楽 | 無料インスタンスは数分で sleep → cold start |

**バックエンドは Fly.io を採用**。SQLite をボリュームに置く構成が個人利用と相性◎、PostgreSQL 移行は不要。

| 候補 | フロント |
|---|---|
| **Cloudflare Pages** (推奨) | 無料・無制限帯域、ビルド自動化、`pages.dev` サブドメイン即発行 |
| Vercel | Hobby 無料、React/Vite 一級サポート |
| Netlify | 同上 |

**フロントは Cloudflare Pages**。Vercel でも実質同じだが、無料枠がより緩いので CFP を推奨。

### 1.2 DB 戦略

| 案 | 採用？ |
|---|---|
| **SQLite on Fly Volume** | ✅ 採用。1 user / 数 MB なら過不足なし、移行コスト最小 |
| Neon / Supabase Postgres | ❌ 今は不要、レイテンシも増える |
| Litestream で S3 にレプリ | ❌ バックアップ目的なら別途検討、移行コアロジックは変えない |

**SQLAlchemy 抽象**は既にあるので、後から PostgreSQL に移すのも `DATABASE_URL` 環境変数差し替え + Alembic 再適用で済む。Phase 7 では SQLite を引き続き使う。

### 1.3 認証戦略

| Phase | 認証 |
|---|---|
| いま | `InstalledAppFlow.run_local_server()` — サーバー側でブラウザを開く |
| Phase 7 | `Flow` (Web Application Flow) — フロントが Google の認可 URL に遷移、callback で code を受け取り token 交換 |

Google Cloud Console での作業:
- OAuth クライアント ID を **「ウェブアプリケーション」種別で新規発行**（既存の Desktop 種別とは別物）
- 承認済みリダイレクト URI に本番 callback URL（`https://task-scheduler.fly.dev/auth/google/callback`）を登録
- 必要なら開発用にローカル callback URL も並べて登録

---

## 2. データ移行

シングルユーザー前提なので、ローカル DB を本番にコピーする一回限りの作業:

1. 本番 Fly Volume をマウント
2. `data/app.db` を `flyctl ssh sftp shell` 等で本番ボリュームへ転送
3. 起動時に `alembic upgrade head`（既に最新なら no-op）

OAuth refresh token は **暗号化キー (`TOKEN_ENCRYPTION_KEY`) が変わると複合化できない**。本番に同じキーを設定 → 既存トークンが使える。

> **代替**: 本番では再度 OAuth 認可する。新規 user / 新規トークン。タスクや snapshot は app.db ごとコピーすればそのまま残る。手間は秒で済む。

---

## 3. バックエンド改修

### 3.1 認証フロー差し替え

ファイル: [`backend/app/services/google/oauth.py`](../backend/app/services/google/oauth.py)、[`backend/app/api/auth.py`](../backend/app/api/auth.py)

**新しいエンドポイント:**

| ルート | 役割 |
|---|---|
| `GET /auth/google/start` | Google の認可 URL を返す。フロントはこの URL に `window.location` 遷移 |
| `GET /auth/google/callback` | Google からのリダイレクト先。`?code=...` を受け取り token 交換、DB 保存後、フロントへ最終リダイレクト |

**実装スケッチ:**

```python
from google_auth_oauthlib.flow import Flow

def _make_flow() -> Flow:
    settings = get_settings()
    return Flow.from_client_secrets_file(
        str(settings.google_credentials_path),
        scopes=settings.google_oauth_scopes,
        redirect_uri=f"{settings.public_backend_url}/auth/google/callback",
    )

@router.get("/auth/google/start")
async def start_auth() -> dict:
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    # state は CSRF 対策で sign 付き Cookie に入れて返すのが本筋。
    # 個人利用なら省略してもよい。
    return {"authorize_url": auth_url}

@router.get("/auth/google/callback")
async def callback(code: str, ...) -> RedirectResponse:
    flow = _make_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    # ここから既存の _save_credentials() に流す
    ...
    return RedirectResponse(settings.public_frontend_url)
```

**設定追加** (`backend/app/core/config.py`):

```python
public_backend_url: str = "http://localhost:47823"
public_frontend_url: str = "http://localhost:47824"
```

本番では `https://task-scheduler.fly.dev` / `https://task-scheduler.pages.dev` を環境変数で渡す。

### 3.2 CORS 拡張

`app.add_middleware(CORSMiddleware, allow_origins=[...])` に本番フロントのオリジンを追加。dev とは別の env で切り替え。

### 3.3 既存 `POST /auth/google/local` の扱い

- 残しておく（ローカル開発用）。本番では使われない（呼ばれてもエラーで返るだけ）
- 将来削除しても良い

### 3.4 ふるまいログ用 `event_log` テーブル（将来の精度向上のための種まき）

> 将来「実測 vs 予測のズレ」「重みの効き目」を分析できるよう、本番運用と同時に追記専用のログを取り始める。読み出し UI は Phase 8+。今は溜めるだけ。

**スキーマ** (migration 0011 で追加):

| カラム | 型 | 用途 |
|---|---|---|
| `id` | INTEGER PK | auto |
| `user_id` | str | 既存テーブルと同じ user_id |
| `occurred_at` | UTCDateTime | イベント発生時刻 |
| `event_type` | str | 下表参照 |
| `subject_type` | str / null | `task` / `snapshot` / `settings` 等 |
| `subject_id` | str / null | 対象エンティティの ID |
| `payload` | JSON | イベント固有データ |

インデックス: `(user_id, occurred_at)` と `(user_id, event_type)`。

**記録するイベント:**

| event_type | payload | 取る目的 |
|---|---|---|
| `task.created` | 初期 duration_min, deadline, priority, location | 見積もりの推移を追える |
| `task.updated` | 差分 (`{field: {before, after}}`) | 「60→90分に伸ばした」が分かる → 見積もり精度の補正 |
| `task.completed` | scheduled_start/end, completed_at, duration_min | **配置 vs 実完了のズレ** — 最重要 |
| `task.uncompleted` | scheduled_start/end | 取消のパターン |
| `task.deleted` | (空) | 放棄パターン |
| `task.scheduled_fixed_changed` | 新しい値 | fix 利用パターン |
| `optimize.ran` | config_overrides, status, solve_time, 配置数/未配置数 | 重みごとの結果蓄積 |
| `snapshot.applied` | updated_task_count | 反映タイミング |
| `snapshot.written` | deleted_count, created_count, dry_run | Calendar 書込のパターン |
| `snapshot.write_deleted` | deleted_event_count | 取消頻度 |
| `task.synced_from_calendar` | updated / cleared 件数 | 手動編集の頻度 |
| `settings.updated` | 変更されたキー | 設定変更履歴 |

**サービス層:**

```python
# app/services/event_log/log.py
async def record(
    db: AsyncSession,
    user_id: str,
    event_type: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(EventLog(
        user_id=user_id,
        occurred_at=utc_now(),
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload or {},
    ))
    await db.flush()
```

**呼び出し場所**（既存 API/service に 1 行ずつ差し込み）:

- `api/tasks.py`: create / update / complete / uncomplete / delete / move
- `api/optimize.py`: optimize / apply / write / delete write
- `api/settings.py`: update
- `api/tasks.py`: sync-from-calendar

**設計上の判断:**

- **追記専用**: イベントは絶対に更新しない（履歴の信頼性のため）
- **payload は JSON 自由形式**: 後から欲しい情報が増えても schema 変更不要
- **失敗時の挙動**: ログ書込が失敗してもメイン処理は止めない（try/except でラップ）— ログのせいでタスク追加が落ちる方が嫌
- **PII 配慮**: payload に Google email や OAuth トークン等の機密は入れない

**実装コスト見積もり:** migration + model + service + 15 ヶ所への差し込みで約 3 時間。

**Phase 8+ での活用例（今はやらない）:**

| 解析 | 必要なデータ | アクション |
|---|---|---|
| 完了時刻のズレ分布 | `task.completed` payload | 全体的に遅刻気味なら duration_min を底上げ提案 |
| duration の updated 履歴 | `task.updated` payload | 個別タスクの再見積もり傾向 |
| day_type ごとの完了率 | `task.completed` × Slot 履歴 | heavy_day の cap=90 が妥当か実測で検証 |
| 重みごとの infeasible 率 | `optimize.ran` の status | 重みチューニングの自動提案 |
| fix 利用パターン | `task.scheduled_fixed_changed` | 「固定したくなる時間帯/曜日」の抽出 |

### 3.5 設定値の env 化

| 名前 | dev | prod |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | `sqlite+aiosqlite:////mnt/data/app.db` |
| `TOKEN_ENCRYPTION_KEY` | `.env` | Fly secrets |
| `GOOGLE_CREDENTIALS_PATH` | `./secrets/credentials.json` | `/app/secrets/credentials.json`（イメージにバンドル）または Fly secrets 経由 |
| `APP_ENV` | `dev` | `prod` |
| `PUBLIC_BACKEND_URL` | `http://localhost:47823` | `https://task-scheduler.fly.dev` |
| `PUBLIC_FRONTEND_URL` | `http://localhost:47824` | `https://task-scheduler.pages.dev` |

`pydantic-settings` で env から読むので、コード変更は最小。

---

## 4. フロントエンド改修

### 4.1 認証ボタンを Web Flow に

`LoginPage.tsx`:

```tsx
const { mutate } = useMutation({
  mutationFn: () => apiFetch<{ authorize_url: string }>("/auth/google/start"),
  onSuccess: (data) => {
    window.location.href = data.authorize_url;  // フルページ遷移
  },
});
```

ログイン後、バックエンドの callback がフロントの `/` にリダイレクトしてくる → `RequireAuth` が `/auth/me` を叩いて成功 → ホームへ。

### 4.2 API base URL

`api/client.ts` の `VITE_API_BASE` を本番 URL に差す。Cloudflare Pages の Environment Variables に `VITE_API_BASE=https://task-scheduler.fly.dev` を設定すれば、ビルド時に埋め込まれる。

### 4.3 PWA 化

最小実装:

- `public/manifest.webmanifest` を追加（アイコン、name、theme_color）
- `index.html` に `<link rel="manifest" ...>` を追加
- Service Worker は `vite-plugin-pwa` を使うと数行で生成可能
- iOS Safari の「ホーム画面に追加」で擬似ネイティブアプリ化

```bash
pnpm add -D vite-plugin-pwa
```

`vite.config.ts`:

```ts
import { VitePWA } from "vite-plugin-pwa";
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "task-scheduler",
        short_name: "tasks",
        theme_color: "#4f46e5",
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
    }),
  ],
});
```

オフライン対応は最低限（API レスポンスはネットワークファースト）。完全オフライン編集はやらない。

---

## 5. デプロイ手順

### 5.1 バックエンド (Fly.io)

```bash
# 初回
brew install flyctl
flyctl auth signup    # または signin
cd backend
flyctl launch         # 対話形式 — name, region (nrt = Tokyo), Dockerfile 自動生成

# ボリューム作成（SQLite 永続化）
flyctl volumes create task_scheduler_data --region nrt --size 1

# Secrets 設定
flyctl secrets set \
  TOKEN_ENCRYPTION_KEY="$(cat .env | grep TOKEN_ENCRYPTION_KEY | cut -d= -f2)" \
  APP_ENV=prod \
  PUBLIC_BACKEND_URL=https://task-scheduler.fly.dev \
  PUBLIC_FRONTEND_URL=https://task-scheduler.pages.dev \
  DATABASE_URL='sqlite+aiosqlite:////mnt/data/app.db'

# credentials.json をイメージに同梱 OR secrets ファイルで配置（後者推奨）
flyctl ssh console -C "mkdir -p /app/secrets"
# scp / sftp で credentials.json を /app/secrets/ に置く

# デプロイ
flyctl deploy
```

`fly.toml` に volume mount を書く:

```toml
[[mounts]]
  source = "task_scheduler_data"
  destination = "/mnt/data"
```

Dockerfile は `flyctl launch` が叩き台を作る。`uv` 採用なので `uv sync --frozen` + `uvicorn` で起動。

`alembic upgrade head` は起動時に走らせる:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
```

### 5.2 フロントエンド (Cloudflare Pages)

1. GitHub に push（まだなら今のうち）
2. Cloudflare Dashboard → Pages → Connect to Git → リポジトリ選択
3. Build settings:
   - Build command: `cd frontend && pnpm install && pnpm build`
   - Output: `frontend/dist`
4. Environment variable:
   - `VITE_API_BASE=https://task-scheduler.fly.dev`
5. Deploy

`https://task-scheduler.pages.dev` で公開。push のたび自動再デプロイ。

### 5.3 Google Cloud Console

1. APIs & Services → Credentials
2. 「ウェブアプリケーション」種別の OAuth クライアント ID を新規作成
3. **承認済みのリダイレクト URI** に追加:
   - `https://task-scheduler.fly.dev/auth/google/callback`
4. `client_secret_xxx.json` をダウンロード → 本番用 `credentials.json` として配置

既存 Desktop 種別の credentials は dev でのみ使用、本番には別ファイル。

---

## 6. PWA としてスマホに入れる

iOS Safari:
1. Cloudflare Pages の URL を Safari で開く
2. 共有ボタン → 「ホーム画面に追加」
3. アイコンがホーム画面に → タップで全画面表示

Android Chrome:
1. URL を開く → アドレスバーに「インストール」プロンプト
2. ホーム画面アイコン化

これで「アプリっぽい」UX が完成。Bookmark より起動が速い、ステータスバーが隠れる、戻る挙動も独立。

---

## 7. テスト戦略

Phase 6 と同じく Phase 7 はテストを最小化:

- バックエンドの新エンドポイント (`/auth/google/start`, `/auth/google/callback`) は **モックで code → token 交換ができる経路を 1 件** だけ確認
- フロント側は手動スモーク（実際にスマホで開く）

---

## 8. 実装順

1. **OAuth Web Flow 切替** — `oauth.py` と `api/auth.py` を修正、dev でブラウザフローを試す
2. **Config の env 化** — `PUBLIC_BACKEND_URL` 等を追加、CORS 動的化
3. **event_log テーブル + service + API への差込** — 本番運用前に必ず仕込んでおく（後から取り戻せないデータなので）
4. **Dockerfile + fly.toml** 雛形作成、ローカルで `docker build && docker run` 動作確認
5. **Fly.io アカウント作成 → volume 作成 → secrets 設定 → deploy**
6. **本番 DB に既存 `app.db` を sftp で投入**（または fresh start）
7. **Google Cloud Console で Web 種別 OAuth client 発行 → 本番にデプロイ**
8. **Cloudflare Pages 接続 → `VITE_API_BASE` 設定 → deploy**
9. **PWA manifest + Service Worker 追加**（`vite-plugin-pwa`）
10. **スマホで開く → ホーム画面追加 → 動作確認**
11. ドキュメント更新（README に本番 URL とデプロイ手順）

---

## 9. Phase 7 完了の判定

- [ ] Fly.io に backend がデプロイされ `https://.../health` が 200
- [ ] Cloudflare Pages に frontend がデプロイされる
- [ ] スマホで本番 URL を開いて Google ログインができる
- [ ] スマホからタスク追加・最適化・カレンダー書き込みが完走する
- [ ] Mac を sleep / 終了させてもスマホから引き続き使える
- [ ] ホーム画面に追加 → タップで全画面で起動
- [ ] CFP / Fly のオートデプロイ（main ブランチ push で更新）

---

## 10. このフェーズで残す未解決事項（Phase 8+）

- **プッシュ通知**：Web Push API + Service Worker で「次のタスクが 10 分後に始まります」みたいな通知。iOS 16.4 から Web Push 対応
- **ネイティブアプリ化**：Capacitor で React コードをそのままラップ。バックグラウンド機能を強化したいときに
- **マルチユーザー化**：今は `get_or_create_default_user` で 1 ユーザー固定。家族 / 友人とシェアしたくなったら user 管理を整備
- **障害対応**：Fly.io の zero downtime deploy、DB バックアップ（Litestream）、Sentry 等のエラートラッキング
- **CI / 自動テスト**：GitHub Actions で push 時に pytest + 型チェック
- **コスト管理**：Fly.io 無料枠の超過監視、Cloudflare Pages の使用量確認

---

## 11. リスク・落とし穴

| リスク | 対処 |
|---|---|
| OAuth redirect_uri ミスマッチ | Google Cloud Console での URI 登録ミスでログイン不可。**本番デプロイ後、Console の URI を再確認** |
| `TOKEN_ENCRYPTION_KEY` を本番で変更してしまう | DB の暗号化済 refresh_token が複合化不可になる。Fly secrets に同じ値を入れる。**変えるなら再 OAuth 認可** |
| Fly Volume の region とアプリ region 不一致 | アプリ起動失敗。`--region nrt` を揃える |
| Cloudflare Pages の build がタイムアウト | `pnpm install` でキャッシュ未設定だと遅い。Pages の build cache を有効化 |
| credentials.json をリポジトリにコミット | 機密漏洩。`.gitignore` で除外、Fly secrets ファイルとしてアップロード |
| 無料枠超過の課金 | Fly は usage-based。月 1 回 dashboard で確認 |

---

## 12. ロールバック戦略

最終的に「やっぱりローカルで」となった場合の戻し方:

1. Fly app を停止（`flyctl scale count 0`）
2. CFP の deploy hook 無効化
3. ローカルの `.env` / `start.command` はそのまま残してあるので即復活
4. Google Cloud Console の本番 redirect URI は残してもよい（追加だけなので影響なし）

ロールバックコスト ≒ 0。気軽に試して、合わなければ戻せる。
