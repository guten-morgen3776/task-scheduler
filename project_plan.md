# タスク自動スケジューリングアプリ - 技術スタック & 進め方

> `task_scheduler_design.md` を踏まえて、具体的な技術選定と進め方を整理したドキュメント。
> レビュー観点：「この技術選定で進めて良いか」「ロードマップの粒度・順序が妥当か」

---

## 1. プロジェクト概要（要約）

**自作のタスク管理 Web アプリ**（Google ToDo の代替）+ 登録タスクを Google カレンダーの空き時間に **MIP（整数計画法）** で最適配置するアプリ。

- 入力：本アプリで登録したタスク（タイトル・所要時間・重さ・優先度・締切）
- 入力：Google Calendar の既存予定 + ユーザー設定（作業可能時間帯）
- 処理：日タイプ判定 → スロット生成 → MIP で最適配置
- 出力：Google Calendar への予定書き込み + React UI での確認・編集

**コアの差別化要素**：単なる時間埋めではなく、「タスクの重さ × スロットのエネルギー」をマッチングさせる点。

### 1.0 カレンダー取得ポリシー（2026-05-08 確定）

**ユーザーは複数の Google Calendar を持っていることが多い**ため、最適化の入力として「埋まっている時間」を取得する際は **複数カレンダー横断**で扱う。

| 種類 | 例 | 取得対象か |
|---|---|---|
| プライマリ | 個人のメイン（インターン勤務、私用予定など） | **必須** |
| セカンダリ | 「試験対策 計画」など自分で作った追加カレンダー | **必須** |
| 共有カレンダー | 家族・チームのカレンダー | 必須（任意で除外可） |
| 購読カレンダー（iCal） | **大学の時間割**（UTAS など） | **必須** |
| 公的カレンダー | 「日本の祝日」など | **不要**（祝日に色を付ける情報、忙しさには関係しない） |

**運用ルール**:

- 既定は「ユーザーがアクセスできる全カレンダーから祝日系を除いたもの」
- ユーザーが個別に除外したいカレンダーがあれば追加で除外
- `GET /calendar/calendars` でカレンダー一覧を取得し、`GET /calendar/events?calendar_ids=a,b,c` で複数指定取得が可能（Phase 1 実装済）
- Phase 2 で `user_settings` テーブルに `busy_calendar_ids` / `ignore_calendar_ids` を持ち、設定駆動で自動的にこのポリシーを適用する
- イベントごとにレスポンスへ `calendar_id` を含めるので、UI で由来を表示できる

### 1.1 方針変更（2026-05-08）：Google Tasks API は使わず、自作する

当初は Google ToDo のタスクを取得して使う設計だったが、以下の理由から **自作のタスク管理に切り替える**：

- Google Tasks には `duration_min` / `weight` / `priority` といった独自フィールドが存在しないため、別 DB で紐付け管理が必要 → 二重管理になる
- 自作なら必要なフィールドをネイティブに持てる
- 出力先が Google Calendar である限り、ユーザーから見た使用感（カレンダーに予定が入る）はほぼ同じ
- 個人利用前提のため、Google ToDo の Android/iOS 連携を諦めるコストは小さい

**UI の方針**：Google ToDo の見た目・操作感を模倣しつつ、本アプリ独自フィールドを追加する。

---

## 2. 技術スタック詳細

### 2.1 バックエンド

| 項目 | 採用技術 | 補足 |
|---|---|---|
| 言語 | Python 3.11+ | 最適化ライブラリの充実度から Python 一択 |
| Webフレームワーク | FastAPI | 非同期対応・自動ドキュメント生成・型ヒント親和性 |
| ASGIサーバー | Uvicorn | FastAPI 標準 |
| 最適化ソルバー | PuLP (CBC backend) | 依存少なく、無料、MVP に最適 |
| 補助ライブラリ | OR-Tools | PuLP で性能不足になった場合の予備（後続フェーズで検討） |
| 認証 | google-auth + google-auth-oauthlib | OAuth2 のローカル開発は `InstalledAppFlow`。スコープは Calendar のみ |
| Google APIクライアント | google-api-python-client | Calendar API のみ使用（Tasks API は廃止） |
| 日付処理 | python-dateutil + zoneinfo | タイムゾーン（Asia/Tokyo）厳密に扱う |
| バリデーション | Pydantic v2 | FastAPI と統合 |

