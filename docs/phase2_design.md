# Phase 2：スロット生成エンジン 詳細設計

> 対象期間：2〜3 日
> ゴール：「期間を指定すると、ユーザーが作業に充てられる空きスロットの一覧を返す」エンジンを作る。
> 参照：`project_plan.md` §1.0（カレンダー取得ポリシー）、§4 Phase 2、`task_scheduler_design.md`（日タイプ・スロット定義）、`docs/phase1_design.md`（既存 API・データモデル）

---

## 0. このフェーズの位置づけ

**やること:**
- 作業可能時間帯と各種ルールを保存する `user_settings` テーブル + 設定 API
- 「日タイプ」判定（カレンダーから自動推定するヒューリスティクス）
- 移動バッファの付与（場所キーワード → 前後何分を「埋まっている」扱いに）
- 空きスロット生成（指定期間で `Slot` 構造体のリストを返す）
- 来週分のスロットを目視で確認できる API（`GET /calendar/slots`）

**やらないこと（Phase 3 以降）:**
- 最適化（タスク × スロットの割当）→ Phase 3
- カレンダーへの書き込み → Phase 5
- 設定 UI → Phase 6（このフェーズでは curl / Swagger UI で叩く）

**なぜ Phase 1 の `/calendar/events` で十分ではないか:**
- 取れるのは「埋まっている時間」だけで、「**空いている時間**」ではない
- 作業可能時間帯（朝何時から夜何時まで作業に使うか）が考慮されていない
- 移動バッファ（大学から帰ってくる 30 分は作業不可）が考慮されていない
- 日タイプ（その日のエネルギー水準）が決まっていない
- Phase 3 の MIP に渡すための `Slot` 構造体がまだない

---

## 1. 成果物チェックリスト

このフェーズ完了の判定条件:

- [ ] `user_settings` テーブルが追加され、Alembic マイグレーション 0004 が往復可能
- [ ] `GET /settings` `PUT /settings` で作業時間帯・場所バッファ・カレンダー含み除き等が編集できる
- [ ] `GET /calendar/slots?start=...&end=...` で来週 1 週間の空きスロットが返る
- [ ] 各スロットに `energy_score` と `allowed_weight_max` が付いている（Phase 3 の入力として有効）
- [ ] 空きカレンダーの日 → ほぼ作業可能時間帯フルで返る
- [ ] 5 限まで授業ある日 → ほぼスロットが出ない
- [ ] インターン勤務日 → 帰宅後のみスロットが出る
- [ ] テスト：シナリオ別の挙動 7 ケース以上が pass
- [ ] `docs/api_cheatsheet.md` に `/calendar/slots` `/settings` の curl サンプル追記

---

## 2. データモデル

### 2.1 `user_settings`（新設）

シングルユーザー前提だが `user_id` で紐付ける構造（[project_plan.md §8.1](../project_plan.md) の方針）。

| カラム | 型 | NULL | 既定値 | 備考 |
|---|---|---|---|---|
| `user_id` | TEXT (UUID) | NO | — | PK 兼 FK → users.id |
| `work_hours` | TEXT (JSON) | NO | （後述）| 曜日ごとの作業可能時間帯 |
| `location_buffers` | TEXT (JSON) | NO | `{}` | 場所キーワード → before/after 分 |
| `day_type_rules` | TEXT (JSON) | NO | （後述） | 日タイプ判定の優先順ルール |
| `day_type_overrides` | TEXT (JSON) | NO | `{}` | `{"2026-05-12": "uni_light"}` 形式の手動上書き |
| `busy_calendar_ids` | TEXT (JSON list) | NO | `[]` | 「忙しい」として読むカレンダー ID。空配列なら全部対象 |
| `ignore_calendar_ids` | TEXT (JSON list) | NO | `[]` | 無視するカレンダー（祝日など） |
| `slot_min_duration_min` | INT | NO | 30 | これより短いスロットは捨てる |
| `slot_max_duration_min` | INT | NO | 120 | これより長いスロットは分割（1 タスク = 1 スロット原則のため） |
| `ignore_all_day_events` | BOOLEAN | NO | true | 終日イベントを busy 判定・日タイプ判定の両方から除外（リマインダー想定） |
| `created_at`, `updated_at` | DATETIME | NO | — | UTC |

