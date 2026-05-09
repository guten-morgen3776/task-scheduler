# Phase 4：場所制約 詳細設計

> 対象期間：4〜5 時間
> ゴール：「タスクをやれる場所」と「カレンダーから推定したスロットの場所」をマッチングさせる仕組みを最適化に組み込む。
> 参照：`docs/feature_backlog.md` §1.6（場所要望）、`project_plan.md` §6.7（拡張可能設計）、`docs/phase2_design.md`（スロット生成）、`docs/phase3_design.md`（最適化）

---

## 0. このフェーズの位置づけ

**やること:**
- Task に `location` フィールド追加（ユーザー入力）
- Slot に `location` フィールド追加（カレンダーから自動推定）
- `calendar_location_rules`：イベントに場所をタグ付ける DSL
- `location_commutes`：場所ごとの往復通学/通勤時間
- 「場所ウィンドウ」モデルでバッファ計算を改修（既存バッファのバグ修正を兼ねる）
- 新制約 `LocationCompatibilityConstraint`：場所が合わないスロットには配置しない

**やらないこと（Phase 4+ 申し送り）:**
- 場所間の位置関係（駅で寄り道など）→ ユーザーも保留と明言
- タスク内容からの場所自動判定 → ユーザー入力に統一する方針
- インターン在宅 vs オフィスの分離 → カレンダーのイベント形式変更が前提、まだ未実装
- 1 日内で複数場所を移動するパターン（uni 朝 → office 午後）→ ウィンドウ複数化で実装可能だがレアケースなので保留

**Phase 3 までとの接続：**

```
[Task CRUD]   ───┐
                 ├─→ Optimizer.solve(tasks, slots, ...) → SolveResult
[Slot 生成] ───┘             ↑
                              └─ Phase 4 で「場所マッチ」を新たな制約として追加
```

---

## 1. 主要設計判断（Phase 4 の前提）

| 判断 | 値 | 理由 |
|---|---|---|
| **場所 enum** | `home` / `university` / `office` / `anywhere` | ユーザーの行動パターン（家↔大学/office）をカバー。必要なら DSL 側で追加可 |
| **連続滞在の閾値** | なし（同日の同場所イベントは全 1 ウィンドウに集約） | 「大学に来てる間は図書館にいる」という現実に整合 |
| **Task.location 既定** | NULL（= `anywhere` 扱い） | 後方互換、ユーザーが明示しない限り場所制約は効かない |
| **Slot.location 推定** | カレンダー由来。マッチしないイベントは null扱い、ウィンドウ外は home | ユーザーが言ったルールベース判定をそのまま反映 |
| **既存 `location_buffers`** | 廃止（migration 0008 で user_settings をリセット） | 連続イベントのバグを抱えるので置き換える方が綺麗 |
| **複数場所の同日混在** | 当面サポートしない（同日に異場所のイベントがあった場合 = 各ウィンドウ独立） | Phase 5+ で必要なら拡張 |

---

## 2. 概念モデル：「場所ウィンドウ」

### 2.1 既存実装のバグ

UTAS の授業が 10:25–12:10 と 13:00–14:45 の 2 件ある日に、現状の `location_buffers`（大学 30/20）は:

```
イベント 1：busy 09:55–12:30  (前 30 / 後 20)
イベント 2：busy 12:30–15:15
→ マージ：busy 09:55–15:15 一本（昼休み 12:10–13:00 も busy 扱い）
```

実際は 12:10–13:00 は**大学にいる**ので、図書館でタスクができる。

### 2.2 新モデル：場所ウィンドウ

その日の同じ場所のイベントを 1 つのウィンドウに集約し、**通学/通勤時間はウィンドウの境界にだけ付与**する。

```
[家] ─→ [大学ウィンドウ：09:55 〜 15:05] ─→ [家]
         ├─ 09:55–10:25  通学（busy）
         ├─ 10:25–12:10  授業1（busy）
         ├─ 12:10–13:00  昼休み      ← 大学にいる、タスク可（slot.location = university）
         ├─ 13:00–14:45  授業2（busy）
         └─ 14:45–15:05  通学（busy）
```

- **ウィンドウ内の隙間**：busy ではない。slot 生成対象、`slot.location = "university"`
- **ウィンドウ外の時間**：busy でない部分は `slot.location = "home"`

### 2.3 ウィンドウ算出アルゴリズム

