# Phase 3：MIP 最適化エンジン 詳細設計

> 対象期間：5〜7 日（試行錯誤を見込んで余裕）
> ゴール：「タスク一覧 + スロット一覧 → どのタスクをどのスロットにいつ置くか」を MIP で解くエンジン。
> 参照：`project_plan.md` §6（拡張可能設計の正本）、`task_scheduler_design.md`（定式化原案）、`docs/phase2_design.md`（入力データ）

---

## 0. このフェーズの位置づけ

**やること：**
- ドメイン型（Task / Slot / Assignment）の確定
- ソルバー抽象（PuLP 実装）
- ハード制約（5 種類）を1クラス1ファイルで実装
- 目的関数項（4 種類）を1クラス1ファイルで実装
- `Optimizer` オーケストレータ（config から組み立てて solve）
- スナップショット保存・再生機構
- テストシナリオ集（5〜10 個）
- `/optimize` エンドポイント

**やらないこと：**
- カレンダーへの書き込み（Phase 5）
- 実績学習・行動から重みを推定（Phase 7）
- OR-Tools 実装（PuLP で性能不足になったら追加。`SolverBackend` 抽象越しなので影響最小）
- フロント UI（Phase 6）

**Phase 2 との接続：**

```
[タスク CRUD]    ─┐
                  ├─→ Optimizer.solve(tasks, slots, config) → SolveResult
[スロット生成] ──┘                                                  │
                                                                  ├─→ Snapshot 保存
                                                                  └─→ /optimize レスポンス
```

---

## 1. 主要設計判断（Phase 3 の前提）

| 判断 | 値 | 理由 |
|---|---|---|
| **タスク分割** | OK（1 タスクが N スロットに分散可） | 長いタスクが入らない問題を回避。代わりに最小断片サイズで「細切れ過ぎ」を防ぐ |
| **未配置許容** | OK（ソフト制約 + ペナルティ） | スケジューラとして自然。"infeasible" でユーザーが詰むのを避ける |
| **断片の最小サイズ** | 30 分（既定）、`OptimizerConfig` で変更可 | 5 分断片を作らない |
| **断片の上限数** | 既定 5 個 / タスク、設定可 | 1 タスクが 10 個に分かれると現実的に集中できないため |
| **スロット内位置** | 抽象化（断片単位、開始位置は post-hoc） | MIP の決定変数を「分単位」だけにすることで小さく保つ |
| **ソルバー** | PuLP（CBC バックエンド） | `SolverBackend` 抽象越しなので OR-Tools 等への切替容易 |
| **タイムリミット** | 既定 30 秒、設定可 | 解が出ない場合は最良の準最適解を返す |

---

## 2. MIP の定式化

### 2.1 集合・パラメータ

```
I = {タスク 1, ..., n}
J = {スロット 1, ..., m}

task_i.duration_min     : int      タスクの所要時間（分）
task_i.weight           : float    タスクの重さ 0..1
task_i.priority         : int      1..5
task_i.deadline         : datetime 締切（UTC）

slot_j.start            : datetime UTC
slot_j.duration_min     : int      スロット長
slot_j.energy_score     : float    0..1
slot_j.allowed_weight_max : float  0..1
```

### 2.2 決定変数

```
z[i]    ∈ {0, 1}     タスク i が完全に配置されたか
x[i][j] ∈ Z, ≥ 0     タスク i をスロット j に何分置くか
y[i][j] ∈ {0, 1}     タスク i がスロット j に何らかの断片を持つか（最小断片制約用）
```

### 2.3 ハード制約（必ず守る）

**(C1) AllOrNothing**：タスクは「全部置く」か「全く置かない」かのどちらか。
```
∀i:  Σ_j x[i][j] = task_i.duration_min × z[i]
```

**(C2) SlotCapacity**：1 スロットの合計時間はスロット長を超えない。
```
∀j:  Σ_i x[i][j] ≤ slot_j.duration_min
```

**(C3) Deadline**：締切後のスロットには配置しない。
```
∀i,j s.t. slot_j.start + slot_j.duration ≥ task_i.deadline:  x[i][j] = 0
```

**(C4) WeightCap**：スロットの `allowed_weight_max` を超える重さのタスクは置かない。
```
∀i,j s.t. task_i.weight > slot_j.allowed_weight_max:  x[i][j] = 0
```

**(C5) MinFragmentSize**：1 つの断片は最小サイズ未満にしない。
```
∀i,j:  min_fragment_min × y[i][j] ≤ x[i][j] ≤ slot_j.duration × y[i][j]
```
（x[i][j] が正なら y[i][j]=1 になり、その断片は min_fragment_min 以上）

