# Phase 5：カレンダー書き込み 詳細設計

> 対象期間：1〜2 日
> ゴール：最適化結果を Google Calendar に予定として書き込み、再実行・取り消しもできる。
> 参照：`project_plan.md` §4 Phase 5、`docs/phase3_design.md`（snapshot 構造）、`docs/phase4_design.md`（Slot.location）

---

## 0. このフェーズの位置づけ

**やること:**
- snapshot ID を渡すと、その配置結果を Google Calendar に events として作成
- **冪等性**：再実行しても重複しない（前回の events を識別して更新 or 削除）
- **dry-run**：書き込まず「何が書かれるか」だけ返す
- **取消**：`DELETE` で全消し
- 連動して `tasks.scheduled_event_id` を埋める（Phase 4 で空欄だった列）

**やらないこと:**
- カレンダー書き込み専用カレンダーの自動作成（既存のプライマリに書く前提）
- 通知の制御（リマインダー設定など）
- 衝突検知（書き込み時にまだ既存予定があった場合のエラー処理） — 楽観的に上書き

**Phase 3 との接続：**

```
[Optimizer] ─→ SolveResult ─→ Snapshot ─→ /apply (DB の tasks.scheduled_* 更新)
                                  │
                                  └─→ /write (Google Calendar に events 作成) ★Phase 5
```

---

## 1. 主要設計判断

| 判断 | 値 | 理由 |
|---|---|---|
| **書き込み先カレンダー** | プライマリ固定（既定）、設定で変更可 | 個人利用前提。専用カレンダーを使いたい場合は `user_settings.target_calendar_id` で切替 |
| **冪等性キー** | `extendedProperties.private.snapshot_id` + `task_id` + `fragment_index` | Google Calendar の event metadata に埋める。再書き込み時はこれで照合 |
| **イベントタイトル** | `[task-scheduler] <task.title>` | 接頭辞でアプリが書いたものか識別。フィルタ用 |
| **再書き込み戦略** | 「同じ snapshot を書く」=「前回 events を全部消して新規作成」 | 差分マージは複雑すぎる。delete + create が単純で予測可能 |
| **異なる snapshot を書く** | 既存の `task-scheduler` 印が付いた events を全削除 → 新規作成 | 「最新の最適化結果が常にカレンダー」の状態を保つ |
| **dry-run 既定** | `?dry_run=false`（書き込みが既定） | 操作の意図がはっきりしている時に呼ぶ前提 |

---

## 2. データモデル

### 2.1 既存スキーマで足りるか確認

- `tasks.scheduled_event_id`（Phase 1 で追加済、現状空欄）：書き込んだ event id を埋める
- `tasks.scheduled_start` / `scheduled_end`（Phase 4 で追加済）：apply で埋まる、書き込み時に変更不要
- `optimizer_snapshots.result_json`（Phase 3 で追加済）：書き込みの入力ソース

**追加スキーマ不要**。Phase 5 はテーブル追加なし。

### 2.2 Google Calendar イベントの metadata

各 event に以下を埋める:

```json
{
  "summary": "[task-scheduler] レポート執筆",
  "description": "Optimized by task-scheduler. Snapshot: <id>",
  "start": {"dateTime": "...", "timeZone": "Asia/Tokyo"},
  "end":   {"dateTime": "...", "timeZone": "Asia/Tokyo"},
  "extendedProperties": {
    "private": {
      "task_scheduler": "1",
      "snapshot_id": "<snapshot uuid>",
      "task_id": "<task uuid>",
      "fragment_index": "0"
    }
  }
}
```

- **`task_scheduler: "1"`** が「アプリが作った」マーカー。これで他の手動予定と区別
- 再書き込み時は `q="task-scheduler"` でリスト取得（または `privateExtendedProperty=task_scheduler=1`）→ 一括削除 → 新規作成

### 2.3 `user_settings` への追加（任意）

追加するなら:

