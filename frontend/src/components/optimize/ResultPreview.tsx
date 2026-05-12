import type { OptimizeResponse } from "../../api/types";

export function ResultPreview({ result }: { result: OptimizeResponse }) {
  if (result.status === "infeasible") {
    return (
      <div className="space-y-2">
        <div className="text-sm text-red-800 bg-red-50 border border-red-200 rounded-md px-3 py-2">
          <strong>infeasible</strong> — 締切タスクが配置不能です。期間を広げるか、
          該当タスクの締切を見直してください。
        </div>
        {result.notes.length > 0 && (
          <ul className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2 space-y-0.5">
            {result.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  if (result.assignments.length === 0) {
    return <div className="text-sm text-gray-500">割り当てなし。</div>;
  }
  return (
    <div className="space-y-3 text-sm">
      <ul className="space-y-2">
        {result.assignments.map((a) => (
          <li key={a.task_id} className="flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-3">
            <span className="font-medium text-gray-900 sm:w-48 sm:truncate">
              {a.task_title}
            </span>
            <span className="text-gray-600 flex-1 text-xs sm:text-sm">
              {a.fragments.map((f, i) => (
                <span key={i} className="mr-3 whitespace-nowrap">
                  {formatRange(f.start, f.duration_min)}
                </span>
              ))}
            </span>
            <span className="text-xs text-gray-400 sm:shrink-0">{a.total_assigned_min} min</span>
          </li>
        ))}
      </ul>
      {result.unassigned.length > 0 && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
          未配置: {result.unassigned.map((u) => u.task_title).join(", ")}
        </div>
      )}
      {result.notes.length > 0 && (
        <ul className="text-xs text-gray-500 space-y-0.5">
          {result.notes.map((n, i) => (
            <li key={i}>• {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatRange(startIso: string, durationMin: number): string {
  const s = new Date(startIso);
  const e = new Date(s.getTime() + durationMin * 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${pad(s.getMonth() + 1)}/${pad(s.getDate())}`;
  const time = `${pad(s.getHours())}:${pad(s.getMinutes())}–${pad(e.getHours())}:${pad(e.getMinutes())}`;
  return `${day} ${time}`;
}