**(C6) MaxFragmentsPerTask**（任意）：1 タスクの分割上限。
```
∀i:  Σ_j y[i][j] ≤ max_fragments_per_task
```

「カレンダー競合」は **Phase 2 のスロット生成時点で既に除外済み**（既存予定はスロットに含まれない）。Phase 3 では追加の制約は不要。

### 2.4 目的関数（最大化）

```
Maximize:
    w_priority × Σ_i z[i] × priority_score[i]
  + w_urgency  × Σ_i z[i] × urgency_score[i]
  + w_energy   × Σ_{i,j} energy_match[i][j] × x[i][j]
  - w_unassigned × Σ_i priority[i] × (1 - z[i])
```

| 項 | 計算 | 意味 |
|---|---|---|
| `priority_score[i]` | `task_i.priority / 5` | 高優先度ほど加点 |
| `urgency_score[i]` | `1 / (days_until_deadline + 1)` | 締切近いほど加点 |
| `energy_match[i][j]` | `1 - abs(task_i.weight - slot_j.energy_score)` | weight と energy が近いほど加点。**分単位で重み付け**するので長く置くほど効く |
| 未配置ペナルティ | `priority[i] × (1 - z[i])` | 高優先度の未配置を強く避ける |

### 2.5 既定の重み

```python
weights = {
    "priority":           1.0,
    "urgency":            1.0,
    "energy_match":       0.05,    # x[i][j] は分単位なので 1/分のスケールに合わせる
    "unassigned_penalty": 5.0,
}
```

キー名は `ObjectiveTerm.name` と一致（priority / urgency / energy_match / unassigned_penalty）。
`OptimizerConfig` で変更可能。

---

## 3. アーキテクチャ（`project_plan.md` §6 の正本に従う）

### 3.1 ディレクトリ構成

```
backend/app/services/optimizer/
├── domain.py                   # Task / Slot / Assignment / SolveResult
├── config.py                   # OptimizerConfig (Pydantic)
├── backend/
│   ├── base.py                 # SolverBackend ABC
│   └── pulp_backend.py         # PuLP 実装
├── constraints/
│   ├── base.py                 # Constraint ABC
│   ├── all_or_nothing.py       # C1
│   ├── slot_capacity.py        # C2
│   ├── deadline.py             # C3
│   ├── weight_cap.py           # C4
│   ├── min_fragment_size.py    # C5
│   └── max_fragments.py        # C6（任意）
├── objectives/
│   ├── base.py                 # ObjectiveTerm ABC
│   ├── priority.py
│   ├── urgency.py
│   ├── energy_match.py
│   └── unassigned_penalty.py
├── orchestrator.py             # Optimizer クラス
└── snapshot.py                 # Snapshot dataclass + save/load
```

### 3.2 ドメイン型

```python
@dataclass(frozen=True)
class OptimizerTask:
    id: str
    title: str
    duration_min: int
    deadline: datetime           # UTC, tz-aware
    priority: int
    weight: float

@dataclass(frozen=True)
class OptimizerSlot:
    id: str
    start: datetime              # UTC
    duration_min: int
    energy_score: float
    allowed_weight_max: float
    day_type: str

@dataclass(frozen=True)
class Fragment:
    """1 タスクの 1 スロット内の断片。"""
    task_id: str
    slot_id: str
    start: datetime              # スロット内の開始時刻
    duration_min: int
    score_breakdown: dict[str, float]

@dataclass(frozen=True)
class TaskAssignment:
    """1 タスクの全断片。配置されたなら fragments が >= 1 個。"""
    task_id: str
    fragments: tuple[Fragment, ...]    # 空 = 未配置
    total_assigned_min: int

@dataclass(frozen=True)
class SolveResult:
    status: Literal["optimal", "feasible", "infeasible", "timed_out", "error"]
    objective_value: float | None
    assignments: tuple[TaskAssignment, ...]
    unassigned_task_ids: tuple[str, ...]
    solve_time_sec: float
```

### 3.3 抽象ベースクラス