```json
{
  "target_calendar_id": "primary",
  "event_title_prefix": "[task-scheduler]"
}
```

両方とも既存 `SettingsRead` に追加。デフォルトは上記。

---

## 3. API

### 3.1 `POST /optimizer/snapshots/{id}/write`

**リクエスト：**
```json
{
  "dry_run": false,
  "target_calendar_id": "primary"
}
```

両方とも省略可。

**レスポンス：**
```json
{
  "snapshot_id": "...",
  "dry_run": false,
  "deleted_event_count": 6,
  "created_events": [
    {
      "task_id": "...",
      "task_title": "物性化学レポート",
      "event_id": "google_event_id",
      "start": "2026-05-12T03:10:00Z",
      "end":   "2026-05-12T05:10:00Z"
    }
  ]
}
```

dry_run=true のときは `event_id` は空、`deleted_event_count` は「**もし実行したら消されるはずの数**」。

### 3.2 `DELETE /optimizer/snapshots/{id}/write`

このアプリが書いた events を全削除（snapshot 単位ではなく、`task_scheduler` マーカー付きの全 events）。

**レスポンス：**
```json
{"deleted_event_count": 6}
```

オプションで `?snapshot_id=<id>` を渡すと「特定 snapshot の events だけ消す」も可能（`extendedProperties.snapshot_id` で絞り込み）。

### 3.3 エラー

| HTTP | error コード | 状況 |
|---|---|---|
| 401 | `not_authenticated` / `reauth_required` | OAuth 期限切れ |
| 404 | `not_found` | snapshot ID が存在しない、または result が `infeasible` で書く内容なし |
| 422 | `nothing_to_write` | snapshot に assignments が無い |
| 502 | `calendar_api_error` | Google API エラー |

---

## 4. サービス層実装

### 4.1 ファイル配置

```
backend/app/
├── services/google/
│   └── calendar.py              既存：list_events / list_calendars
└── services/optimizer/
    └── writer.py                ★ Phase 5 追加：書き込みロジック
```

`writer.py` の主な関数:

```python
async def write_snapshot(
    db: AsyncSession,
    user_id: str,
    snapshot_id: str,
    *,
    dry_run: bool = False,
    target_calendar_id: str = "primary",
) -> WriteResult:
    """1. 既存の task_scheduler events を取得
    2. （dry_run でなければ）一括削除
    3. snapshot.result_json から events を構築
    4. （dry_run でなければ）順次作成
    5. tasks.scheduled_event_id を更新
    """

async def delete_all_app_events(
    db: AsyncSession,
    user_id: str,
    *,
    target_calendar_id: str = "primary",
    snapshot_id: str | None = None,  # 指定すれば snapshot 単位で削除
) -> int:
    """app マーカー付き events を一括削除。返り値は削除件数。"""
```

### 4.2 既存 events の取得

```python
service.events().list(
    calendarId=target_calendar_id,
    privateExtendedProperty="task_scheduler=1",
    maxResults=2500,
).execute()
```

### 4.3 削除と作成の同期/非同期

- 削除はループで `service.events().delete(...).execute()` を呼ぶ。
- 作成も同様に `service.events().insert(...).execute()`。
- バッチ実行（`google-api-python-client` の `new_batch_http_request()`）で性能改善可。**MVP では順次実行**で OK（10〜30 件規模なら数秒）。

### 4.4 `extendedProperties` の正しい使い方

Google Calendar の `extendedProperties.private` は文字列 → 文字列のマップ。

```python
event_body = {
    "summary": f"[task-scheduler] {task.title}",
    "start": {"dateTime": frag_start.isoformat(), "timeZone": "Asia/Tokyo"},
    "end":   {"dateTime": frag_end.isoformat(),   "timeZone": "Asia/Tokyo"},
    "extendedProperties": {
        "private": {
            "task_scheduler": "1",
            "snapshot_id": snapshot_id,
            "task_id": task.id,
            "fragment_index": str(idx),
        }
    },
    "reminders": {"useDefault": False, "overrides": []},  # 通知は出さない
}
```