```
1. その日のイベントを場所タグ付けして取得（calendar_location_rules で照合）
2. 場所別にグループ化（NULL = 場所なし、ウィンドウを作らない）
3. 各 location L について:
   first_start = min(event.start for event in L_events)
   last_end    = max(event.end   for event in L_events)
   window_start = first_start - location_commutes[L].to_min
   window_end   = last_end    + location_commutes[L].from_min
   yield LocationWindow(L, window_start, window_end)
4. 場所が決まらないイベント（NULL）も busy として扱うが、ウィンドウは作らない
```

---

## 3. データモデル

### 3.1 `tasks.location`（新設、nullable）

| カラム | 型 | NULL | 既定 | 備考 |
|---|---|---|---|---|
| `location` | TEXT | YES | NULL | NULL = 場所制約なし。値は `home` / `university` / `office` / `anywhere` |

### 3.2 `user_settings` の変更

**追加：`calendar_location_rules`** — 順序付きルールリスト。先頭から照合し、最初にマッチしたものを採用。

```json
[
  {
    "calendar_id": "u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com",
    "location": "university"
  },
  {
    "event_summary_matches": "intern|インターン",
    "location": "office"
  }
]
```

各ルールには **少なくとも 1 つの条件**（`calendar_id` か `event_summary_matches` のどちらか）と `location` が必須。

**追加：`location_commutes`** — 場所ごとの通学/通勤時間 + 放課後滞在時間。

```json
{
  "university": {"to_min": 30, "from_min": 30, "linger_after_min": 180},
  "office":     {"to_min": 20, "from_min": 20, "linger_after_min": 0}
}
```

- `to_min`：その場所への片道
- `from_min`：その場所からの片道
- `linger_after_min`：最後の予定が終わってから何分まで「その場所にいる」扱いするか
  - 例：大学 = 180 → 16:40 に最後の授業が終わっても 19:40 まで図書館にいると判断
  - 0 にすればその場所での滞在は予定範囲のみ
- `commute_from` はウィンドウ末尾の `from_min` 分間に配置される（つまり実際の帰宅は linger 後）

`home` は通学不要なので登録不要（暗黙の 0/0/0）。`anywhere` も同様。

**削除：`location_buffers`** — 既存のバッファルール。新モデルに置き換え。

### 3.3 `Slot.location`（新設）

slot 生成時に自動推定。値は同じ enum。場所が決まらない場合は `home`。

---

## 4. Pydantic スキーマ

```python
Location = Literal["home", "university", "office", "anywhere"]

class CalendarLocationRule(BaseModel):
    calendar_id: str | None = None
    event_summary_matches: str | None = None
    location: Location

    @model_validator(mode="after")
    def _at_least_one_condition(self) -> "CalendarLocationRule":
        if self.calendar_id is None and self.event_summary_matches is None:
            raise ValueError("Either calendar_id or event_summary_matches must be set")
        return self

class LocationCommute(BaseModel):
    to_min:   int = Field(ge=0, le=240)
    from_min: int = Field(ge=0, le=240)

class SettingsRead(BaseModel):
    # ... 既存フィールド ...
    calendar_location_rules: list[CalendarLocationRule]
    location_commutes: dict[Location, LocationCommute]
    # location_buffers は削除
```

Task 側：

```python
class TaskCreate(BaseModel):
    # ... 既存フィールド ...
    location: Location | None = None

class TaskRead(BaseModel):
    # ... 既存フィールド ...
    location: Location | None
```

---

## 5. アルゴリズム改修

### 5.1 buffer.py の変更点

`expand_busy_periods(events, rules)` を以下に置き換え:

```python
def compute_location_windows(
    events_by_day: dict[date, list[CalendarEvent]],
    location_rules: list[CalendarLocationRule],
    commutes: dict[Location, LocationCommute],
) -> list[LocationWindow]: ...

def compute_busy_periods(
    events: list[CalendarEvent],
    windows: list[LocationWindow],
) -> list[BusyPeriod]:
    """busy = events themselves + commute-only portions of each window's edges."""
```

つまり busy は:
1. **すべてのイベント**（場所タグの有無にかかわらず）
2. 各 location window の **両端の通学/通勤時間**（first_event_start − to_min 〜 first_event_start、および last_event_end 〜 last_event_end + from_min）

ウィンドウ内の event 間の gap は busy ではない（slot 生成対象になる）。

### 5.2 generator.py の変更点

slot 生成ループに 2 つ追加:
1. 1 日ぶんの events から `location_windows` を計算（先頭で 1 回）
2. 各 free interval（slot 候補）について：

```python
def slot_location_for(slot_start: datetime, slot_end: datetime, windows: list[LocationWindow]) -> Location:
    for w in windows:
        if w.start <= slot_start and slot_end <= w.end:
            return w.location
    return "home"
```