```python
# backend/base.py
class SolverBackend(ABC):
    @abstractmethod
    def add_binary_var(self, name: str) -> Any: ...
    @abstractmethod
    def add_int_var(self, name: str, lb: int, ub: int) -> Any: ...
    @abstractmethod
    def add_constraint(self, expr: Any, name: str) -> None: ...
    @abstractmethod
    def add_to_objective(self, expr: Any) -> None: ...
    @abstractmethod
    def solve(self, time_limit_sec: int) -> SolveStatus: ...
    @abstractmethod
    def value(self, var: Any) -> float: ...

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

`BuildContext` は tasks / slots / 決定変数群 / `SolverBackend` を保持し、各制約・目的関数項はここから参照する。

```python
@dataclass
class BuildContext:
    tasks: list[OptimizerTask]
    slots: list[OptimizerSlot]
    backend: SolverBackend
    config: OptimizerConfig
    # 決定変数（インデックスで参照）
    z: dict[str, Any]                          # z[task_id]
    x: dict[tuple[str, str], Any]              # x[task_id, slot_id]
    y: dict[tuple[str, str], Any]              # y[task_id, slot_id]
```

### 3.4 オーケストレータ

```python
class Optimizer:
    def __init__(
        self,
        config: OptimizerConfig,
        constraints: list[Constraint],
        objectives: list[ObjectiveTerm],
        backend_factory: Callable[[], SolverBackend],
    ): ...

    def solve(
        self, tasks: list[OptimizerTask], slots: list[OptimizerSlot]
    ) -> SolveResult:
        ctx = BuildContext(tasks, slots, self.backend_factory(), self.config)
        ctx.create_decision_variables()
        for c in self._enabled(self.constraints):
            c.apply(ctx)
        for o in self._enabled(self.objectives):
            o.contribute(ctx)
        status = ctx.backend.solve(self.config.time_limit_sec)
        return self._extract(ctx, status)
```

**ポイント**：
- 制約や目的関数を追加するときはクラスを 1 つ書いて `constraints` / `objectives` リストに渡すだけ
- 既存ロジックには触らない
- `OptimizerConfig.enabled_constraints` / `enabled_objectives` で動的に切替

### 3.5 OptimizerConfig

```python
class OptimizerConfig(BaseModel):
    weights: dict[str, float] = {
        "priority": 1.0,
        "urgency": 1.0,
        "energy_match": 0.05,
        "unassigned_penalty": 5.0,
    }
    enabled_constraints: set[str] = {
        "all_or_nothing", "slot_capacity",
        "deadline", "weight_cap",
        "min_fragment_size",
    }
    enabled_objectives: set[str] = {
        "priority", "urgency", "energy_match", "unassigned_penalty",
    }
    min_fragment_min: int = 30
    max_fragments_per_task: int | None = 5
    time_limit_sec: int = 30
    backend: Literal["pulp"] = "pulp"   # 将来 "ortools" を追加