### 2.2 データベース

| 項目 | 採用技術 | 補足 |
|---|---|---|
| DB | **SQLite** | 個人利用前提のため軽量で十分。ファイル1個で完結し、Docker 不要 |
| ORM | SQLAlchemy 2.0 + Alembic | マイグレーションは Alembic |
| ドライバ | aiosqlite | FastAPI 非同期対応 |

**SQLite で十分な理由**：
- 単一ユーザー想定で同時書き込み競合がほぼ発生しない
- ローカル動作で完結するため運用コストゼロ（バックアップはファイルコピー）
- SQLAlchemy 経由で書けば、後で PostgreSQL に移行する場合も大半は接続文字列の変更だけで済む

**保持するデータ**：
- **タスク本体**（自作タスク管理。詳細は §2.2.1）
- **タスクリスト**（複数リスト対応 = Google ToDo の「リスト」）
- ユーザー設定（最適化エンジンの重みパラメータ、作業可能時間帯、location_buffer）
- 日タイプ定義（カスタマイズ可能にする想定）
- 過去の最適化結果ログ（後の改善・行動学習用）
- 最適化エンジン用のシナリオスナップショット（再現実験用 → §6 で詳述）
- OAuth トークン（refresh_token は暗号化必須）

#### 2.2.1 タスクのスキーマ（自作）

Google ToDo 互換 + 独自フィールド:

| カラム | 型 | 由来 | 備考 |
|---|---|---|---|
| `id` | TEXT (UUID) | 独自 | 主キー |
| `list_id` | TEXT | Google ToDo 互換 | タスクリスト |
| `title` | TEXT | Google ToDo 互換 | 必須 |
| `notes` | TEXT | Google ToDo 互換 | メモ |
| `parent_id` | TEXT | Google ToDo 互換 | サブタスク用 |
| `position` | TEXT | Google ToDo 互換 | 並び順 |
| `completed` | BOOLEAN | Google ToDo 互換 | 完了フラグ |
| `due` | DATETIME | Google ToDo 互換 | 期日（表示用） |
| **`duration_min`** | INT | **独自** | 所要時間。既定値 60 |
| **`weight`** | REAL | **独自** | タスクの重さ 0〜1。既定値 0.5 |
| **`priority`** | INT | **独自** | 1〜5。既定値 3 |
| **`deadline`** | DATETIME | **独自** | 厳密な締切（最適化のハード制約に使う） |
| **`scheduled_event_id`** | TEXT | **独自** | カレンダー反映後の Google Calendar イベントID |
| **`scheduled_start`** | DATETIME | **独自** | 最適化で配置された開始時刻 |
| `created_at`, `updated_at` | DATETIME | 独自 | 監査用 |

`due` と `deadline` を分けている理由：Google ToDo の `due` は表示上の期日（柔らかい）、本アプリの `deadline` は MIP のハード制約として使う厳密な締切。同じことが多いが必要に応じて別々に設定できるようにする。

### 2.3 フロントエンド

| 項目 | 採用技術 | 補足 |
|---|---|---|
| フレームワーク | React 18 + Vite | CRA は使わない |
| 言語 | TypeScript | 必須 |
| UIライブラリ | shadcn/ui + Tailwind CSS | カレンダー UI は FullCalendar も検討 |
| 状態管理 | TanStack Query | サーバー状態はこれ、クライアント状態は useState で十分な想定 |
| ルーティング | React Router v6 | 画面数が少ないので軽量に |
| フォーム | React Hook Form + Zod | タスク作成/編集・設定画面のバリデーション |
| ドラッグ&ドロップ | dnd-kit | タスクの並び替え（Google ToDo 同様） |

