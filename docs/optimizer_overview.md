# 最適化ソルバー 現状まとめ

> 現時点での MIP（Mixed Integer Programming）ソルバー周りのパラメータ・制約・目的関数を一覧化したもの。
> 実装の正本: [`backend/app/services/optimizer/`](../backend/app/services/optimizer/)
>
> 関連:
> - 設計の出発点: [`phase3_design.md`](phase3_design.md)
> - 場所・拘束時間まわりの拡張: [`phase4_design.md`](phase4_design.md)
> - 既定設定（働く時間・場所・day_type）: [`api_cheatsheet.md §4.5`](api_cheatsheet.md)

---

## 1. 概要

ソルバーが解く問題は **タスクをスロットに割り当てる整数計画問題** です。

- **入力**:
  - タスク群（`OptimizerTask`）— 所要時間・優先度・締切・場所制約
  - スロット群（`OptimizerSlot`）— 開始/長さ・エネルギー・上限分・day_type・場所
- **出力**: 各タスクの「どのスロットに何分ずつ入れるか」（複数 fragment 可）
- **目的**: 重み付き目的関数の最大化（優先度・緊急度・エネルギー一致を加点、未配置を減点）
- **ハード制約**: 配置不能な組合せは数式で除外（締切超過・場所不一致など）

実装は **ストラテジ + ファクトリー** で構成され、制約・目的・バックエンドはそれぞれ差し替え可能（[`orchestrator.py`](../backend/app/services/optimizer/orchestrator.py)）。

---

## 2. 決定変数

[`orchestrator.py:_create_decision_variables`](../backend/app/services/optimizer/orchestrator.py)

| 変数 | 種別 | 範囲 | 意味 |
|---|---|---|---|
| `z[i]` | Binary | `{0, 1}` | タスク `i` を配置するか（all-or-nothing） |
| `x[i, j]` | Integer | `0 ≤ x ≤ min(duration_i, duration_j)` | タスク `i` をスロット `j` に何分入れるか |
| `y[i, j]` | Binary | `{0, 1}` | タスク `i` がスロット `j` を使うか（fragment 存在フラグ） |

`y` は「`x > 0` のとき必ず `y = 1`」を強制するための補助変数で、断片の個数や最小サイズの制御に使う。

---

## 3. ハード制約

既定で全 7 件が有効（[`config.py:DEFAULT_ENABLED_CONSTRAINTS`](../backend/app/services/optimizer/config.py)）。`config_overrides.enabled_constraints` で個別に無効化可能。

### 3.1 `all_or_nothing` — タスクは全部入れるか全く入れないか

ファイル: [`constraints/all_or_nothing.py`](../backend/app/services/optimizer/constraints/all_or_nothing.py)

```
Σⱼ x[i, j] = duration_i * z[i]    （各タスク i に対して）
```

部分配置（30 分だけ入れて残り未配置）を禁止する。半端な配置を防ぐ。

### 3.2 `slot_capacity` — スロットを超えて詰めない

ファイル: [`constraints/slot_capacity.py`](../backend/app/services/optimizer/constraints/slot_capacity.py)

```
Σᵢ x[i, j] ≤ duration_j    （各スロット j に対して）
```

1 スロットに複数タスクを詰めること自体は OK。合計分数だけ制限。

> ⚠️ **抽出時の注意**: 同じスロット内に複数タスクが置かれた場合、`orchestrator._extract_result` が順次オフセット（13:00–14:00 → 14:00–15:00）で並べる。以前はここがバグっていて両方とも `slot.start` から始まる扱いだったが、Phase 5 検証中に修正済み（test_two_tasks_in_one_slot_get_sequential_offsets）。

### 3.3 `deadline` — 締切後のスロットには入れない

ファイル: [`constraints/deadline.py`](../backend/app/services/optimizer/constraints/deadline.py)

```
x[i, j] = 0    （slot_j.end > task_i.deadline のとき）
```

`task.deadline = None` のタスクは制約なし。

### 3.3.1 `force_deadlined` — 締切付きタスクは必ず配置する（絶対条件）

ファイル: [`constraints/force_deadlined.py`](../backend/app/services/optimizer/constraints/force_deadlined.py)

```
z[i] = 1    （task_i.deadline is not None のとき）
```