```

`user_settings` テーブルに追加するか、独立した `optimizer_config` テーブルを設けるかは Phase 3 着手時に決める（小さい違いなので）。

---

## 4. スナップショット & 再現実験

### 4.1 用途

- 「設定 A で解いた結果」と「設定 B で解いた結果」を比較
- バグ報告（再現入力をすぐ得られる）
- 過去の最適化を後でリプレイして「あの時 weight をいじっていたらどうなったか」を見る

### 4.2 スキーマ

`optimizer_snapshots` テーブル（Phase 3 で migration 0006 として追加）:

| カラム | 型 | 備考 |
|---|---|---|
| `id` | TEXT (UUID) | PK |
| `user_id` | TEXT FK | |
| `created_at` | DATETIME | |
| `tasks_json` | JSON | OptimizerTask 配列 |
| `slots_json` | JSON | OptimizerSlot 配列 |
| `config_json` | JSON | OptimizerConfig |
| `result_json` | JSON | SolveResult（null = 失敗） |
| `note` | TEXT | 任意のメモ |

### 4.3 API / CLI

```
POST /optimize                         → 実行 + Snapshot 保存
GET  /optimizer/snapshots              → 一覧
GET  /optimizer/snapshots/{id}         → 単件取得
POST /optimizer/snapshots/{id}/replay  → 同じ入力 + 別 config で再実行
```

CLI 補助（`uv run python -m app.cli optimizer replay <id> --config new.yaml`）も任意で。

---

## 5. API エンドポイント

### 5.1 `POST /optimize`

**リクエスト：**
```json
{
  "start": "2026-05-11T00:00:00+09:00",
  "end": "2026-05-17T23:59:59+09:00",
  "list_ids": ["勉強リスト UUID"],
  "task_ids": ["特定タスク UUID"],
  "config_overrides": {
    "weights": {"unassigned": 10.0},
    "min_fragment_min": 45
  }
}
```

| フィールド | 必須 | 既定 | 用途 |
|---|---|---|---|
| `start` / `end` | Yes | — | スロット取得・締切フィルタの期間 |
| `list_ids` | No | 全リスト | 対象タスクをリストで絞る |
| `task_ids` | No | 全タスク | より細かく対象を絞る |
| `config_overrides` | No | `{}` | 既定の `OptimizerConfig` を部分上書き |

**レスポンス：**
```json
{
  "status": "optimal",
  "objective_value": 12.45,
  "snapshot_id": "abc123...",
  "assignments": [
    {
      "task_id": "...",
      "task_title": "物性化学レポート",
      "fragments": [
        {"slot_id": "slot-2026-05-12T03:10:00Z-120", "start": "2026-05-12T03:10:00Z", "duration_min": 90}
      ],
      "total_assigned_min": 90
    }
  ],
  "unassigned": [
    {"task_id": "...", "title": "宇宙物理レポート", "reason": "no fitting slot before deadline"}
  ],
  "solve_time_sec": 1.23
}
```

### 5.2 関連エンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| `GET` | `/optimizer/snapshots` | スナップショット一覧 |
| `GET` | `/optimizer/snapshots/{id}` | 単件 |
| `POST` | `/optimizer/snapshots/{id}/replay` | 再実行（body で `config_overrides` 渡せる） |
| `DELETE` | `/optimizer/snapshots/{id}` | 削除 |

### 5.3 エラー

| HTTP | error コード | 状況 |
|---|---|---|
| 400 | `validation_error` | 期間不正・config 不正 |
| 401 | `not_authenticated` / `reauth_required` | スロット生成段階で認証必要 |
| 422 | `no_tasks` / `no_slots` | 対象タスク or スロットが空 |
| 504 | `solver_timeout` | タイムリミット内に最良解が見つからなかった（最良の準最適解は返す） |

---

## 6. テストシナリオ集

`backend/tests/optimizer/scenarios/*.json` に固定入力 + 期待性質を置く。
**制約・目的関数を変更したら全件 pass を最低条件とする**（[memory: feedback_design_focus](../.claude/projects/-Users-aokitenju-task-scheduler/memory/feedback_design_focus.md) の方針）。

| シナリオ | 内容 | 期待性質 |
|---|---|---|
| `trivial.json` | タスク 3 / スロット 5 | 全タスク配置・締切超過なし |
| `deadline_pressure.json` | 締切間際タスク混在 | 締切間際が優先配置 |
| `energy_mismatch.json` | 重いタスク × 軽いスロットしかない | weight_cap で配置不可 → 未配置 |
| `overcapacity.json` | 全タスクは入りきらない | 高優先度から残る |
| `task_split.json` | 180 分タスク × 60 分スロット x 3 | 60+60+60 で配置 |
| `min_fragment.json` | 残スロットが 20 分しかない | 最小断片 30 分 → 未配置 |
| `realistic_week.json` | 1 週間の現実的なケース | 締切超過なし、最重要タスク必ず配置 |

各シナリオの `expected.json` に「assert すべき条件」を JSON で書き、テスト側で評価する形式（コードを増やさず追加できるように）。

```json
{
  "expectations": [
    {"type": "all_assigned", "task_ids": ["t1", "t2", "t3"]},
    {"type": "no_deadline_violation"},
    {"type": "task_completed_via_fragments", "task_id": "t_big", "min_fragments": 2}
  ]
}
```

---

## 7. 実装順（おすすめ）

1. `domain.py` + `config.py`（Pydantic）
2. `backend/base.py` ABC + `pulp_backend.py` 最小実装（add_binary_var / add_constraint / solve / value のみ）
3. `BuildContext` + `Optimizer` の骨組み（制約 0 個でも solve できる状態）
4. `constraints/all_or_nothing.py` + テスト 1 件
5. `constraints/slot_capacity.py` + テスト
6. `constraints/deadline.py` + テスト
7. `constraints/weight_cap.py` + テスト
8. `constraints/min_fragment_size.py` + テスト
9. `objectives/priority.py` + テスト
10. `objectives/urgency.py`
11. `objectives/energy_match.py`
12. `objectives/unassigned_penalty.py`
13. シナリオテスト集（7 シナリオ）
14. `snapshot.py` + Alembic 0006（`optimizer_snapshots` テーブル）
15. `api/optimize.py`（`/optimize` + `/optimizer/snapshots`）
16. `main.py` 配線
17. 実機検証（自分のタスクで `/optimize` 叩く）
18. ドキュメント追加

各ステップで「動く状態」を保つ。制約を 1 個追加してテストで確認 → 次の制約、というサイクル。

---

## 8. 動作確認シナリオ

```bash
# 1. サーバー起動
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 2. タスク投入（実在のものを 5-10 個）
curl -X POST http://localhost:8000/lists -H "Content-Type: application/json" \
  -d '{"title":"今学期"}'
LIST_ID=...
curl -X POST http://localhost:8000/lists/$LIST_ID/tasks -H "Content-Type: application/json" \
  -d '{"title":"物性化学レポート","duration_min":180,"weight":0.8,"priority":4,
       "deadline":"2026-05-20T23:59:59+09:00"}'
# ... 残り 4-9 個

# 3. 最適化実行
curl -X POST http://localhost:8000/optimize -H "Content-Type: application/json" \
  -d '{"start":"2026-05-11T00:00:00+09:00","end":"2026-05-17T23:59:59+09:00"}' \
  | python -m json.tool

# 4. 結果に違和感が出たら config を弄って再実行
curl -X POST http://localhost:8000/optimize -H "Content-Type: application/json" \
  -d '{"start":"2026-05-11T00:00:00+09:00","end":"2026-05-17T23:59:59+09:00",
       "config_overrides":{"weights":{"energy":0.1}}}' \
  | python -m json.tool

# 5. スナップショット確認
curl http://localhost:8000/optimizer/snapshots | python -m json.tool

# 6. 過去入力を別 config で再実行
curl -X POST http://localhost:8000/optimizer/snapshots/<ID>/replay \
  -H "Content-Type: application/json" \
  -d '{"config_overrides":{"min_fragment_min":60}}'
```

---

## 9. このフェーズで残す未解決事項（Phase 4+）

- **断片の順序制約**：「フラグメント 1 → フラグメント 2 の順で」が必要なら追加制約 1 個で対応可。MVP では順序自由
- **タスク間依存**：「A 終わるまで B を始めない」は `DependencyConstraint` として後付け（[project_plan.md §6.7](../project_plan.md) の拡張一覧通り）
- **同種タスクの分散**：「同じ日に同種タスクを集中させない」は `SameDayDispersionConstraint` で。当面なし
- **連続作業時間上限**：「3 時間連続したら最低 30 分休憩」は `ConsecutiveWorkLimitConstraint` で。Phase 4+
- **時間帯重み付け**：1 日内で朝は集中・夜は緩い、のような時間帯ごとの energy 変動。Phase 2 では「日単位のみ」で割り切っているので、必要が出たら Phase 4+ で `slot_j.energy_score` を時間帯依存に拡張（`user_settings.time_curve` を導入してスロット生成時に乗じる）
- **OR-Tools 切替**：PuLP で 30 秒で解けない規模になったら検討。`SolverBackend` 抽象を作っているので影響最小

---

## 10. Phase 3 完了の判定

- [ ] PuLP バックエンドで小〜中規模シナリオ（タスク 10 / スロット 50）が 30 秒以内に解ける
- [ ] 7 シナリオが全 pass
- [ ] 制約・目的関数を 1 つ追加するだけで動作する（仕組みの確認）
- [ ] スナップショットが保存され、別 config で replay できる
- [ ] 実カレンダー × 実タスクで `/optimize` を叩いて、それっぽい結果が返ってくる

---

## 11. 設計の核：何が「不確実」で何が「確定」か

[memory: feedback_design_focus](../.claude/projects/-Users-aokitenju-task-scheduler/memory/feedback_design_focus.md) に従って:

**確定（普通に書いて良い）:**
- ドメイン型定義
- ソルバー抽象（インターフェース）
- スナップショット永続化
- API エンドポイント

**不確実（試行錯誤前提、差し替え可能に作る）:**
- 各制約・目的関数の数式 → 1 ファイル 1 クラスで隔離
- 重みパラメータ → `OptimizerConfig` で外出し、`config_overrides` で実行毎に上書き可
- どの制約を有効にするか → `enabled_constraints` で動的に切替
- ソルバー実装 → `SolverBackend` 抽象越しなので OR-Tools 等への乗り換え可

**従って:**
- Phase 3 着手後、実機で結果を見て「unassigned ペナルティが緩すぎる」と思ったら **コード触らず** に `config_overrides` で調整 → 同じ Snapshot で replay → 比較
- 「priority より urgency を優先したい」と思ったら同上
- 「断片の最小サイズが小さすぎる」と思ったら同上
- 新しい制約（例：「夜遅くは置かない」）を入れたくなったらクラス 1 個追加 + `enabled_constraints` に追加

これにより、**最適化の挙動チューニングは設計→実装→運用のどのフェーズでも、コード変更なしで可能**になる。
