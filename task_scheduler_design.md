# タスク自動スケジューリングアプリ 設計ドキュメント

## 概要

Google ToDoのタスクをGoogleカレンダーの空き時間に自動で最適配置するアプリ。
MIP（整数計画法）をコアエンジンとして使い、ユーザーの習性・行動パターンをソフト制約として組み込む。

---

## 技術スタック

| レイヤー | 技術 | 用途 |
|---|---|---|
| API サーバー | FastAPI | バックエンドAPI |
| DB | PostgreSQL | タスク履歴・設定・日タイプ定義の保存 |
| 最適化エンジン | PuLP + OR-Tools | MIPによる最適スケジューリング |
| 外部連携 | Google Calendar API / Google Tasks API | 予定・タスクの取得と書き込み |
| 認証 | Google OAuth2 | Googleアカウント連携 |
| フロントエンド | React | 確認画面・設定UI |

---

## システム構成

```
[React UI]
    ↕ REST API
[FastAPI]
    ├─ Google Tasks API     → タスク一覧取得
    ├─ Google Calendar API  → 空き枠取得・予定書き込み
    ├─ Day Type 判定モジュール → カレンダーから日タイプを自動分類
    ├─ スロット生成モジュール  → 使える時間帯を自動算出
    ├─ MIP Solver (PuLP)    → タスク×スロットの最適配置
    └─ PostgreSQL           → 設定・履歴保存
```

---

## データモデル

### タスク（Google Todoから取得 + ユーザー入力）

```python
task = {
    "id": "string",
    "title": "レポート執筆",
    "duration_min": 90,       # ユーザーが入力
    "deadline": "2025-05-15",
    "priority": 3,            # 1〜5（ユーザーが入力）
    "weight": 0.8,            # 0〜1（タスクの重さ、ユーザーが入力）
}
```

### スロット（カレンダーと日タイプから自動生成）

```python
slot = {
    "datetime": "2025-05-12 17:00",
    "duration_min": 60,
    "energy_score": 0.8,          # 0〜1（集中しやすさ）
    "allowed_weight_max": 1.0,    # その時間帯に置けるタスクの重さ上限
}
```

---

## 日タイプの自動分類

カレンダーの予定を読み取り、その日の行動パターンを自動判定する。

| 日タイプ | 条件 | 使える時間帯 | エネルギー |
|---|---|---|---|
| `intern_day` | インターン予定あり | 帰宅後のみ | 0.3 |
| `uni_light` | 〜4限で終わる日 | 放課後〜19時（図書館） | 0.8 |
| `uni_heavy` | 5限まである日 | ほぼなし | 0.4 |
| `tuesday` | 火曜（体育あり） | 放課後（補正あり） | 0.5 |
| `free_day` | 予定なし・土日 | 終日 | 1.0 |

### 移動バッファの自動付与

大学・オフィス・歯科大それぞれに対して、前後に固定バッファ時間を設定する。

```python
location_buffer = {
    "university": {"before_min": 30, "after_min": 20},
    "office":     {"before_min": 20, "after_min": 20},
    "dental":     {"before_min": 30, "after_min": 30},
}
```

---

## 最適化エンジン設計

### 問題の定式化

**決定変数**

```
x[i][j] ∈ {0, 1}
  i: タスクのインデックス
  j: スロットのインデックス
  x[i][j] = 1 → タスクiをスロットjに配置する
```

**ハード制約（絶対に破れない）**

- 各タスクは最大1つのスロットにしか配置されない
- 各スロットに入るタスクの合計時間はスロット長を超えない
- カレンダーの既存予定・移動バッファと被らない
- 締め切りを超えたスロットには配置されない

**目的関数（最大化）**

```
Maximize:
  Σ x[i][j] × (
      w1 × priority_score[i]       # 優先度が高いほど加点
    + w2 × urgency_score[i]        # 締め切りが近いほど加点
    + w3 × energy_match[i][j]      # タスクの重さとスロットのエネルギーが合うほど加点
    - w4 × overdue_penalty[i][j]   # 締め切りを超えると大減点
  )
```

**energy_match の計算**

```python
# タスクの重さとスロットのエネルギーが近いほどスコアが高い
energy_match[i][j] = 1 - abs(task[i].weight - slot[j].energy_score)

# 例：
# 重いタスク(0.8) × 図書館スロット(0.8) → 1.0（完璧）
# 重いタスク(0.8) × インターン後スロット(0.3) → 0.5（ミスマッチ）
```

**urgency_score の計算**

```python
days_remaining = (deadline - today).days
urgency_score = 1 / (days_remaining + 1)  # 締め切りが近いほど高い
```

---

## APIエンドポイント設計

```
POST /auth/google          → Google OAuth認証
GET  /tasks                → Google ToDoからタスク一覧取得
GET  /calendar/slots       → カレンダーから空きスロット生成
POST /optimize             → 最適化実行 → 配置結果を返す
POST /calendar/apply       → 最適化結果をカレンダーに書き込む
GET  /settings             → ユーザー設定取得
PUT  /settings             → ユーザー設定更新（重みパラメータなど）
```

---

## 開発ロードマップ

### Step 1：Google API連携
- OAuth2認証の実装
- Google ToDoのタスク一覧取得
- Googleカレンダーの予定取得

### Step 2：スロット生成
- 日タイプの自動判定ロジック
- 移動バッファの付与
- 空きスロットの生成

### Step 3：MIPエンジン単体の構築
- PuLPで定式化・動作確認
- ダミーデータで最適化が動くことを確認

### Step 4：FastAPIで統合
- `/optimize` エンドポイントを実装
- Step1〜3を繋ぐ

### Step 5：カレンダーへの書き込み
- 最適化結果をGoogleカレンダーに登録

### Step 6：React UIの実装
- タスク入力フォーム
- 最適化結果の確認・修正画面
- 設定画面（重みパラメータの調整）

---

## 詰まりやすいポイント

| ポイント | 対策 |
|---|---|
| Google OAuthの初期設定 | `google-auth-oauthlib` を使う。ローカルでは `InstalledAppFlow` が楽 |
| 空きスロットの定義 | 「作業可能時間帯」をユーザー設定で持たせる（例：8時〜22時） |
| MIPが解けない場合 | 制約を緩和してソフト制約に変える、またはスロット数・タスク数を削減 |
| GAへの移行タイミング | タスク数が増えMIPが遅くなったら検討。DEAPライブラリが定番 |