**UIの方向性**：Google ToDo の「左サイドにリスト一覧 / 右にタスク一覧」レイアウトを踏襲。タスク行をクリックすると右側にディテールパネルが開き、`duration_min` / `weight` / `priority` / `deadline` を編集できる。最適化済みタスクは「次は X 月 X 日 HH:MM に配置済み」のチップを表示。

### 2.4 開発・運用

| 項目 | 採用技術 |
|---|---|
| パッケージ管理 (Python) | uv または Poetry |
| パッケージ管理 (Node) | pnpm |
| Lint / Format (Python) | ruff |
| Lint / Format (TS) | Biome または ESLint + Prettier |
| テスト (Python) | pytest + pytest-asyncio |
| テスト (TS) | Vitest |
| コンテナ | （MVP では不要 — SQLite に変更したため） |
| CI | GitHub Actions（Lint + テスト） |

### 2.5 インフラ（MVP段階）

- **ローカル完結**を最初の目標にする（ホスティング不要）
- 将来的に公開する場合は Fly.io / Render / Cloud Run あたりが候補
- 個人利用なら SQLite + ローカルサーバーで十分

---

## 3. リポジトリ構成（提案）

```
task-scheduler/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI ルーター
│   │   ├── core/             # 設定・認証・DI
│   │   ├── models/           # SQLAlchemy モデル
│   │   ├── schemas/          # Pydantic スキーマ
│   │   ├── services/
│   │   │   ├── google/       # Calendar クライアントラッパー（Tasks API は使わない）
│   │   │   ├── tasks/        # 自作タスク管理（CRUD ロジック）
│   │   │   ├── slots/        # 日タイプ判定 + スロット生成
│   │   │   └── optimizer/    # MIP エンジン（拡張前提の構造、§6 詳述）
│   │   │       ├── domain.py         # Task / Slot / Assignment dataclass
│   │   │       ├── backend/          # ソルバーバックエンド抽象
│   │   │       │   ├── base.py       # SolverBackend ABC
│   │   │       │   └── pulp_backend.py
│   │   │       ├── constraints/      # ハード制約を1ファイル1クラスで配置
│   │   │       │   ├── base.py
│   │   │       │   ├── one_slot_per_task.py
│   │   │       │   ├── slot_capacity.py
│   │   │       │   ├── deadline.py
│   │   │       │   └── calendar_conflict.py
│   │   │       ├── objectives/       # 目的関数の各項を1ファイル1クラス
│   │   │       │   ├── base.py
│   │   │       │   ├── priority.py
│   │   │       │   ├── urgency.py
│   │   │       │   ├── energy_match.py
│   │   │       │   └── overdue_penalty.py
│   │   │       ├── config.py         # OptimizerConfig（重み・ON/OFF）
│   │   │       ├── orchestrator.py   # 制約と目的関数を組み立てて solve
│   │   │       └── snapshot.py       # 入出力スナップショット（再現実験用）
│   │   └── main.py
│   ├── tests/
│   │   └── optimizer/
│   │       ├── scenarios/    # JSON シナリオ集（小・中・極端ケース）
│   │       └── test_scenarios.py
│   ├── alembic/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   └── api/              # 型付き API クライアント
│   └── package.json
├── task_scheduler_design.md
└── project_plan.md           # このファイル
```

---

## 4. 開発の進め方（フェーズ別）

設計ドキュメントの Step 1〜6 を、より具体的なマイルストーンに分解します。

### Phase 0：環境構築（0.5日）
- [ ] backend / frontend のスケルトン作成
- [ ] SQLite ファイルの配置場所を決定（例：`backend/data/app.db`、git管理対象外）
- [ ] Alembic 初期化 + 初回マイグレーション
- [ ] Google Cloud Console で OAuth クライアント ID 作成
- [ ] `.env.example` を整備（client_id / client_secret / SQLite パス）

