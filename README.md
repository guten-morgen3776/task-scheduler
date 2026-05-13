# task-scheduler

Google Calendar の空き時間に、登録したタスクを **MIP（整数計画法）** で自動配置する個人用タスク管理 Web アプリ。

「やることはあるのに、いつやるか決められない」状態を、ソルバー任せにすることで解消する。

- **デモ（個人OAuth設定済み、本人のみログイン可）**
  - フロント: https://task-scheduler.pages.dev
  - API: https://super-ultra-task-solver.fly.dev

---

## 1. このアプリで解決したかったこと

Google ToDo / カレンダーを併用する中で、次のような不満があった。

- **タスクは溜まるが、いつやるかを毎回考えるのが面倒** — 締切・優先度・所要時間を見比べて手動で時間割を組むコストが高い
- **重いタスクを疲れている時間に置いてしまう** — 集中力が必要な作業を夜遅くに回して結局終わらない
- **「場所」を考慮した配置がどのツールでもできない** — 大学にいる時間は紙のノートが必要なタスクをやりたい、家でしかできないタスクは家の時間に置きたい
- **既存予定（インターン勤務・授業）との被りを毎回手で避けるのが大変**

これらを「タスクの属性（所要時間・優先度・締切・場所）」と「日のキャパシティ（拘束時間ベースの day_type）」「スロットのエネルギー」をマッチングする **整数計画問題** として定式化し、毎日の時間割をワンクリックで生成できるようにした。

---

## 2. 主な機能

### タスク管理（Google ToDo 風 UI の自作タスク管理）

- タスクリスト（複数）/ タスク（タイトル・所要時間・優先度・締切・場所・メモ）の CRUD
- 完了 / 未完了切替、ドラッグ並び替え
- 「場所」属性：`home` / `university` / `office` / `anywhere`

### Google Calendar 連携

- OAuth2（Web Application Flow）で複数カレンダー横断の予定取得
- 祝日カレンダーなどは設定で除外可能
- 最適化結果はワンクリックで Google Calendar に書き込み、再実行時は冪等に上書き

### 自動スケジューリング（MIP ソルバー）

- 「カレンダーの埋まり方」と「ユーザー設定の作業可能時間帯」から、その週の作業可能スロットを自動生成
- 拘束時間（バッファ込み）でその日の `day_type` を判定（`free_day` / `light_day` / `medium_day` / `heavy_day` / `intern_day`）
  - 各 day_type が `energy_score` と「1 タスクの最大長」をスロットに与える
- MIP で以下を同時に最適化:
  - **ハード制約**: 締切、スロット容量、場所一致、最小断片サイズ、最大分割数、所要時間上限、締切付きタスクの強制配置
  - **目的関数**: 優先度加点 / 緊急度加点 / 高エネルギースロットへの長尺タスク誘導 / 同一タスクの集約 / 早期配置 / 未配置のペナルティ

### 再現実験用スナップショット

- `/optimize` 実行ごとに「入力（タスク・スロット・設定）と結果」を Snapshot として保存
- `/optimizer/snapshots/{id}/replay` で同じ入力に対し設定を変えて再実行可能 → 重みのチューニングが確定的に行える

### PWA / スマホ対応

- Cloudflare Pages 経由で配信、ホーム画面に追加するとアプリのように起動
- モバイル幅でも操作可能なレイアウト

---

## 3. 使用技術と選定理由

### バックエンド

| 技術 | 用途 | 選定理由 |
|---|---|---|
| **Python 3.13** | 言語 | 最適化ライブラリ（PuLP / OR-Tools）の充実度から実質一択 |
| **FastAPI** | Web フレームワーク | 非同期対応・Pydantic v2 と統合された型ヒント・OpenAPI 自動生成 |
| **Pydantic v2** | バリデーション | リクエスト/レスポンス、`OptimizerConfig` の動的上書きを型安全に扱える |
| **SQLAlchemy 2.0 + Alembic** | ORM / マイグレーション | 後から PostgreSQL に乗せ替える際も接続文字列差し替えで済むよう抽象を維持 |
| **SQLite + aiosqlite** | DB | **個人利用**前提でファイル 1 個に集約。Docker 不要、バックアップはコピーで完結。後から PostgreSQL に乗せ替える際は接続文字列の差し替えだけで済むよう SQLAlchemy 抽象越しに使う |
| **PuLP + CBC** | MIP ソルバー | OSS で依存軽量、MVP として十分な規模（数十タスク × 数百スロット）を秒オーダーで解ける。インターフェイス抽象を挟んでいるので OR-Tools への乗り換えも容易 |
| **uv** | パッケージ管理 | pip / Poetry より圧倒的に高速。`pyproject.toml` ベースで Lock も自動 |
| **Google OAuth + Calendar API** | 外部連携 | Tasks API は独自フィールド（所要時間・場所・優先度）を持てないため使用せず、Calendar API のみ採用 |
| **cryptography (Fernet)** | refresh_token 暗号化 | 単一ユーザーでも DB に平文保存しない。鍵は環境変数で外出し |