各 slot に `location` を貼って返す。

**注意**：slot 分割は **ウィンドウ境界をまたがない**ように制御する必要がある。なぜなら 1 つの slot が 2 つの場所にまたがると location が決まらないため。

```
1. work_hours から busy を引いて free intervals を得る
2. ★ 各 free interval をウィンドウ境界で分割（ウィンドウ内 / 外で別 slot に）
3. slot_max_duration_min で再分割
4. 各 slot に location を貼る
```

### 5.3 Optimizer 側

#### `OptimizerTask` / `OptimizerSlot` に location 追加

```python
@dataclass(frozen=True)
class OptimizerTask:
    # ...
    location: Location | None  # None = anywhere

@dataclass(frozen=True)
class OptimizerSlot:
    # ...
    location: Location
```

#### 新制約 `LocationCompatibilityConstraint`

```python
class LocationCompatibilityConstraint(Constraint):
    name = "location_compatibility"

    def apply(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            if task.location is None or task.location == "anywhere":
                continue
            for slot in ctx.slots:
                # slot.location is always set; "anywhere" is treated as "compatible with anything"
                if slot.location == "anywhere":
                    continue
                if slot.location != task.location:
                    ctx.backend.add_constraint(
                        ctx.x[task.id, slot.id] == 0,
                        name=f"{self.name}__{task.id}__{slot.id}",
                    )
```

`OptimizerConfig.enabled_constraints` の既定に `"location_compatibility"` を追加。

---

## 6. ファイル単位の変更まとめ

```
backend/
├── alembic/versions/0008_*.py      新規：tasks.location 追加、user_settings リセット
├── app/models/task.py              変更：location 列追加
├── app/schemas/task.py             変更：TaskCreate/Update/Read に location
├── app/schemas/settings.py         変更：CalendarLocationRule / LocationCommute / Location 追加、
│                                       location_buffers 削除、build_default_settings 更新
├── app/services/slots/
│   ├── domain.py                   変更：Slot.location、LocationWindow dataclass 追加
│   ├── buffer.py                   ★ 大幅書き換え：場所ウィンドウモデルへ
│   └── generator.py                変更：windows 計算 → slot に location 貼り付け、
│                                         境界での slot 分割
├── app/services/optimizer/
│   ├── domain.py                   変更：OptimizerTask/Slot に location
│   ├── orchestrator.py             変更：default_constraints に追加
│   ├── service.py                  変更：Task → OptimizerTask 変換、JSON シリアライズ
│   └── constraints/
│       └── location_compatibility.py  新規
├── app/services/tasks/tasks.py     変更：create/update に location 引数
└── app/api/tasks.py                変更：payload.location 受け渡し
```

合計 13 ファイル + 1 マイグレーション。

---

## 7. テスト計画

### 7.1 ユニットテスト

| 対象 | 確認内容 |
|---|---|
| `compute_location_windows` | 同日同場所 N 件 → 1 ウィンドウに集約。ウィンドウなし日 → 空リスト |
| `compute_busy_periods` | ウィンドウ境界の通学時間 + イベント自体が busy になる。ウィンドウ内 gap は busy にならない |
| `slot_location_for` | ウィンドウ内 → そのlocation、ウィンドウ外 → home |
| `LocationCompatibilityConstraint` | location 不一致なら x=0、anywhere は通る |

### 7.2 シナリオテスト

| シナリオ | 期待 |
|---|---|
| UTAS 授業 10:25-12:10 + 13:00-14:45 の日 | 12:10-13:00 が `university` の slot として出る（既存バグの回帰防止） |
| 朝 office 始業 10:00-18:00 | 10:00 前は home、休憩時間は office、18:20 以降は home |
| `location=university` のタスク × intern_day のスロットしかない | 未配置（LocationCompatibility が効く） |
| `location=anywhere` タスク | どのスロットにも置ける |
| Calendar に無いイベントしかない日（場所ルール非マッチ） | slot 全部 `home` 扱い |
| 同日 uni AM + office PM | 各々独立ウィンドウ、間は home |

### 7.3 既存テストへの影響

- `test_buffer.py`：旧 `expand_busy_periods` 用なので**書き換え必要**
- `test_day_type.py`：`busy_hours` の引数渡し方は同じだが、上流の windows 計算が変わるので**統合テスト**で検証
- `test_slot_generator.py`：slot に `location` フィールドが増えるので assertion 追加
- `test_optimizer.py`：`OptimizerSlot` のコンストラクタ引数増加で書き換え

---

## 8. 既定値（出荷時）