### Phase 1：Google Calendar 連携 + 自作タスク管理（3-4日）
- [ ] OAuth2 フロー実装（`InstalledAppFlow` でローカル動作確認、スコープは Calendar のみ）
- [ ] トークン保存（SQLite に refresh_token を簡易暗号化して保存）
- [ ] Google Calendar API：指定期間の予定取得
- [ ] **タスクCRUD（自作）**：SQLAlchemy モデル + FastAPI ルーター
  - 一覧 / 取得 / 作成 / 更新 / 削除 / 完了切替
  - フィールド：`id`, `list_id`, `title`, `notes`, `duration_min`, `weight`, `priority`, `deadline`, `completed`, `parent_id`, `position`, `created_at`, `updated_at`, `scheduled_slot_start`（最適化結果反映用）
- [ ] タスクリスト（複数リスト対応）の CRUD
- [ ] **マイルストーン**：CLI / curl で「タスク登録」「カレンダー予定取得」が動く

### Phase 2：スロット生成エンジン（2-3日）
- [ ] 作業可能時間帯の設定スキーマ定義
- [ ] 日タイプ判定ロジック（カレンダーのタイトル/場所から推定）
- [ ] 移動バッファの付与
- [ ] 空きスロットを `slot` 構造体のリストとして生成
- [ ] **マイルストーン**：来週分のスロットが正しく生成される（手動検証）

### Phase 3：MIP 最適化エンジン（5-7日 ← 試行錯誤を見込んで余裕）
**ここがプロジェクトの中核。詳細は §6 を参照。**
- [ ] domain types（Task / Slot / Assignment）を確定
- [ ] `SolverBackend` 抽象 + PuLP 実装
- [ ] 制約を1クラスずつ実装（4種：1スロット制約・容量・締切・カレンダー競合）
- [ ] 目的関数を1クラスずつ実装（4種：priority / urgency / energy_match / overdue_penalty）
- [ ] `Optimizer` オーケストレータが config から組み立てて solve
- [ ] スナップショット保存・再生機構（後の比較実験のため最初に作る）
- [ ] テストシナリオ集（5〜10個の小〜中規模ケース）で挙動確認
- [ ] **マイルストーン**：シナリオを切り替えて結果を比較できる + 制約を1つ追加するだけで動作確認できる構造が出来ている

### Phase 4：FastAPI 統合（2日）
- [ ] エンドポイント整理：
  - 認証：`/auth/google` `/auth/callback` `/auth/me`
  - タスク：`/lists` `/lists/{id}/tasks` `/tasks/{id}`（CRUD + 完了切替 + 並び替え）
  - カレンダー：`/calendar/slots`（空きスロット取得）
  - 最適化：`/optimize`（実行）/ `/calendar/apply`（書き込み）
  - 設定：`/settings`（GET/PUT、最適化の重みなど）
  - スナップショット：`/optimizer/snapshots` `/optimizer/snapshots/{id}/replay`
- [ ] エンドツーエンドで「ログイン → タスク登録 → スロット取得 → 最適化 → 結果取得」が動く
- [ ] **マイルストーン**：curl で全フロー検証

### Phase 5：カレンダー書き込み（1-2日）
- [ ] `/calendar/apply` 実装
- [ ] **冪等性**を担保（最適化結果の Snapshot ID をイベントの `extendedProperties` に保存し、再実行時は既存イベントを更新/削除）
- [ ] dry-run モード（書き込まずに結果だけ返す）
- [ ] **マイルストーン**：実カレンダーに自動で予定が入る

### Phase 6：React UI（5-7日 ← Google ToDo 代替化により範囲拡大）
**タスク管理UI（Google ToDo 模倣）：**
- [ ] OAuth ログイン画面
- [ ] 左サイド：タスクリスト一覧（追加/リネーム/削除）
- [ ] メイン：選択中リストのタスク行（チェックボックスで完了、ドラッグで並び替え、サブタスク対応）
- [ ] タスクディテールパネル：title / notes / `duration_min` / `weight` / `priority` / `deadline` を編集
- [ ] クイック追加（タイトルだけで即追加 → 詳細は後で）