**設計判断：**

- スキーマレスな構造（`work_hours` 等を JSON で保持）にする。Phase 4〜6 で頻繁に項目追加が想定されるため、列追加 + マイグレーション往復のコストを避ける
- 個別の Pydantic スキーマで型は厳密に検証する（`PUT /settings` のリクエストボディで）
- SQLite の `JSON` 型は SQLAlchemy 2.0 の `JSON` で十分（PostgreSQL 移行時もそのまま動く）

**`work_hours` の構造:**

```json
{
  "monday":    {"slots": [{"start": "09:00", "end": "22:00"}]},
  "tuesday":   {"slots": [{"start": "09:00", "end": "22:00"}]},
  "wednesday": {"slots": [{"start": "09:00", "end": "22:00"}]},
  "thursday":  {"slots": [{"start": "09:00", "end": "22:00"}]},
  "friday":    {"slots": [{"start": "09:00", "end": "22:00"}]},
  "saturday":  {"slots": [{"start": "10:00", "end": "23:00"}]},
  "sunday":    {"slots": [{"start": "10:00", "end": "22:00"}]},
  "timezone":  "Asia/Tokyo"
}
```

- 1 日に複数スロット（例：朝活と夜だけ）にも対応できる構造
- `timezone` は将来別 TZ 対応する場合の余地。当面 `Asia/Tokyo` 固定運用

**`location_buffers` の構造:**

```json
{
  "rules": [
    {"match": "university|大学|駒場|本郷", "before_min": 30, "after_min": 20, "label": "大学"},
    {"match": "intern|インターン", "before_min": 20, "after_min": 20, "label": "インターン"},
    {"match": "歯科|dental", "before_min": 30, "after_min": 30, "label": "歯科大"}
  ]
}
```

- `match` は正規表現（イベントの `summary` / `location` に対して大文字小文字無視で検索）
- 複数ルールがマッチしたら **最大値** を採用（厳しい方に倒す）
- 既定値は空。ユーザーが Phase 6 で UI から追加 or `PUT /settings` で初期化

**`day_type_rules` の構造（重要）:**

```json
{
  "rules": [
    {"name": "intern_day",  "if": {"event_summary_matches": "intern|インターン"}, "energy": 0.3, "allowed_weight_max": 0.5},
    {"name": "uni_heavy",   "if": {"event_count_min": 4, "tag_filter": "university"}, "energy": 0.4, "allowed_weight_max": 0.6},
    {"name": "uni_light",   "if": {"event_count_max": 3, "tag_filter": "university"}, "energy": 0.8, "allowed_weight_max": 1.0},
    {"name": "tuesday_pe",  "if": {"weekday": "tuesday", "event_summary_matches": "スポーツ|身体運動"}, "energy": 0.5, "allowed_weight_max": 0.8},
    {"name": "free_day",    "if": {"event_count_max": 0}, "energy": 1.0, "allowed_weight_max": 1.0}
  ],
  "default": {"name": "normal", "energy": 0.7, "allowed_weight_max": 0.8}
}
```

- 上から順にマッチする最初のルールを採用
- どれもマッチしなければ `default`
- `tag_filter` は将来「カレンダー ID にタグ付けして大学カレンダーから来た予定だけ数える」のような拡張のための予約フィールド（Phase 2 では未実装でも可）

**設計上の意図:**

- 日タイプ判定は **試行錯誤前提のヒューリスティクス**。コード変更なしでルールを差し替えられる構造にしておく（[memory: feedback_design_focus](../../.claude/projects/-Users-aokitenju-task-scheduler/memory/feedback_design_focus.md) の方針）
- ルールは DSL 風にしすぎず、シンプルな AND 条件のみサポート
- 表現力が足りなくなったら Phase 3 後に拡張（OR、優先度の細分化、過去実績学習など）

**エナジーは「日単位」で扱う方針:**