`deadline` 制約と組み合わせて「締切付きタスクは締切以内に必ず配置」を**ハード制約として保証**する。重み付けではなく絶対条件で、対象タスクが配置不能なら `unassigned_penalty` を払って未配置にする逃げ道を許さない。

該当タスクが入りきらない場合は MIP が **`infeasible` を返す**。`orchestrator._diagnose_deadline_infeasibility` がどの締切タスクが入らなかったかを `notes` に列挙して返すので、UI 側でユーザーに提示する。

無効化したいときは `config_overrides.enabled_constraints` から `"force_deadlined"` を外す（締切超過時の挙動を「未配置に逃げる」に戻す）。

### 3.4 `duration_cap` — スロット側の上限を超える「長いタスク」を丸ごと除外

ファイル: [`constraints/duration_cap.py`](../backend/app/services/optimizer/constraints/duration_cap.py)

```
x[i, j] = 0    （task_i.duration_min > slot_j.allowed_max_task_duration_min のとき）
```

例: heavy_day（`allowed_max_task_duration_min = 90`）には所要 4 時間のタスクは入れない。分割してでも入れない（「重い日に重いタスクを置かない」セマンティクスを保つ）。

> ⚠️ **infeasible 回避との関係**: optimizer service の retry chain の最終段では、この制約を **last-resort で無効化**する。つまり「heavy_day しか締切前にない 4 時間タスク」のような状況では、duration_cap を外して配置する。意図的に「重い日に重いタスクが入る」結果が出る代わりに、infeasible は回避される（[§9.1 retry chain](#91-infeasible-回避retry-chain) 参照）。

### 3.5 `min_fragment_size` — 短すぎる断片を禁止

ファイル: [`constraints/min_fragment_size.py`](../backend/app/services/optimizer/constraints/min_fragment_size.py)

```
m * y[i, j] ≤ x[i, j] ≤ ub * y[i, j]
```

ここで `m = config.min_fragment_min`（既定 30 分）、`ub = min(slot.duration_min, task.duration_min)`。

- `y = 0` ⇒ `x = 0`（このスロットは使わない）
- `y = 1` ⇒ `x ≥ m`（使うなら最低 `m` 分）

5 分の中途半端な断片が量産されるのを防ぐ。

### 3.6 `max_fragments` — 1 タスクの分割上限

ファイル: [`constraints/max_fragments.py`](../backend/app/services/optimizer/constraints/max_fragments.py)

```
Σⱼ y[i, j] ≤ max_fragments_per_task    （各タスク i に対して）
```

既定 5。`config.max_fragments_per_task = None` で無制限（理論上）。

### 3.7 `location_compatibility` — 場所が合わないスロットには入れない

ファイル: [`constraints/location_compatibility.py`](../backend/app/services/optimizer/constraints/location_compatibility.py)

```
x[i, j] = 0    （task.location と slot.location が両方とも特定の場所で、かつ一致しない とき）
```

判定ルール:
- `task.location` が `None` or `"anywhere"` → 制約なし（どこでも入る）
- `slot.location == "anywhere"` → どんなタスクも入る（自由スロット）
- それ以外は完全一致が必要（`home == home`、`university != office` など）

---

## 4. 目的関数（重み付き和、最大化）

既定で全 4 項目が有効（[`config.py:DEFAULT_ENABLED_OBJECTIVES`](../backend/app/services/optimizer/config.py)）。

```
maximize  Σ (weight * 各項目)
```

### 4.1 `priority` — 高優先度タスクを配置すると加点

ファイル: [`objectives/priority.py`](../backend/app/services/optimizer/objectives/priority.py)

```
+ w_priority * Σᵢ (priority_i / 5) * z[i]
```

priority は 1–5 の整数。5 で最大。配置できた瞬間に効く。

### 4.2 `urgency` — 締切が近いタスクを配置すると加点

ファイル: [`objectives/urgency.py`](../backend/app/services/optimizer/objectives/urgency.py)

```
+ w_urgency * Σᵢ urgency_i * z[i]

urgency_i = 1 / (days_until_deadline + 1)    （deadline が無い場合は 0）
```

「明日締切（1 日）」と「1 週間後（7 日）」の比は `0.5` vs `0.125` で 4 倍差。締切ナシは 0 で項に寄与しない。

### 4.3 `energy_match` — 高エナジーのスロットに分単位で加点

ファイル: [`objectives/energy_match.py`](../backend/app/services/optimizer/objectives/energy_match.py)

```
+ w_energy_match * Σᵢⱼ slot.energy_score * x[i, j]
```

**分単位の積算**なので、長いタスクほど高エナジースロットを取り合う動機が強い。結果として「長いタスク → 高エナジー時間帯」「短いタスク → 余りの低エナジー時間帯」になる。

> Phase 3 までは `(1 - |task.weight - slot.energy|)` の「重さ↔エナジー一致」だったが、`task.weight` を捨てた段階でこの単純な「分 × エナジー」形に縮退。

### 4.4 `keep_together` — 同じタスクは一気にまとめる（断片数 + 日数のソフト減点）

ファイル: [`objectives/keep_together.py`](../backend/app/services/optimizer/objectives/keep_together.py)

```
- w_keep_together_fragments * Σᵢⱼ y[i, j]              （使用スロット数）
- w_keep_together_days      * Σᵢ Σ_date d[i, date]     （タスクが跨ぐ日数）
```

`d[i, date]` は新規の補助 binary：日付 `date` の少なくとも 1 スロットで `y[i, j] = 1` なら 1 になる。連結制約 `d[i, date] ≥ y[i, j]` を各 (i, date, j on date) について追加（最大化では自然に 0 へ落ちる）。

**意図**: ソフト制約。`max_fragments` のハード上限を満たした上で、同じタスクはなるべく:
1. 1 スロット内で完結（最良）
2. 同じ日のスロットにまとめる（次善）
3. 複数日に分散（最悪）

の順で選好される。priority / urgency / energy_match が強く競合する場合は分割も許容（重みが小さいため）。

| 重み | 既定 | 意味 |
|---|---|---|
| `keep_together_fragments` | 1.0 | 1 断片あたりの追加コスト（1 スロット完結なら 1.0、2 スロットなら 2.0...） |
| `keep_together_days` | 2.0 | 1 日あたりの追加コスト（同じ日なら 2.0、2 日に跨ると 4.0...） |

「より一気にやる方向」に強めたければ両方を 2-3 倍にする。完全に無効化したいなら `enabled_objectives` から `"keep_together"` を外す。

> **実装メモ**: 日付グループは UTC date でカット。JST work_hours (9-23:59) はすべて同じ UTC 日付に収まるので JST 日付グループと一致する。タイムゾーンが日跨ぎする運用に拡張する場合は要再検討。

### 4.5 `early_placement` — 締切付きタスクを早めに置くソフト誘導

ファイル: [`objectives/early_placement.py`](../backend/app/services/optimizer/objectives/early_placement.py)

```
+ w_early_placement * Σᵢⱼ (slack_ratio_ij) * x[i, j]

slack_ratio_ij = (deadline_i - slot_j.end) / (deadline_i - reference)
reference = min(s.start for s in slots)   # 最適化範囲内の最早スロット = "now" 相当
```

範囲は `(0, 1]`：最早スロットに置けば 1、締切ギリギリのスロットなら ~0。タスクごとに**自分の締切までの全長**で正規化するので、明日締切のタスクと来週締切のタスクが同じ尺度で「早めに」評価される（クロスタスクの緊急度比較は `urgency` が担当）。

| 重み | 既定 | 意味 |
|---|---|---|
| `early_placement` | 0.02 | 締切付きタスクの per-minute ボーナス。slack_ratio で重み付け |

ソフト：`energy_match` の差（高エナジー時間に置く利得）が大きい場合はそちらが優先される。同等のスロットなら早い方を選ぶ、というレベルの誘導。締切のないタスクには寄与しない（`urgency` と同じく no-op）。

### 4.6 `unassigned_penalty` — 配置できなかったタスクに対する減点

ファイル: [`objectives/unassigned_penalty.py`](../backend/app/services/optimizer/objectives/unassigned_penalty.py)

```
- w_unassigned_penalty * Σᵢ (priority_i / 5) * (1 - z[i])
```

未配置のときに優先度比例で減点。これがあるおかげで、ソルバーは「未配置を作るくらいなら多少エナジー一致が悪くても入れる」を選ぶ。

---

## 5. 設定パラメータ

[`OptimizerConfig`](../backend/app/services/optimizer/config.py) で管理。`/optimize` リクエストの `config_overrides` で部分上書き可。

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `weights.priority` | float | 1.0 | 優先度加点の重み |
| `weights.urgency` | float | 1.0 | 緊急度加点の重み |
| `weights.energy_match` | float | 0.05 | エナジー一致加点の重み（**分単位の積算なので小さめ**） |
| `weights.unassigned_penalty` | float | 5.0 | 未配置減点の重み |
| `weights.keep_together_fragments` | float | 1.0 | 1 タスクが使う断片 1 つあたりの減点（高いほど 1 タスク 1 スロット完結を強く好む） |
| `weights.keep_together_days` | float | 2.0 | 1 タスクが跨ぐ日 1 日あたりの減点（高いほど 1 日でまとめることを好む） |
| `weights.early_placement` | float | 0.02 | 締切付きタスクを早めに置く per-minute ボーナス（slack_ratio で重み付け） |
| `min_fragment_min` | int | 30 | 1 断片の最小サイズ（分） |
| `max_fragments_per_task` | int / null | 5 | 1 タスクの分割上限。null で無制限 |
| `time_limit_sec` | int | 30 | ソルバーの時間制限（秒） |
| `enabled_constraints` | set | 全 7 件 | 動的に切り替え可能 |
| `enabled_objectives` | set | 全 4 件 | 同上 |
| `backend` | Literal | `"pulp"` | 現状 PuLP のみ |

### 5.1 重みの目安

| 状況 | 推奨 |
|---|---|
| 締切重視（締切に間に合うかが第一） | `urgency` を 2.0、`energy_match` を 0.02 に下げる |
| 体力管理重視（朝はガッツリやりたい） | `energy_match` を 0.1〜0.3 |
| 全タスク詰め込み重視 | `unassigned_penalty` を 10.0 |

`energy_match` だけ桁が違う（0.05 既定）のは、**分単位積算で他の項目と数値スケールを合わせるため**。タスク 60 分 × エナジー 0.5 = 15 が priority 1 件分相当（`1.0 * 5/5 = 1.0` を 15 倍にすると合う）— 実際は分の差があるのでもう少し小さめにしている。

---

## 6. スロット側で効く設定（user_settings 経由）

タスク側でなくスロット生成段階で効くものは [`phase2_design.md`](phase2_design.md) / [`api_cheatsheet.md §4.5.3`](api_cheatsheet.md) 参照。要点だけ:

| 設定 | 効くタイミング | デフォルト |
|---|---|---|
| `work_hours.<day>.slots` | スロット生成（曜日ごとの作業可能時間帯） | 平日/週末とも 9:00–12:00 + 13:00–19:00（昼休み込み） |
| `slot_min_duration_min` / `slot_max_duration_min` | スロット分割 | 30 / 120 |
| `calendar_location_rules` | 各 event の場所推定 | 大学カレ ID → university、`intern\|インターン` 一致 → office |
| `location_commutes.<loc>.to_min/from_min` | 通学/通勤を busy にする | university 30/30、office 20/20 |
| `location_commutes.<loc>.linger_after_min` | 場所滞在時間の延長（放課後図書館） | university 180、office 0 |
| `day_type_rules` / `day_type_default` | スロットの `energy_score` と `allowed_max_task_duration_min` 決定 | 拘束時間ベース 4 段階：heavy_day(≥6h)/medium_day(3-6h)/light_day(0-3h)/free_day(0h) → 各 energy/duration cap |
| `ignore_all_day_events` | 終日イベントの忙しさ判定除外 | `true` |

スロットには `energy_score`（0.0–1.0）と `allowed_max_task_duration_min`（分）が day_type から導出されて埋め込まれ、最適化はそれを所与とする。

---

## 7. バックエンド（ソルバー）

[`backend/pulp_backend.py`](../backend/app/services/optimizer/backend/pulp_backend.py)

- **PuLP + CBC**（オープンソース MIP ソルバー）
- 最大化問題
- `time_limit_sec`（既定 30）で時間切れ → `timed_out` 状態を返す
- 解ステータスは `optimal` / `feasible` / `infeasible` / `timed_out` / `error` の 5 種類

将来 OR-Tools に乗せ替える場合は [`SolverBackend`](../backend/app/services/optimizer/backend/base.py) インターフェイス（`add_binary_var` / `add_int_var` / `add_constraint` / `add_to_objective` / `solve` / `value`）を実装すれば既存ロジックを保ったまま差し替え可能。

---

## 8. リクエスト時の設定上書き

特定の最適化実行だけ設定を変えたいときは `/optimize` 呼び出しに `config_overrides` を渡す。永続化はしない。

```bash
curl -X POST $TS_BASE/optimize -H "Content-Type: application/json" -d '{
  "start": "2026-05-10T00:00:00+09:00",
  "end":   "2026-05-17T23:59:59+09:00",
  "config_overrides": {
    "weights": {"urgency": 2.0, "energy_match": 0.02},
    "max_fragments_per_task": 3,
    "enabled_constraints": ["all_or_nothing", "slot_capacity", "deadline", "min_fragment_size", "location_compatibility"]
  }
}'
```

- `weights` だけは部分上書き（指定した重みのみ変更）
- 他のフィールドは値ごと上書き
- snapshot に保存されるので、後から `/replay` で同じ条件を再現可能

---

## 9. 既定値のまとめ（cheat sheet）

```python
OptimizerConfig(
    weights = {
        "priority":                  1.0,
        "urgency":                   1.0,
        "energy_match":              0.05,
        "unassigned_penalty":        5.0,
        "keep_together_fragments":   1.0,
        "keep_together_days":        2.0,
        "early_placement":           0.02,
    },
    enabled_constraints = {
        "all_or_nothing", "slot_capacity", "deadline", "force_deadlined",
        "duration_cap", "min_fragment_size", "max_fragments",
        "location_compatibility",
    },
    enabled_objectives = {
        "priority", "urgency", "energy_match", "unassigned_penalty",
        "keep_together", "early_placement",
    },
    min_fragment_min       = 30,
    max_fragments_per_task = 5,
    time_limit_sec         = 30,
    backend                = "pulp",
)
```

---

## 9.1 infeasible 回避 retry chain

`optimizer_service.run_optimization` は MIP を **1 回ではなく最大 4 回**回して、infeasible を極力避ける:

| 段 | 延長 | duration_cap | 用途 |
|---|---|---|---|
| 1 | なし | 有効 | 通常運用 |
| 2 | 〜23:30 | 有効 | 夜遅くに枠を取れば収まるケース |
| 3 | 〜23:59 | 有効 | さらに遅くまで延ばせば収まるケース |
| 4 | 〜23:59 | **無効** | heavy_day に長尺タスクが当たって duration_cap で詰まったケース（last resort） |

- 各段で延長スロットは `energy_score × 0.3` 倍で生成される → 通常段で fit する case では夜スロットは使われない
- どの段で確定したかは `notes` に `work_hours_extended_to=...` や `duration_cap disabled as last resort` として記録される
- 4 段目でも infeasible なら、本当に物理的に無理（24 時間タスクが明日まで、等）

---

## 10. 既知の制限・拡張余地

| 項目 | 現状 | 拡張案 |
|---|---|---|
| 時間帯ごとの重み | day_type ベースで 1 日 1 値 | 朝/昼/夜の細粒度重みを `energy_score` で実装可能（ただし設定 UI が必要） |
| 場所間の移動経路 | home ↔ uni / office のみ。`uni → office → home` のような連続移動は未対応 | スロットを location 連続ブロックでクラスタリングしてペナルティ項を追加 |
| 既存配置を優先（インクリメンタル） | `/optimize` は毎回ゼロから配置 | `task.scheduled_start` を持つタスクには「同じ位置を維持すると加点」項を追加 |
| 締切ソフト化 | `deadline` + `force_deadlined` の組合せで完全ハード | 必要なら `force_deadlined` を外して「超過した分の penalty」化（現状は disable 可能） |
| 重複防止（連日同じタスク） | 未対応（そもそも 1 タスクは 1 回配置で all-or-nothing） | 反復タスクは Phase 7+ で別モデル化 |