**スケジューラ機能：**
- [ ] 「最適化を実行」ボタン → 結果プレビュー画面（カレンダー風表示）
- [ ] 結果の手動編集（特定タスクをピン留め / 除外）
- [ ] 「カレンダーに反映」ボタン
- [ ] 設定画面（最適化の重みパラメータ調整、作業可能時間帯、location_buffer）

- [ ] **マイルストーン**：UI から全機能が叩ける + Google ToDo を開かなくても日々のタスク管理が完結する

### Phase 7（任意）：行動学習・改善
- [ ] 過去の実績から weight / energy_score を自動学習
- [ ] タスク数増加で MIP が遅くなったら GA（DEAP）への切り替え検討

---

## 5. 設計上の重要判断ポイント（要レビュー）

レビュー時に判断してほしい論点です。

### 5.1 タスクの「重さ」と「優先度」の入力UX 〔解消済み〕
本アプリを Google ToDo の代替（自作タスク管理）にしたことで論点解消。
- `duration_min` / `weight` / `priority` / `deadline` はすべてアプリのネイティブフィールドとして DB スキーマに持つ
- UI 側は Google ToDo を模倣しつつ、タスク作成/編集モーダルにこれらの入力欄を素直に追加する
- 入力負荷を下げるため、`duration_min` / `weight` には **既定値**（例：60分・0.5）を設定し、未入力でも最適化が動くようにする

### 5.2 OAuth トークンの保存
- 個人利用前提なので、SQLite に格納（refresh_token は環境変数のキーで簡易暗号化）
- ローカル動作のみであれば `~/.config/task-scheduler/credentials.json` でも実害はない
- **推奨**：SQLite に保存（DB を1ヶ所に集約したいので）

### 5.3 MVP のスコープ
- 「自分一人が使う」レベルのものか、「他人にも配布する」レベルか
- 前者なら認証画面・設定画面の作り込みは最小化できる
- **推奨**：まずは自分専用 → 動いてから整える

### 5.4 タイムゾーン
- 全データを UTC で保存し、表示時に Asia/Tokyo に変換するのが定石
- Google API は RFC3339 形式で TZ 付きで返ってくるので素直に扱える

### 5.5 PuLP vs OR-Tools
- PuLP (CBC) は学術用途・小規模向き、OR-Tools (CP-SAT) は実務での実績豊富
- 設計書では PuLP + OR-Tools の併記だが、**最初は PuLP のみで十分**
- §6 の `SolverBackend` 抽象を経由するので、後から OR-Tools 実装を追加しても他コードへの影響なし

---

## 6. MIP 最適化エンジンの拡張可能設計（中核）

> プロジェクトで唯一「試行錯誤が前提」の領域。制約条件は実運用してから追加・修正されることが確実なので、**後から書き換えやすい構造**を最初から作る。

### 6.1 設計方針

1. **制約と目的関数は1クラス1ファイル**：追加・削除・無効化が独立して行える
2. **ソルバーは抽象越し**：PuLP → OR-Tools への乗り換えがオーケストレータ層に波及しない
3. **設定はコード外**：重みパラメータ・有効/無効フラグは `OptimizerConfig`（Pydantic）で外出しし、DB / YAML 経由で変更可能
4. **入出力をスナップショット化**：同じ入力に対して異なる設定で再実行・比較できる
5. **小さなテストシナリオ集**：fixtures として小〜中規模 JSON を持ち、変更時は全シナリオで挙動回帰を確認

### 6.2 コア抽象