`slot.energy_score = day_type.energy`（直接代入）。1 日内の時間帯による変動（朝高く夜低い等）は **当面入れない**（[Phase 3 設計判断との整合](phase3_design.md)）。
理由：

- `work_hours` を 9-19 で打ち切れば、夜遅くにスロットが生成されない（時間帯差の最大の用途を物理的に遮断）
- `day_type.allowed_weight_max` で「インターン日は重いタスク禁止」が既にハード制約として機能
- 残るのは「フリーな日の朝 vs 夕方」程度の繊細さで、実運用では「リストの上から実行する」で十分

時間帯重み付けが本当に必要になったら Phase 4+ で追加する（[phase3_design.md §9](phase3_design.md) 参照）。

### 2.2 `Slot` ドメイン型（DB に永続化しない）

スロットはステートレスに毎回生成するため、テーブルは不要。Pydantic + dataclass で表現。

```python
# app/services/slots/domain.py
@dataclass(frozen=True)
class Slot:
    id: str                 # 決定論的: "slot-2026-05-10T09:00:00Z-60"
    start: datetime         # UTC, tz-aware
    duration_min: int
    energy_score: float     # 0.0〜1.0
    allowed_weight_max: float  # 0.0〜1.0
    day_type: str           # "intern_day" / "uni_light" / ... / "normal"
```

Phase 3 の MIP では `Slot` を入力として受け取る前提（`docs/phase1_design.md` で言及した optimizer 抽象との整合）。

---

## 3. ディレクトリ構成（Phase 2 完了時）

```
backend/app/
├── api/
│   ├── settings.py              # Phase 2 で追加：/settings
│   └── slots.py                 # Phase 2 で追加：/calendar/slots
├── models/
│   └── user_settings.py         # Phase 2 で追加
├── schemas/
│   └── settings.py              # Phase 2 で追加：work_hours / buffers / rules の型
├── services/
│   └── slots/
│       ├── domain.py            # Phase 2 で追加：Slot dataclass
│       ├── settings.py          # Phase 2 で追加：設定 CRUD ロジック
│       ├── day_type.py          # Phase 2 で追加：日タイプ判定
│       ├── buffer.py            # Phase 2 で追加：場所バッファ計算
│       └── generator.py         # Phase 2 で追加：スロット生成本体
└── tests/
    └── test_slot_generator.py   # シナリオテスト
```

---

## 4. 設定 API（`/settings`）

### 4.1 エンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| `GET` | `/settings` | 現在の設定（無ければ既定値で初期化して返す） |
| `PUT` | `/settings` | 全部 / 部分更新 |
| `POST` | `/settings/reset` | 既定値で上書き（Phase 6 用、当面任意） |

### 4.2 既定値の方針

`GET /settings` を初めて叩いた時点で `user_settings` 行が無ければ、`services/slots/settings.py` 内の `default_settings()` を作成して保存。
既定値はユーザー個別の事情（大学・インターン）を考慮して以下を仕込む:

- `work_hours`：平日 09:00–22:00、土日 10:00–22:00
- `location_buffers`：大学 30/20、インターン 20/20、歯科 30/30
- `day_type_rules`：§2.1 のサンプル通り
- `busy_calendar_ids`：空（＝全カレンダー対象）
- `ignore_calendar_ids`：祝日カレンダー ID（自動検出 or 空で開始してユーザーが追加）

### 4.3 Pydantic スキーマ

