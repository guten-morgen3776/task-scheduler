import { useMemo, useState } from "react";
import {
  useApplySnapshot,
  useDeleteWritten,
  useOptimize,
  useWriteSnapshot,
} from "../../hooks/useOptimize";
import { Button, Card, ErrorBanner, Input, Label } from "../ui";
import { ResultPreview } from "./ResultPreview";

export function OptimizePanel({ activeListId }: { activeListId: string }) {
  const today = useMemo(() => new Date(), []);
  const initialStart = toLocalInput(startOfDay(today));
  const initialEnd = toLocalInput(endOfDay(addDays(today, 7)));

  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(initialEnd);
  const [scope, setScope] = useState<"thisList" | "all">("thisList");
  const [dryRun, setDryRun] = useState(true);

  const optimize = useOptimize();
  const apply = useApplySnapshot();
  const write = useWriteSnapshot();
  const deleteWritten = useDeleteWritten();

  const errorMessage =
    (optimize.error as Error | undefined)?.message ??
    (apply.error as Error | undefined)?.message ??
    (write.error as Error | undefined)?.message ??
    (deleteWritten.error as Error | undefined)?.message ??
    null;

  const result = optimize.last;

  return (
    <Card className="p-4 space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">最適化</h2>
        {result && (
          <span className="text-xs text-gray-500">
            snapshot {result.snapshot_id.slice(0, 8)}… / {result.status}
            {" / "}
            {result.solve_time_sec.toFixed(2)}s
          </span>
        )}
      </header>
      <div className="flex flex-wrap gap-3">
        <div>
          <Label>開始</Label>
          <Input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="w-44"
          />
        </div>
        <div>
          <Label>終了</Label>
          <Input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="w-44"
          />
        </div>
        <div>
          <Label>対象</Label>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as "thisList" | "all")}
            className="border border-gray-300 rounded-md px-2 py-1 text-sm bg-white"
          >
            <option value="thisList">選択中のリストのみ</option>
            <option value="all">全リスト</option>
          </select>
        </div>
        <div className="ml-auto flex items-end">
          <Button
            variant="primary"
            disabled={optimize.isPending}
            onClick={() => {
              optimize.mutate({
                start: new Date(start).toISOString(),
                end: new Date(end).toISOString(),
                list_ids: scope === "thisList" ? [activeListId] : null,
              });
            }}
          >
            {optimize.isPending ? "計算中…" : "Optimize"}
          </Button>
        </div>
      </div>

      <ErrorBanner message={errorMessage} />

      {result && <ResultPreview result={result} />}

      {result && result.status !== "infeasible" && result.assignments.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-gray-200">
          <Button
            disabled={apply.isPending}
            onClick={() => apply.mutate(result.snapshot_id)}
          >
            {apply.isPending ? "Apply…" : "Apply to Tasks"}
          </Button>
          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            Dry-run
          </label>
          <Button
            variant="primary"
            disabled={write.isPending}
            onClick={() =>
              write.mutate({ snapshotId: result.snapshot_id, dryRun })
            }
          >
            {write.isPending
              ? "書き込み中…"
              : dryRun
                ? "Preview Calendar Write"
                : "Write to Calendar"}
          </Button>
          <Button
            variant="danger"
            disabled={deleteWritten.isPending}
            onClick={() => {
              if (confirm("カレンダー上のアプリ書き込みを全削除しますか？")) {
                deleteWritten.mutate(result.snapshot_id);
              }
            }}
          >
            Calendar から取消
          </Button>
        </div>
      )}

      {write.last && (
        <div className="text-xs text-gray-600 pt-2 border-t border-gray-200">
          {write.last.dry_run
            ? `Dry-run: ${write.last.deleted_event_count} 件削除予定 / ${write.last.created_events.length} 件作成予定`
            : `削除 ${write.last.deleted_event_count} 件 / 新規作成 ${write.last.created_events.length} 件`}
        </div>
      )}
    </Card>
  );
}

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function endOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(23, 59, 0, 0);
  return x;
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