```python
# domain.py — 純粋なデータ型（ソルバー非依存）
@dataclass(frozen=True)
class Task:
    id: str
    title: str
    duration_min: int
    deadline: datetime
    priority: int       # 1〜5
    weight: float       # 0〜1（タスクの重さ）

@dataclass(frozen=True)
class Slot:
    id: str
    start: datetime
    duration_min: int
    energy_score: float
    allowed_weight_max: float

@dataclass(frozen=True)
class Assignment:
    task_id: str
    slot_id: str
    score_breakdown: dict[str, float]  # どの目的関数項がどう寄与したか
```

```python
# backend/base.py — ソルバー抽象
class SolverBackend(ABC):
    @abstractmethod
    def add_binary_var(self, name: str) -> Any: ...
    @abstractmethod
    def add_constraint(self, expr: Any, name: str) -> None: ...
    @abstractmethod
    def add_to_objective(self, expr: Any) -> None: ...
    @abstractmethod
    def solve(self, time_limit_sec: int) -> SolveStatus: ...
    @abstractmethod
    def value(self, var: Any) -> float: ...
```

```python
# constraints/base.py
class Constraint(ABC):
    name: str
    @abstractmethod
    def apply(self, ctx: BuildContext) -> None: ...

# objectives/base.py
class ObjectiveTerm(ABC):
    name: str
    weight: float
    @abstractmethod
    def contribute(self, ctx: BuildContext) -> None: ...
```

`BuildContext` は tasks / slots / 決定変数 `x[i][j]` / SolverBackend を保持し、各制約・目的関数項はこの ctx を介してソルバーに書き込む。

### 6.3 オーケストレータ

```python
# orchestrator.py
class Optimizer:
    def __init__(
        self,
        config: OptimizerConfig,
        constraints: list[Constraint],
        objectives: list[ObjectiveTerm],
        backend_factory: Callable[[], SolverBackend],
    ): ...

    def solve(self, tasks: list[Task], slots: list[Slot]) -> SolveResult:
        ctx = BuildContext(tasks, slots, self.backend_factory())
        ctx.create_decision_variables()
        for c in self._enabled(self.constraints):
            c.apply(ctx)
        for o in self._enabled(self.objectives):
            o.contribute(ctx)
        status = ctx.backend.solve(self.config.time_limit_sec)
        return self._extract(ctx, status)
```

**ポイント**：
- 制約や目的関数を追加するときは、新しいクラスを1つ書いて `constraints` / `objectives` リストに渡すだけ
- 既存ロジックには一切触らない
- config で `enabled_constraints` / `enabled_objectives` を切り替えられるので、A/B 比較が容易

### 6.4 OptimizerConfig（外部化される設定）

```python
class OptimizerConfig(BaseModel):
    # 目的関数の重み
    weights: dict[str, float] = {
        "priority": 1.0,
        "urgency": 1.0,
        "energy_match": 1.5,
        "overdue_penalty": 10.0,
    }
    # ON/OFF（実験用）
    enabled_constraints: set[str] = {
        "one_slot_per_task", "slot_capacity",
        "deadline", "calendar_conflict",
    }
    enabled_objectives: set[str] = {
        "priority", "urgency", "energy_match", "overdue_penalty",
    }
    time_limit_sec: int = 30
    backend: Literal["pulp", "ortools"] = "pulp"
```

UI の設定画面・DB から自由にいじれるようにする。コード変更なしでチューニング可能。

### 6.5 スナップショット & 再現実験

```python
# snapshot.py
class Snapshot(BaseModel):
    id: str
    created_at: datetime
    tasks: list[Task]
    slots: list[Slot]
    config: OptimizerConfig
    result: SolveResult | None
```

- `/optimize` を叩くたびに DB に Snapshot を保存
- CLI コマンド `python -m optimizer replay <snapshot_id> --config new_config.yaml` で過去入力を別設定で再実行
- 「制約を変えたら結果がどう変わるか」を即座に比較できる

### 6.6 テストシナリオ集

`tests/optimizer/scenarios/` に JSON で配置：