```python
class WorkHourSlot(BaseModel):
    start: str  # "HH:MM"
    end: str    # "HH:MM"

class WorkHoursDay(BaseModel):
    slots: list[WorkHourSlot]

class WorkHours(BaseModel):
    monday: WorkHoursDay
    tuesday: WorkHoursDay
    # ... (week)
    timezone: str = "Asia/Tokyo"

class LocationBufferRule(BaseModel):
    match: str
    before_min: int = Field(ge=0, le=240)
    after_min: int = Field(ge=0, le=240)
    label: str

class DayTypeCondition(BaseModel):
    event_summary_matches: str | None = None
    weekday: Literal["monday", ..., "sunday"] | None = None
    event_count_min: int | None = None
    event_count_max: int | None = None

class DayTypeRule(BaseModel):
    name: str
    if_: DayTypeCondition = Field(alias="if")
    energy: float = Field(ge=0.0, le=1.0)
    allowed_weight_max: float = Field(ge=0.0, le=1.0)

class SettingsRead(BaseModel):
    work_hours: WorkHours
    location_buffers: list[LocationBufferRule]
    day_type_rules: list[DayTypeRule]
    day_type_default: DayTypeRule
    day_type_overrides: dict[str, str]  # date string -> day type name
    busy_calendar_ids: list[str]
    ignore_calendar_ids: list[str]
    slot_min_duration_min: int
    slot_max_duration_min: int
    ignore_all_day_events: bool
```

`PUT /settings` は `SettingsUpdate`（全フィールドオプショナル）で部分更新を許す。

---

## 5. 日タイプ判定エンジン（`services/slots/day_type.py`）

### 5.1 入力

- 対象日（`date` オブジェクト、ユーザー TZ で）
- その日に発生するイベントのリスト（`CalendarEvent`、§4.2 と同じ正規化済み形式）
- `day_type_rules`、`day_type_default`、`day_type_overrides`

### 5.2 判定ロジック

```
classify_day(date, events, rules, default, overrides) -> DayTypeRule:
    if date.isoformat() in overrides:
        return rules[overrides[date.isoformat()]] or default
    for rule in rules:
        if matches(rule.if_, date, events):
            return rule
    return default
```

### 5.3 `matches` の判定基準

| 条件 | 意味 |
|---|---|
| `event_summary_matches` | その日のいずれかのイベントの `summary` が正規表現にマッチ |
| `weekday` | その日の曜日が一致 |
| `event_count_min` | その日のイベント数が指定値以上 |
| `event_count_max` | その日のイベント数が指定値以下 |

複数条件が指定されたら **AND**。

**注意：日タイプは「忙しい日タイプから先に評価」する優先順がユーザー設定で決まる**。例：「大学＋インターン両方ある日」のときは `intern_day` を `uni_heavy` より上に置けば intern_day が勝つ。

---

## 6. バッファ計算（`services/slots/buffer.py`）

### 6.1 関数シグネチャ

```python
def expand_busy_periods(
    events: list[CalendarEvent],
    rules: list[LocationBufferRule],
) -> list[BusyPeriod]:
    ...
```

### 6.2 アルゴリズム

各イベントについて:
1. `summary` と `location` を結合した文字列に対して各ルールの `match` 正規表現を当てる（`re.search`、大文字小文字無視）
2. マッチしたルールが複数あれば `before_min` `after_min` の **最大値** を採用
3. `start - before` 〜 `end + after` の `BusyPeriod` を作る
4. 何もマッチしなければバッファなしで `start`〜`end` をそのまま `BusyPeriod` に

すべての BusyPeriod を集めた後、**重複・連続区間をマージ**（標準的な区間マージアルゴリズム）。

```python
@dataclass(frozen=True)
class BusyPeriod:
    start: datetime
    end: datetime
    sources: list[str]  # event ids that produced this (デバッグ用)
```

---

## 7. スロット生成本体（`services/slots/generator.py`）

### 7.1 入出力

```python
async def generate_slots(
    db: AsyncSession,
    user_id: str,
    start: datetime,  # UTC
    end: datetime,    # UTC
) -> list[Slot]:
    ...
```

### 7.2 アルゴリズム

```
1. settings = load_user_settings(user_id)
2. events = calendar_service.list_events(
       db, user_id, start, end,
       calendar_ids=resolve_calendars(settings),
   )
   if settings.ignore_all_day_events:
       events = [e for e in events if not e.all_day]
3. busy = expand_busy_periods(events, settings.location_buffers)

4. ユーザーTZで [start, end] を 1 日ずつイテレート:
     for date in date_range:
        events_today = events で date に重なるもの
        day_type = classify_day(date, events_today, ...)

        # 作業可能時間帯から busy を引く
        candidates = work_hours[date.weekday] (UTC に変換)
        free = subtract_busy(candidates, busy)

        # 短すぎるスロットを捨てる
        free = [s for s in free if s.duration >= settings.slot_min_duration_min]

        # 長すぎるスロットを分割
        free = split_long_slots(free, settings.slot_max_duration_min)

        for s in free:
            yield Slot(
                id = "slot-{ISO8601}-{duration}",
                start = s.start,
                duration_min = s.duration,
                energy_score = day_type.energy,
                allowed_weight_max = day_type.allowed_weight_max,
                day_type = day_type.name,
            )
5. 全日分を結合 → start 順でソート → 返す
```

