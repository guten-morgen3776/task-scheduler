# 機能バックログ（要望と実装状況）

> ユーザーから 2026-05-09 に共有された要望リストを起点に、実装済 / 部分実装 / 未実装を整理。
> 2026-05-09 後半に「重さ＝かかる時間統合」「拘束時間ベース判定」「完了処理」の 3 つを追加実装済。

---

## 0. 2026-05-09 後半に追加実装した変更

### `weight` を `duration_min` に統合
- `Task.weight` 列を廃止（migration 0007）
- `allowed_weight_max` (0-1) を `allowed_max_task_duration_min` (int 分) にリネーム
- `WeightCapConstraint` → `DurationCapConstraint`：タスクの**全体長**が slot の上限超なら配置不可（分割しても入れない）
- `EnergyMatchObjective` 簡略化：`w × energy × x[i,j]`（minutes-weighted by energy）

### 拘束時間ベースの day_type 判定
- `DayTypeCondition` に `total_busy_hours_min/max` を追加
- 既定ルールを再構成：`free_day`（0 件）→ `intern_day` → `heavy_day` (≥6h) → `medium_day` (3-6h) → `light_day` (0-3h)
- 件数ベースの `event_count_*` も併存

### 完了処理
- `Task.scheduled_end` 列を追加（migration 0007）
- `POST /optimizer/snapshots/{id}/apply`：snapshot の結果を tasks に反映（`scheduled_start` / `scheduled_end` 書き込み）
- 完了は既存の `POST /tasks/{id}/complete` で OK
- セマンティクス：scheduled_end までに complete されなければ未完了扱い、次の `/optimize` で再考慮される

---

## 1. 最適化条件

### 1.1 ✅ 締め切り

- [DeadlineConstraint](../backend/app/services/optimizer/constraints/deadline.py)：締切後のスロットには絶対置かない（ハード制約）
- [UrgencyObjective](../backend/app/services/optimizer/objectives/urgency.py)：締切が近いほど加点（`1/(days_until+1)`）
- 締切ありタスクは厳密、締切なしタスクは制約なし

### 1.2 ✅ 重さ・かかる時間（統合済）

- `duration_min`（分）に統一。`weight` 列は廃止
- 「タスクが長い = 重い」という前提
- [DurationCapConstraint](../backend/app/services/optimizer/constraints/duration_cap.py)：slot の `allowed_max_task_duration_min` を超える長さのタスクは置けない
- [EnergyMatchObjective](../backend/app/services/optimizer/objectives/energy_match.py)：`energy × x[i,j]`（minutes-weighted）→ 長いタスクほど高エネルギー帯を獲得しやすい

### 1.3 ✅ 優先度

- [PriorityObjective](../backend/app/services/optimizer/objectives/priority.py)：`priority/5` を z[i] に乗じて加点
- [UnassignedPenaltyObjective](../backend/app/services/optimizer/objectives/unassigned_penalty.py)：未配置時、優先度に応じた減点
- 締切（urgency）と方向が被るのはユーザー指摘の通り。両方を同時に効かせている

### 1.4 ✅ 時間帯の上限下限

- `user_settings.work_hours` で曜日ごとに作業可能時間帯を定義（既定 9:00-19:00）
- 範囲外にはスロットが生成されないため、最適化対象から自動除外

### 1.5 ✅ 既存カレンダー予定に被せない

- Phase 2 のスロット生成時点で `events_today` を `work_hours` から減算
- バッファ（移動時間）も加味して busy 区間を作り、スロット候補から除外

### 1.6 ✅ 場所（実装済 / 2026-05-09 後半 Phase 4）

- `tasks.location` 列を追加（enum: `home` / `university` / `office` / `anywhere` / NULL）
- `user_settings.calendar_location_rules` で「カレンダー → 場所」をルールベース判定（UTAS 由来 → university、intern キーワード → office）
- `user_settings.location_commutes` で場所ごとの通学/通勤時間
- **場所ウィンドウモデル**：同日の同場所イベントを 1 つのウィンドウに集約。境界に通学/通勤時間を加算するが、ウィンドウ内の隙間は free（既存バグ修正：大学の授業の合間に図書館でタスクできる）
- `Slot.location` 自動推定（ウィンドウ内 = そのlocation、外 = home）
- 新制約 `LocationCompatibilityConstraint`：location 不一致なら配置不可
- 詳細は [docs/phase4_design.md](phase4_design.md)
- インターン在宅 vs オフィス分離、場所間位置関係は Phase 5+ 申し送り

### 1.7 ✅ 1 日のキャパ（拘束時間ベース判定）

- `day_type.energy` で日ごとのエネルギー
- DSL に `total_busy_hours_min/max` を追加（バッファ込みの合計時間）
- 既定ルールは時間ベース：`heavy_day` (≥6h) / `medium_day` (3-6h) / `light_day` (0-3h)
- `intern_day` / `free_day` は引き続き keyword / 件数ベース

### 1.8 ✅ 未完了処理（簡易実装）

- タスクの状態は `completed: bool` のまま（要望に合わせて簡易）
- `Task.scheduled_end` 列を追加：optimizer が「いつまでに終わるべき」かを記録
- `POST /optimizer/snapshots/{id}/apply`：snapshot 結果を tasks に書き込む
- セマンティクス：`scheduled_end` までに `/complete` されなければ「未完了」のまま、次の `/optimize` で再考慮対象になる
- 「やったけど終わらなかった」を表現する `partial` 状態などは**当面入れない**（要望が「事後の二値判定で OK」とあったため）

---

## 2. ユーザー入力フィールド

| 要望 | 状態 | 備考 |
|---|---|---|
| タスク名（必須） | ✅ | `title`、1〜512 文字 |
| かかる時間の予測（ほぼ必須） | ✅ | `duration_min`、既定 60 |
| 締め切り（選択） | ✅ | `deadline`、nullable |
| 優先度（選択） | ✅ | `priority` 1〜5、既定 3 |
| **場所（選択）** | ❌ **未実装** | 1.6 と連動 |

実装済みだが要望リストにないもの:
- `weight`（脳のキャパ負担）— 1.2 の確認次第で扱いが変わる
- `notes`（自由メモ）— 残す

---

## 3. 残タスクの優先度

```
[低] 場所間位置関係（発展、ユーザー自身も後回し可と明言）
[低] インターン在宅 vs オフィス分離（カレンダー入力の整理が前提）
```

2026-05-09 中の作業で、ユーザー要望リストの全項目が実装完了。
最適化の中核（締切 / 重さ × 時間 / 優先度 / 既存予定 / 1 日のキャパ / 完了処理 / 場所）が揃った。