```python
calendar_location_rules = [
    CalendarLocationRule(
        calendar_id="u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com",
        location="university",
    ),
    CalendarLocationRule(
        event_summary_matches=r"intern|インターン",
        location="office",
    ),
]

location_commutes = {
    "university": LocationCommute(to_min=30, from_min=30),
    "office":     LocationCommute(to_min=20, from_min=20),
}
```

ユーザー固有の UTAS カレンダー ID をハードコードするのは抵抗あるが、個人利用前提なので OK。
将来クラウド化するときに別途リセット手段を用意（[project_plan.md §8](../project_plan.md)）。

---

## 9. API への影響

エンドポイントは増えない。既存ルートに location フィールドが追加されるだけ:

| エンドポイント | 変更 |
|---|---|
| `POST /lists/{id}/tasks` | リクエスト body に `location` 追加（任意） |
| `PATCH /tasks/{id}` | 同上 |
| `GET /tasks/{id}` / `GET /lists/{id}/tasks` | レスポンスに `location` 追加 |
| `GET /calendar/slots` | レスポンスに `location` 追加 |
| `GET /settings` / `PUT /settings` | `calendar_location_rules` と `location_commutes` フィールド、`location_buffers` 削除 |
| `POST /optimize` | 内部で LocationCompatibility 制約が効く（外見上は変化なし） |

---

## 10. 実装順（おすすめ）

1. Migration 0008 + Task.location 列追加
2. Pydantic スキーマ更新（Location enum、CalendarLocationRule、LocationCommute、build_default_settings）
3. `LocationWindow` dataclass + `compute_location_windows` + ユニットテスト
4. `compute_busy_periods` 新版 + `subtract_busy` でウィンドウ境界考慮 + ユニットテスト
5. `generator.py` 改修 + シナリオテスト（UTAS 授業の昼休みケース）
6. `OptimizerTask/Slot` に location 追加
7. `LocationCompatibilityConstraint` + 単体テスト
8. orchestrator / service / api に配線
9. test_optimizer のシナリオに「location=university のタスクが intern_day スロットには入らない」を追加
10. 実機検証（実カレンダー × 実タスク with location）
11. ドキュメント追加（api_cheatsheet § Location 関連、feature_backlog 更新）

---

## 11. Phase 4 完了の判定

- [ ] Migration 0008 が往復通る
- [ ] `GET /calendar/slots` で各 slot に `location` フィールドが入っている
- [ ] UTAS 授業の昼休みが `location=university` の slot として出る（既存バグ修正の確認）
- [ ] `location=university` を指定したタスクが intern day の slot には配置されない
- [ ] `location` 未指定（NULL）タスクは従来通り任意の slot に置かれる
- [ ] テストシナリオ全 pass、既存 71 テストも全 pass
- [ ] 実機で `/optimize` を叩いて違和感なく配置される

---

## 12. 確定 vs 不確実の切り分け

[memory: feedback_design_focus](../.claude/projects/-Users-aokitenju-task-scheduler/memory/feedback_design_focus.md) に従って:

**確定（普通に書ける）:**
- Task.location 列の追加とスキーマ
- LocationCompatibilityConstraint（パターンは DurationCap と同じ）
- API シリアライズ

**不確実（試行錯誤前提）:**
- `calendar_location_rules` の DSL 表現力 — 今は `calendar_id` と `summary_matches` の OR だけ。`location` 列との AND が要るかは運用してから
- `location_commutes` の値 — 30 分 / 20 分は仮置き
- 場所未判定イベントの扱い — 今は busy だが home ウィンドウとは独立。多重イベント日でこれがどう振る舞うか実機で確認してから

**従って:**
- DSL 拡張が必要になっても `CalendarLocationRule` に条件を 1 つ追加するだけで対応可能
- 値のチューニングは `PUT /settings` で完結
- 場所種類追加（dental など）は enum 拡張のみ（コード変更最小）

---

## 13. Phase 5+ への申し送り

- **インターン在宅 vs オフィス** — カレンダーのイベント形式（タイトルに `(リモート)` 等）変更が前提。形式が決まったら `event_summary_matches` で `office` を `office_remote` / `office_onsite` に分岐できる
- **複数場所同日**（uni 朝 → office 午後） — `compute_location_windows` は既に「場所別グループ化」しているので、複数ウィンドウが返るのは仕様内。slot 生成側で「ウィンドウ境界で分割」を実装すれば自動対応する
- **位置関係**（駅で寄り道） — 別のドメインモデル（Location グラフ + 経路コスト）が必要。当面なし