### フロントエンド

| 技術 | 用途 | 選定理由 |
|---|---|---|
| **React 19 + Vite** | フレームワーク / ビルド | 軽量で立ち上がりが速く、Cloudflare Pages の静的配信と相性が良い |
| **TypeScript** | 言語 | API の型を生成 / 共有して、UI とサーバ間の食い違いを早期に検出 |
| **TanStack Query** | サーバ状態管理 | キャッシュ + 楽観的更新 + リフェッチを宣言的に書ける。タスク CRUD と最適化結果のキャッシュ整合が肝なので必須 |
| **React Hook Form + Zod** | フォーム / 検証 | タスク作成・設定編集が多いため、軽量で型に乗ったバリデーションが必要 |
| **React Router v7** | ルーティング | ページ数が少ないため Next.js は過剰、SPA で十分 |
| **Tailwind CSS v4** | スタイリング | クラスベースで Google ToDo 風のシンプルな UI を素早く組む |
| **vite-plugin-pwa** | PWA 化 | スマホのホーム画面追加 + 最低限のオフライン耐性を、設定だけで実現 |

### インフラ / デプロイ

| 技術 | 用途 | 選定理由 |
|---|---|---|
| **Fly.io（Tokyo / nrt）** | バックエンド | 無料枠で常時稼働 + 永続ボリュームに SQLite を置ける。`fly deploy` 一発で済む |
| **Cloudflare Pages** | フロントエンド | 無料・無制限帯域、GitHub 連携で自動デプロイ。SPA リダイレクトもネイティブ対応 |
| **Fly Volumes** | DB 永続化 | SQLite を `/mnt/data/app.db` で永続化、PostgreSQL を立てる必要なし |

### 開発支援

| 技術 | 用途 |
|---|---|
| ruff | Python の Lint / Format |
| pytest + pytest-asyncio | バックエンドのユニット / シナリオテスト |
| ESLint + typescript-eslint | TS の Lint |
| Alembic | スキーマ進化（場所列追加・weight列廃止など複数回のマイグレーション） |

---

## 4. アーキテクチャ

```
                ┌────────────────────────┐
                │  Cloudflare Pages       │
                │  (React / Vite / PWA)   │
                └──────────┬──────────────┘
                           │ REST (HTTPS)
                           ▼
                ┌────────────────────────┐
                │  Fly.io (FastAPI)       │
                │                         │
                │  ┌─ Auth (OAuth Web Flow)│─┐
                │  │                       │ │
                │  ├─ Task CRUD           │ │  ┌──────────────────┐
                │  │                       │ ├─▶│  Google Calendar │
                │  ├─ Calendar Adapter    │ │  │       API        │
                │  │  (複数カレンダー)    │ │  └──────────────────┘
                │  │                       │ │
                │  ├─ Slot Generator       │ │
                │  │  (日タイプ・場所推定) │ │
                │  │                       │ │
                │  └─ Optimizer            │ │
                │     PuLP / CBC          │ │
                │     ├ constraints/*.py  │ │
                │     ├ objectives/*.py   │ │
                │     └ snapshot 保存     │ │
                │                          │ │
                └──────────┬──────────────┘ │
                           │                │
                           ▼                │
                ┌────────────────────────┐  │
                │  SQLite (Fly Volume)    │  │
                │  tasks / lists /        │  │
                │  user_settings /        │  │
                │  oauth_token (暗号化) /  │  │
                │  snapshots / event_log  │  │
                └─────────────────────────┘  │
```

---

## 5. 設計上の工夫

### 5.1 最適化エンジンを「差し替え可能」な構造にした

最適化は試行錯誤が前提なので、制約・目的関数を **1 クラス 1 ファイル** で配置し、`OptimizerConfig` の `enabled_constraints` / `enabled_objectives` で動的に ON/OFF できる構造にしている。

```
backend/app/services/optimizer/
├── domain.py              # Task / Slot / Assignment（ソルバー非依存）
├── backend/
│   ├── base.py            # SolverBackend ABC
│   └── pulp_backend.py    # PuLP 実装（OR-Tools 実装を後から追加可能）
├── constraints/
│   ├── deadline.py
│   ├── slot_capacity.py
│   ├── location_compatibility.py
│   ├── force_deadlined.py
│   ├── min_fragment_size.py
│   ├── max_fragments.py
│   └── duration_cap.py
├── objectives/
│   ├── priority.py
│   ├── urgency.py
│   ├── energy_match.py
│   ├── early_placement.py
│   ├── keep_together.py
│   └── unassigned_penalty.py
├── config.py              # OptimizerConfig（重み・有効化フラグ・時間制限）
├── orchestrator.py        # 制約と目的関数を集めて solve
└── service.py             # infeasible retry chain（後述）
```

新しい制約を追加するときは「ファイルを 1 つ書いて `enabled_constraints` に名前を入れる」だけで済む。