通知（reminders）はあえて空にする。アプリが大量に書いてスマホが鳴り続けるのを避けるため。

### 4.5 タスクの `scheduled_event_id` 更新

書き込み成功後、各タスクについて **最初の fragment の event_id** を `tasks.scheduled_event_id` に保存。
複数 fragment ある場合、UI 側で「メインの event」を指す参照として最初のものを使う。

---

## 5. テスト計画

### 5.1 ユニットテスト

| 対象 | 確認内容 |
|---|---|
| イベント body 構築 | summary 接頭辞、extendedProperties の中身、reminders 無効 |
| ID 採番 | snapshot_id + task_id + fragment_index がユニーク |
| dry_run 分岐 | dry_run のとき `service.events().delete/insert` が呼ばれない |

### 5.2 統合テスト（Google API モック）

`googleapiclient` をモックして:
- 既存 0 件 + 新規 3 件 → 0 削除 + 3 作成
- 既存 5 件（うち他 snapshot 由来 2 件） + 新規 3 件 → 5 削除 + 3 作成（全消し戦略）
- snapshot.assignments が空 → `nothing_to_write` エラー
- Google API が 401 → `reauth_required` 伝播
- Google API が 500 → 部分的成功で書き込みがあれば、その分は記録 + ロールバック試みる

### 5.3 実機テスト

実カレンダーに小さい snapshot を書く → スマホで確認 → DELETE で消える、を 1 回手動で実行。

---

## 6. 実装順

1. `services/optimizer/writer.py`：基本ロジック（write/delete の関数）
2. ユニットテスト（モックで body 構築の確認）
3. `api/optimize.py`：`POST/DELETE /optimizer/snapshots/{id}/write` 追加
4. `tasks.scheduled_event_id` 連動更新
5. dry_run モード
6. 統合テスト（モック）
7. 実機検証
8. ドキュメント追加（api_cheatsheet）

---

## 7. 動作確認シナリオ

```bash
# 0. 既存タスクで最適化 → 結果を /apply で書き戻し
curl -X POST $TS_BASE/optimize -d '{"start":"...","end":"..."}' | jq .snapshot_id
SNAP=...

# 1. dry-run で何が書かれるかプレビュー
curl -X POST $TS_BASE/optimizer/snapshots/$SNAP/write -d '{"dry_run":true}'

# 2. 実際に書き込み
curl -X POST $TS_BASE/optimizer/snapshots/$SNAP/write -d '{"dry_run":false}'
# → スマホの Google Calendar に予定が入る

# 3. 取消
curl -X DELETE $TS_BASE/optimizer/snapshots/$SNAP/write
# → 全消し
```

---

## 8. Phase 5 完了の判定

- [ ] `POST /optimizer/snapshots/{id}/write` で実カレンダーに予定が入る
- [ ] スマホの Google Calendar アプリで確認できる
- [ ] 同じ snapshot を 2 回書いても重複しない
- [ ] 別の snapshot を書くと前回分が消えて新規分だけ残る
- [ ] `DELETE` で全消しできる
- [ ] dry_run で書かずにプレビューできる
- [ ] tasks.scheduled_event_id が埋まる

---

## 9. このフェーズで残す未解決事項（Phase 6+）

- **専用カレンダーの自動作成**：「task-scheduler」専用カレンダーを作って書き込む選択肢。現状はプライマリに書く
- **手動編集後の同期**：ユーザーが Google Calendar 側でアプリ書き込み event を移動した場合の挙動。現状は次の `/write` で上書きされる
- **書き込み中エラー時のロールバック**：途中で API エラーが出ると一部書き込み済 + 一部未、の状態に。MVP では「エラー出たら DELETE で全消ししてやり直し」運用
- **複数 fragment イベントのリンク**：同じタスクの 3 つの fragment が別 events として作られる。UI でそれをグループ化して表示するのは Phase 6