### 7.3 `resolve_calendars` の挙動

```python
def resolve_calendars(settings) -> list[str]:
    if settings.busy_calendar_ids:
        # 明示指定があればそれを使う（ignore は無視）
        return settings.busy_calendar_ids
    # それ以外は「全カレンダー − ignore_calendar_ids」
    all_ids = [c.id for c in await list_calendars(...)]
    return [c for c in all_ids if c not in settings.ignore_calendar_ids]
```

`ignore_calendar_ids` のみ設定されている運用が想定主流（祝日だけ除外）。

### 7.4 スロット分割の方針

- `slot_max_duration_min` を超えるスロットは均等分割（例：4 時間あれば 2 時間×2 に）
- 余りが出る場合は最後のスロットを短くする（min 制限を満たす範囲で）
- 分割理由：**1 タスク = 1 スロット**を原則にしたいので、長すぎるスロットは複数タスクの選択肢を減らす方が MIP の探索空間が小さくなり最適化が速い（[task_scheduler_design.md](../task_scheduler_design.md) の MIP 定式化に整合）

---

## 8. API エンドポイント `/calendar/slots`

### 8.1 仕様

| パラメータ | 必須 | 既定 | 備考 |
|---|---|---|---|
| `start` | Yes | — | ISO8601 + TZ |
| `end` | Yes | — | ISO8601 + TZ |
| `min_duration_min` | No | 設定値 | このリクエストだけ上書き |
| `max_duration_min` | No | 設定値 | 同 |

### 8.2 レスポンス例

```json
[
  {
    "id": "slot-2026-05-11T00:00:00Z-120",
    "start": "2026-05-11T00:00:00Z",
    "duration_min": 120,
    "energy_score": 0.8,
    "allowed_weight_max": 1.0,
    "day_type": "uni_light"
  },
  ...
]
```

### 8.3 エラー

- 400 `validation_error`：`start` ≥ `end` / TZ 欠落
- 401 `not_authenticated` / `reauth_required`：Calendar 取得が失敗したとき
- 502 `calendar_api_error`：Google 側エラー（既存処理を踏襲）

---

## 9. テスト戦略

### 9.1 ユニットテスト

| 対象 | 確認内容 |
|---|---|
| `expand_busy_periods` | バッファ加算・マージ・複数ルール最大値採用 |
| `classify_day` | 各ルールが順序通り評価される / overrides 優先 |
| `subtract_busy` | 区間引き算（busy が複数 / 端の重なり / 完全包含 / 跨ぎ） |
| `split_long_slots` | max を超える区間が分割される |

### 9.2 シナリオテスト（実カレンダー想定の合成データ）

`tests/test_slot_generator.py` に以下のテストを置く:

| シナリオ | 期待 |
|---|---|
| 空きカレンダー1日 | 作業時間帯フルがスロットになる（max で分割済） |
| インターン勤務日（10〜18 時） | 18:20 以降のみスロットが出る（バッファ加算） |
| 5 限まで授業ある日 | 17:30 以降の少しだけ（uni_heavy） |
| 4 限で終わる日 | 16:30 以降たっぷり（uni_light） |
| 大学＋インターンが混ざる日 | intern_day が勝つ（ルール優先順） |
| 移動バッファでスロット長が `slot_min` 未満 | スロットから除外 |
| `day_type_overrides` がある | ルールではなく上書き値が採用 |

### 9.3 統合テスト

- `PUT /settings` → `GET /calendar/slots` を 1 リクエストで通すフロー（calendar_service をモック）