### 5.2 infeasible retry chain

「締切付きタスクは必ず配置する」を強い制約にしているため、素朴に解くと簡単に infeasible になる。これに対し、最大 4 段階で段階的に制約を緩めて再実行する仕組みを入れている。

| 段 | 緩和内容 |
|---|---|
| 1 | 通常運用（work_hours 内、duration_cap 有効） |
| 2 | 作業時間を 23:30 まで延長 |
| 3 | 作業時間を 23:59 まで延長 |
| 4 | duration_cap を無効化（last resort） |

各段の延長スロットは `energy_score × 0.3` で生成されるため、通常段で fit するケースでは夜スロットは使われない。どの段で確定したかは `notes` で UI に返している。

### 5.3 場所制約のための「場所ウィンドウ」モデル

「同じ日に大学にいる間は、授業の合間でも図書館でタスクできる」という現実を素直に表現するため、同日の同場所イベントを 1 つのウィンドウに集約し、ウィンドウの境界（始点と終点）にだけ通学・通勤時間を加算する設計にした。ウィンドウ内の隙間は free。これにより「授業の合間 = 大学 location のスロット」「夕方帰宅後 = home location のスロット」が自動的に分離される。

### 5.4 再現実験を可能にするスナップショット

`/optimize` の入力（タスク・スロット・設定）と結果をまるごと DB に保存し、`/snapshots/{id}/replay` で設定を上書きして同じ入力に対し別条件で再実行できる。重みのチューニングが「気分」ではなく確定的なテストになる。

### 5.5 将来のクラウド・モバイル移行を見越した設計

最初から「個人ローカル利用」と「将来のクラウド・マルチユーザー化」を両立できるよう、以下の方針で書いている。

- **DB**: SQLAlchemy 抽象越し / `user_id` カラムを最初から持つ（値は当面固定）
- **API**: ステートレス REST、リクエストごとに `user_id` でアクセス制御できる構造
- **時刻**: 保存は UTC + TZ 情報、表示は Asia/Tokyo に変換
- **設定**: 環境変数経由（pydantic-settings）、ローカル絶対パスをコードに書かない
- **OAuth**: Desktop Flow → Web Flow への移行を Phase 7 で実施済み

これらにより、Phase 7 で実際に Fly.io へ移行した際は、コード変更を最小限に抑えられた。

---

## 6. 開発フェーズ

機能ごとにフェーズを区切り、それぞれ設計ドキュメントを残して進めた。

| Phase | 内容 | 設計ドキュメント |
|---|---|---|
| 0 | 環境構築 / Alembic 初期化 / OAuth クライアント発行 | [docs/phase0_design.md](docs/phase0_design.md) |
| 1 | OAuth ローカルフロー / タスク CRUD / Calendar 取得 | [docs/phase1_design.md](docs/phase1_design.md) |
| 2 | スロット生成（日タイプ判定・移動バッファ） | [docs/phase2_design.md](docs/phase2_design.md) |
| 3 | MIP 最適化エンジン（差し替え可能構造） | [docs/phase3_design.md](docs/phase3_design.md) |
| 4 | 場所制約 / 場所ウィンドウモデル | [docs/phase4_design.md](docs/phase4_design.md) |
| 5 | カレンダー書き込み（冪等） | [docs/phase5_design.md](docs/phase5_design.md) |
| 6 | React UI / 設定画面 / 最適化結果プレビュー | [docs/phase6_design.md](docs/phase6_design.md) |
| 7 | Fly.io + Cloudflare Pages デプロイ / Web OAuth Flow / PWA | [docs/phase7_design.md](docs/phase7_design.md) |

その他の参考ドキュメント:

- [project_plan.md](project_plan.md) — 全体計画・技術選定の意思決定
- [task_scheduler_design.md](task_scheduler_design.md) — 初期の設計概要
- [docs/optimizer_overview.md](docs/optimizer_overview.md) — 最適化エンジンの全変数・全制約・全目的関数の一覧
- [docs/api_cheatsheet.md](docs/api_cheatsheet.md) — API リファレンス
- [docs/feature_backlog.md](docs/feature_backlog.md) — 要望と実装状況

---

## 7. 今後の改善余地

- **行動学習**: 過去の実績（予定通り完了したか、ずらしたか）から `energy_score` や `weight` のデフォルト値を自動調整
- **OR-Tools への切り替え**: タスク数が増えて PuLP が秒で解けなくなった場合の置き換え（インターフェイスは既に抽象化済み）
- **インクリメンタル最適化**: `/optimize` を毎回ゼロから解くのではなく、既存配置を維持しつつ差分だけ再計算
- **プッシュ通知**: PWA + Web Push で「次のタスクが 10 分後に始まる」を通知
- **マルチユーザー化**: `user_id` カラムは既に用意済み、UI ログイン画面と JWT 発行を足せば移行可能

---

## ライセンス

個人利用前提のため、ライセンスは未設定。
