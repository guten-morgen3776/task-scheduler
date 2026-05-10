import type { OptimizeResponse } from "../../api/types";

export function ResultPreview({ result }: { result: OptimizeResponse }) {
  if (result.status === "infeasible") {
    return (
      <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
        infeasible — タスクが期間内に収まりません。期間を広げるか、タスク量を減らしてください。
      </div>
    );
  }
  if (result.assignments.length === 0) {
    return <div className="text-sm text-gray-500">割り当てなし。</div>;
  }
  return (
    <div className="space-y-3 text-sm">
      <ul className="space-y-1.5">
        {result.assignments.map((a) => (
          <li key={a.task_id} className="flex items-baseline gap-3">
            <span className="font-medium text-gray-900 w-48 truncate">
              {a.task_title}
            </span>
            <span className="text-gray-600 flex-1">
              {a.fragments.map((f, i) => (
                <span key={i} className="mr-3 whitespace-nowrap">
                  {formatRange(f.start, f.duration_min)}
                </span>
              ))}
            </span>
            <span className="text-xs text-gray-400">{a.total_assigned_min} min</span>
          </li>
        ))}
      </ul>
      {result.unassigned.length > 0 && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
          未配置: {result.unassigned.map((u) => u.task_title).join(", ")}
        </div>
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