```
scenarios/
├── trivial.json           # タスク3個 / スロット5個
├── deadline_pressure.json # 締切ギリギリのタスクが混ざる
├── energy_mismatch.json   # 重いタスクと軽いスロットの組み合わせ
├── overcapacity.json      # 全タスクは入りきらない
└── realistic_week.json    # 1週間分の現実的なケース
```

各シナリオに「期待される性質」（例：締切超過のタスクは存在しない、最重要タスクは必ず配置される、など）を assertion で書く。
**制約や目的関数を変更したら、このシナリオ集で全件パスすることを最低条件にする。**

### 6.7 拡張シナリオ（あとで追加されそうな制約）

設計上、以下を追加する場合も既存コードへの影響は最小にしたい：

| 追加されそうな制約 | 実装イメージ |
|---|---|
| 同じ日に同種タスクを集中させない | `SameDayDispersionConstraint`（ソフト制約 → 目的関数項として） |
| 連続作業時間に上限 | `ConsecutiveWorkLimitConstraint` |
| 朝型/夜型の好み | `TimeOfDayPreferenceObjective` |
| タスク間の依存関係 | `DependencyConstraint`（A が終わるまで B を置かない） |
| 通学日は午前を確保 | `MorningReservationConstraint` |
| 食事時間の確保 | `MealTimeBlockConstraint` |

**いずれもクラス1個追加 + リスト追加で対応可能**。これが本設計の狙い。

### 6.8 性能・MIPが解けない場合のフォールバック

- まず `time_limit_sec` を設定して、時間内に最良解が見つからなければ準最適解を返す
- それでもダメなら、ハード制約をソフト制約（目的関数のペナルティ項）に降格させる仕組みを config で持つ
- スロット数 × タスク数が爆発したら、対象期間を週単位に分割して逐次最適化

---

## 7. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| Google OAuth の verification 申請 | 公開時に必要・時間かかる | 個人利用なら test user 登録のみで OK |
| MIP の解が出ない / 遅い | 機能停止 | 制約のソフト化、タイムリミット設定（PuLP の `timeLimit`） |
| 日タイプ判定の精度 | 配置の質が下がる | 最初はルールベース、後にユーザーが手動で日タイプ上書き可能に |
| 重みパラメータのチューニング | UX 悪化 | デフォルト値 + 設定画面でスライダー調整可能に |
| Google API のレート制限 | 同期失敗 | 取得結果をキャッシュ、エラー時は指数バックオフ |
| 将来のクラウド・モバイル移行コスト | 後で大改修になりうる | §8 の方針で設計初期からロックインを避ける |

---

## 8. 将来のクラウド化・モバイル対応（必須ではない / 念頭に置く）

> 現時点では個人ローカル利用を前提にしているが、いずれクラウドホスティング + モバイル対応に移行する可能性がある。
> **今すぐ実装しない。ただし、ローカル前提のロックインを生む設計判断を避ける**ことだけは MVP 段階から守る。

### 8.1 移行を見据えた現時点の設計指針

各レイヤーで「将来困らない最低限」を守る。実装コストはほぼ増えない。

| レイヤー | 守るべきこと | 避けること |
|---|---|---|
| **DB** | SQLAlchemy 抽象を介して使う。`user_id` カラムを最初からテーブルに持つ（値は当面固定） | SQLite 固有の機能（`PRAGMA` 依存の挙動、動的型付け前提のスキーマ）に依存しない |
| **認証** | OAuth 認可コード ＋ refresh_token を DB に保存する構造にしておく | `InstalledAppFlow` で得たクレデンシャルをファイルに直書きしない（ハードコード禁止） |
| **API** | 完全ステートレスな REST 設計。リクエストごとに `user_id` でアクセス制御できる構造 | サーバー側にリクエストをまたぐセッション状態を持たない |
| **時刻** | すべて UTC + TZ 情報で保存、クライアント側で表示変換 | サーバーローカル TZ 依存の処理を書かない |
| **設定** | 環境変数経由（`pydantic-settings`）。秘密情報は `.env` | `~/Documents/...` のようなローカル絶対パスをコードに書かない |
| **フロントエンド** | API クライアント層を `frontend/src/api/` に分離、型定義を独立モジュール化 | UI コンポーネントから直接 fetch しない |
| **ファイル保存** | 画像・添付などは扱わないので問題なし。今後発生したら最初から S3 互換抽象（boto3 + minio）を経由 | サーバーローカルディスクに直接書かない |
| **長時間ジョブ** | MVP では同期処理で十分。重くなったら Celery / RQ に切り出せる構造（サービス関数を純粋に保つ） | リクエストハンドラー内に長い処理ロジックを直書きしない |

