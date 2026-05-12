import { useMemo } from "react";
import { clsx } from "clsx";
import {
  useScheduled,
  useSyncFromCalendar,
  useToggleFixed,
} from "../../hooks/useScheduled";
import type { Task } from "../../api/types";
import { Button, Card, ErrorBanner } from "../ui";

interface ScheduleEntry {
  taskId: string;
  title: string;
  completed: boolean;
  fixed: boolean;
  start: Date;
  end: Date;
  fragmentIndex: number;
  fragmentCount: number;
}

export function CurrentSchedulePanel() {
  // Fixed window: today 00:00 → today + 7d 23:59 (local).
  const { startIso, endIso, todayKey, windowStart, windowEnd } = useMemo(() => {
    const now = new Date();
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 8); // exclusive upper bound for "next 7 days"
    return {
      startIso: start.toISOString(),
      endIso: end.toISOString(),
      todayKey: dateKey(start),
      windowStart: start,
      windowEnd: end,
    };
  }, []);

  const { data, isLoading, error, refetch } = useScheduled(startIso, endIso);
  const sync = useSyncFromCalendar();
  const toggleFixed = useToggleFixed();

  const grouped = useMemo(
    () => groupEntriesByLocalDate(toScheduleEntries(data ?? [], windowStart, windowEnd)),
    [data, windowStart, windowEnd],
  );
  const dayKeys = Object.keys(grouped).sort();

  const errMessage =
    (error as Error | undefined)?.message ??
    (sync.error as Error | undefined)?.message ??
    null;

  return (
    <Card className="p-3 sm:p-4 space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-gray-900">現在のスケジュール</h2>
        <div className="flex items-center gap-2 ml-auto">
          <span className="hidden sm:inline text-xs text-gray-500">今日〜7日後</span>
          <Button
            className="text-xs sm:text-sm"
            disabled={sync.isPending}
            onClick={async () => {
              await sync.mutateAsync();
              await refetch();
            }}
            title="Google Calendar を見て scheduled_* を上書きする"
          >
            {sync.isPending ? "同期中…" : "Calendar から同期"}
          </Button>
        </div>
      </header>

      <ErrorBanner message={errMessage} />
      {sync.data && (
        <div className="text-xs text-gray-600">
          {sync.data.event_count} 件取得・{sync.data.updated_task_count} 件更新
          {sync.data.cleared_task_count > 0 &&
            `・${sync.data.cleared_task_count} 件クリア`}
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-gray-500">読み込み中…</div>
      ) : dayKeys.length === 0 ? (
        <div className="text-sm text-gray-500">
          配置済みタスクはありません。Optimize と Apply を実行すると埋まります。
        </div>
      ) : (
        <ul className="space-y-3">
          {dayKeys.map((key) => (
            <li key={key}>
              <div className="text-xs font-medium text-gray-500 mb-1">
                {formatDateLabel(key, todayKey)}
              </div>
              <ul className="space-y-1">
                {grouped[key].map((entry) => (
                  <li
                    key={`${entry.taskId}-${entry.fragmentIndex}`}
                    className="flex items-baseline gap-2 text-sm"
                  >
                    <span className="text-gray-500 tabular-nums w-20 sm:w-24 shrink-0 text-xs sm:text-sm">
                      {formatRange(entry.start, entry.end)}
                    </span>
                    <span
                      className={clsx(
                        "flex-1 min-w-0",
                        entry.completed
                          ? "line-through text-gray-400"
                          : "text-gray-900",
                      )}
                    >
                      {entry.title}
                      {entry.fragmentCount > 1 && (
                        <span className="ml-1 text-xs text-gray-400">
                          ({entry.fragmentIndex + 1}/{entry.fragmentCount})
                        </span>
                      )}
                    </span>
                    <button
                      type="button"
                      className={clsx(
                        "shrink-0 text-xs px-2 py-0.5 rounded-md border transition",
                        entry.fixed
                          ? "bg-amber-50 border-amber-300 text-amber-800"
                          : "bg-white border-gray-200 text-gray-400 hover:text-gray-700 hover:border-gray-300",
                      )}
                      onClick={() =>
                        toggleFixed.mutate({
                          id: entry.taskId,
                          fixed: !entry.fixed,
                        })
                      }
                      disabled={toggleFixed.isPending}
                      title={
                        entry.fixed
                          ? "再最適化で動かないように固定中。クリックで解除"
                          : "クリックして固定（再最適化で動かない）"
                      }
                    >
                      {entry.fixed ? "🔒 fixed" : "fix"}
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function toScheduleEntries(
  tasks: Task[],
  windowStart: Date,
  windowEnd: Date,
): ScheduleEntry[] {
  const out: ScheduleEntry[] = [];
  for (const t of tasks) {
    const fragments =
      t.scheduled_fragments && t.scheduled_fragments.length > 0
        ? t.scheduled_fragments.map((f) => ({
            start: new Date(f.start),
            end: new Date(f.end),
          }))
        : t.scheduled_start
          ? [
              {
                start: new Date(t.scheduled_start),
                end: t.scheduled_end ? new Date(t.scheduled_end) : new Date(t.scheduled_start),
              },
            ]
          : [];
    fragments.sort((a, b) => a.start.getTime() - b.start.getTime());
    fragments.forEach((f, idx) => {
      // Window filter: include if the fragment's start is in [windowStart, windowEnd).
      if (f.start < windowStart || f.start >= windowEnd) return;
      out.push({
        taskId: t.id,
        title: t.title,
        completed: t.completed,
        fixed: t.scheduled_fixed,
        start: f.start,
        end: f.end,
        fragmentIndex: idx,
        fragmentCount: fragments.length,
      });
    });
  }
  out.sort((a, b) => a.start.getTime() - b.start.getTime());
  return out;
}

function groupEntriesByLocalDate(
  entries: ScheduleEntry[],
): Record<string, ScheduleEntry[]> {
  const out: Record<string, ScheduleEntry[]> = {};
  for (const e of entries) {
    const key = dateKey(e.start);
    (out[key] ??= []).push(e);
  }
  return out;
}

function dateKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function formatDateLabel(key: string, todayKey: string): string {
  const [, m, d] = key.split("-").map(Number);
  const dt = new Date(`${key}T00:00:00`);
  const dayLabels = ["日", "月", "火", "水", "木", "金", "土"];
  const wd = dayLabels[dt.getDay()];
  const todayBadge = key === todayKey ? "（今日）" : "";
  return `${m}/${d}（${wd}）${todayBadge}`;
}

function formatRange(start: Date, end: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(start.getHours())}:${pad(start.getMinutes())}–${pad(end.getHours())}:${pad(end.getMinutes())}`;
}