---

## 10. 実装順（おすすめ）

1. `models/user_settings.py` + Alembic 0004
2. `schemas/settings.py`（Pydantic 階層型）+ `default_settings()` 実装
3. `services/slots/settings.py`（設定 CRUD）
4. `api/settings.py`（GET/PUT）
5. `services/slots/domain.py`（`Slot` / `BusyPeriod`）
6. `services/slots/buffer.py` + ユニットテスト
7. `services/slots/day_type.py` + ユニットテスト
8. `services/slots/generator.py` + ユニットテスト
9. `api/slots.py`（`/calendar/slots`）
10. シナリオテスト一式
11. `docs/api_cheatsheet.md` 追記
12. README に Phase 2 動作確認手順追記

---

## 11. Phase 2 完了の動作確認シナリオ

```bash
# 1. サーバー起動
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 2. 既定設定の確認（行が無ければ作って返す）
curl http://localhost:8000/settings | python -m json.tool

# 3. 祝日カレンダーを ignore に追加
curl -X PUT http://localhost:8000/settings \
  -H "Content-Type: application/json" \
  -d '{"ignore_calendar_ids":["ja.japanese#holiday@group.v.calendar.google.com"]}'

# 4. 来週分のスロット生成
curl "http://localhost:8000/calendar/slots\
?start=2026-05-11T00:00:00%2B09:00\
&end=2026-05-17T23:59:59%2B09:00" | python -m json.tool

# 5. 既知の予定がある日（インターン勤務日）でスロットが帰宅後のみであることを目視確認
# 6. 授業がぎっしり詰まった日（5 限まで）でスロットがほぼ無いことを確認
# 7. 完全に空きの日でフルスロットが出ることを確認
```

---

## 12. このフェーズで残す未解決事項（Phase 3 以降への申し送り）

- **`Slot` の `id` の決定論性**：再実行で同じ `id` が出るので、同一スナップショットの再現性に使える。Phase 3 の Snapshot/Replay 機構と整合
- **「タスク間移動バッファ」**：1 タスク終わったら次のタスクまで N 分空ける、という制約は **MIP のソフト制約**として Phase 3 で扱う（スロット生成時には入れない）
- **エネルギー学習**：当面 `day_type_rules` 固定。Phase 7 で過去実績から学習する仕組みを検討
- **異なる TZ 対応**：海外旅行中等。Phase 2 では `Asia/Tokyo` 固定で OK、`work_hours.timezone` フィールドだけ用意しておく
- **設定のバリデーション強度**：`work_hours` の `start < end` 等のクロスフィールドバリデーションは Phase 2 で入れる。複雑な健全性チェック（バッファが work_hours より長い等）は Phase 6 の UI 側で

---

## 13. 設計の核：何が「不確実」で何が「確定」か

[memory: feedback_design_focus](../../.claude/projects/-Users-aokitenju-task-scheduler/memory/feedback_design_focus.md) の方針通り、以下のように切り分け:

**確定済み（普通に書けば良い領域）:**
- `user_settings` の CRUD
- カレンダーイベントから busy 区間を作る（既存 `/calendar/events` を呼ぶだけ）
- 区間引き算・マージのアルゴリズム

**不確実（試行錯誤前提、差し替え可能に作る領域）:**
- 日タイプ判定ロジック（ルール DSL の表現力）
- `energy_score` / `allowed_weight_max` の値（最初は固定値で出して、Phase 3 の最適化結果を見ながら調整）
- バッファルールの粒度（場所マッチで足りるか / カレンダー ID マッチも要るか）
- スロット分割粒度（`slot_max_duration_min` の妥当値）

**従って:**
- 日タイプとバッファのルールは **JSON で外出し、コード変更なしでチューニング可能**
- `Slot` は dataclass で **Phase 3 の optimizer から見て安定した API**
- 値（energy 等）は **`PUT /settings` で簡単に変えられる**

これにより、Phase 3 で MIP を回した結果を見て「インターン日のエネルギーをもっと低くしよう」と思ったら、コードを触らずに `PUT /settings` 一発で対応できる。