### 8.2 想定される移行ロードマップ（将来）

実際にクラウド化したくなったときの順序。MVP では着手しない。

#### Step A：バックエンドのクラウドホスティング（半日〜1日）
- ホスト候補：**Fly.io** / **Cloud Run** / **Railway** のいずれか（個人開発で扱いやすい順）
- DB を SQLite → 管理 PostgreSQL（Fly Postgres / Cloud SQL / Neon / Supabase）に切り替え
  - SQLAlchemy なら接続文字列の変更 + Alembic マイグレーション再適用で済む
- 環境変数で接続情報を渡す
- OAuth リダイレクト URI を本番ドメインに登録

#### Step B：認証フローを Web 対応へ（1〜2日）
- `InstalledAppFlow` → `Flow` (Web flow) に変更
- 認証成功時にアプリ独自のセッショントークン（JWT または Cookie）を発行
- マルチユーザー対応：すでに `user_id` カラムがあるので、トークン発行時に作成 / 紐付け

#### Step C：PWA 化（1日）
- 既存 React アプリに manifest と Service Worker を追加するだけ
- ホーム画面追加で「アプリっぽく」使える、最低限のオフライン耐性も確保
- 多くの場合これで「モバイル対応」要件は満たせる

#### Step D：ネイティブモバイルアプリ（必要なら）
- **選択肢1：Capacitor** — 既存 React Web をそのままネイティブ化。改修最小
- **選択肢2：React Native + Expo** — UI を作り直すが、ネイティブ機能（プッシュ通知）にフルアクセス
- API クライアント層を `frontend/src/api/` に分離してあるので、別プロジェクトから import できる
- プッシュ通知（「次のタスクが10分後に始まる」など）はモバイル化の主目的になり得る

### 8.3 MVP では明示的に「やらない」こと

- マルチユーザー UI（ログイン画面・ユーザー管理）→ シングルユーザー固定で OK
- JWT 発行・リフレッシュ機構 → 単一ユーザー前提で簡略化して OK
- レート制限・スロットリング → 不要
- セッション暗号化キーローテーション → 不要

### 8.4 「あとで困ること」リスト（覚書）

将来クラウド化するときに対処が必要になりそうな点。実装はしないが、頭に入れて開発する。

- カレンダーへの書き込みは Google API 直叩きなので、サーバー化してもクライアントごとに OAuth 認可が必要（マルチユーザー化時にユーザー単位でトークン管理）
- 最適化処理が長くなるとリクエストタイムアウトに当たる → 非同期ジョブに切り出す前提でサービス関数の純粋性を保つ
- スナップショット（§6.5）の保存先 → SQLite 内に持つ前提だが、量が増えるなら BLOB ストレージへの抽象化を視野に
- 通知機能を入れるならイベント駆動の仕組み（cron + キュー）が必要に

---

## 9. 次のアクション（このレビュー完了後）

レビューで OK が出たら、以下の順で着手：

1. Phase 0 の環境構築（プロジェクト雛形 + SQLite 初期化）
2. Google Cloud Console 設定（OAuth クライアント ID 作成）
3. Phase 1 から順に実装

レビュー時に修正点があれば、本ドキュメントを更新してから着手します。
