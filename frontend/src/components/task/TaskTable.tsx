import { useState } from "react";
import { clsx } from "clsx";
import {
  useDeleteTask,
  useTasks,
  useToggleComplete,
  useUpdateTask,
} from "../../hooks/useTasks";
import type { Location, Task, TaskUpdate } from "../../api/types";
import { Button, Card, ErrorBanner, Input, Label, Select } from "../ui";

const LOCATIONS: (Location | "")[] = ["", "home", "university", "office", "anywhere"];

export function TaskTable({ listId }: { listId: string }) {
  const [includeCompleted, setIncludeCompleted] = useState(false);
  const { data, isLoading, error } = useTasks(listId, includeCompleted);
  const update = useUpdateTask(listId);
  const toggle = useToggleComplete(listId);
  const remove = useDeleteTask(listId);

  return (
    <Card className="overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50">
        <span className="text-sm font-medium text-gray-700">タスク</span>
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          <input
            type="checkbox"
            checked={includeCompleted}
            onChange={(e) => setIncludeCompleted(e.target.checked)}
          />
          完了済みも表示
        </label>
      </header>
      {error && <ErrorBanner message={(error as Error).message} />}
      {isLoading ? (
        <div className="p-4 text-sm text-gray-500">読み込み中…</div>
      ) : !data || data.length === 0 ? (
        <div className="p-4 text-sm text-gray-500">タスクがありません。</div>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              onPatch={(patch) => update.mutate({ id: task.id, patch })}
              onToggle={() =>
                toggle.mutate({ id: task.id, completed: !task.completed })
              }
              onRemove={() => {
                if (confirm(`「${task.title}」を削除しますか？`)) {
                  remove.mutate(task.id);
                }
              }}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function TaskRow({
  task,
  onPatch,
  onToggle,
  onRemove,
}: {
  task: Task;
  onPatch: (patch: TaskUpdate) => void;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className={clsx("group", task.completed && "opacity-60")}>
      <div className="flex items-center gap-2 px-3 py-3 sm:py-2.5">
        <input
          type="checkbox"
          checked={task.completed}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          className="h-4 w-4 shrink-0"
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 min-w-0 flex items-center gap-2 text-left"
        >
          <span
            className={clsx(
              "truncate text-sm",
              task.completed
                ? "line-through text-gray-500"
                : "text-gray-900",
            )}
          >
            {task.title}
          </span>
          <Meta task={task} />
          <Chevron open={open} />
        </button>
      </div>
      {open && (
        <Details
          task={task}
          onPatch={onPatch}
          onRemove={onRemove}
        />
      )}
    </li>
  );
}

function Meta({ task }: { task: Task }) {
  const bits: string[] = [];
  bits.push(`${task.duration_min}m`);
  if (task.priority !== 3) bits.push(`★${task.priority}`);
  if (task.location && task.location !== "anywhere") bits.push(task.location);
  if (task.scheduled_start)
    bits.push(`📅 ${formatScheduled(task.scheduled_start)}`);
  return (
    <span className="ml-auto text-xs text-gray-500 whitespace-nowrap shrink-0">
      {bits.join(" · ")}
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span
      className={clsx(
        "ml-2 text-gray-400 transition-transform shrink-0",
        open && "rotate-180",
      )}
    >
      ▾
    </span>
  );
}

function Details({
  task,
  onPatch,
  onRemove,
}: {
  task: Task;
  onPatch: (patch: TaskUpdate) => void;
  onRemove: () => void;
}) {
  return (
    <div className="px-3 pb-4 pt-1 bg-gray-50/60 border-t border-gray-100">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-2xl">
        <Field label="タイトル" className="col-span-2 sm:col-span-4">
          <InlineText
            value={task.title}
            onCommit={(v) => v !== task.title && v.trim() !== "" && onPatch({ title: v })}
            className="w-full"
          />
        </Field>
        <Field label="所要時間 (分)">
          <InlineNumber
            value={task.duration_min}
            onCommit={(v) =>
              v !== task.duration_min && onPatch({ duration_min: v })
            }
          />
        </Field>
        <Field label="優先度">
          <Select
            value={String(task.priority)}
            onChange={(e) => {
              const next = Number(e.target.value);
              if (next !== task.priority) onPatch({ priority: next });
            }}
            className="w-full"
          >
            {[1, 2, 3, 4, 5].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="場所">
          <Select
            value={task.location ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              const next = v === "" ? null : (v as Location);
              if (next !== task.location) onPatch({ location: next });
            }}
            className="w-full"
          >
            {LOCATIONS.map((l) => (
              <option key={l} value={l}>
                {l === "" ? "—" : l}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="締切">
          <InlineDateTime
            isoValue={task.deadline}
            onCommit={(iso) => onPatch({ deadline: iso })}
          />
        </Field>
        <Field label="予定" className="col-span-2 sm:col-span-4">
          <ScheduledDisplay task={task} />
        </Field>
      </div>
      <div className="mt-3 flex justify-end">
        <Button variant="danger" onClick={onRemove}>
          削除
        </Button>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex flex-col gap-1", className)}>
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function InlineText({
  value,
  onCommit,
  className,
}: {
  value: string;
  onCommit: (v: string) => void;
  className?: string;
}) {
  const [v, setV] = useState(value);
  return (
    <Input
      className={className}
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => onCommit(v.trim())}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

function InlineNumber({
  value,
  onCommit,
}: {
  value: number;
  onCommit: (v: number) => void;
}) {
  const [v, setV] = useState(String(value));
  return (
    <Input
      type="number"
      min={5}
      max={720}
      step={5}
      className="w-full"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        const n = Number(v);
        if (!Number.isNaN(n)) onCommit(n);
      }}
    />
  );
}

function InlineDateTime({
  isoValue,
  onCommit,
}: {
  isoValue: string | null;
  onCommit: (iso: string | null) => void;
}) {
  const local = isoValue ? toLocalInput(isoValue) : "";
  const [v, setV] = useState(local);
  return (
    <Input
      type="datetime-local"
      className="w-full"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        if (v === "") {
          if (isoValue !== null) onCommit(null);
          return;
        }
        const iso = new Date(v).toISOString();
        if (iso !== isoValue) onCommit(iso);
      }}
    />
  );
}

function ScheduledDisplay({ task }: { task: Task }) {
  const fragments =
    task.scheduled_fragments && task.scheduled_fragments.length > 0
      ? task.scheduled_fragments
      : task.scheduled_start && task.scheduled_end
        ? [{ start: task.scheduled_start, end: task.scheduled_end }]
        : [];
  if (fragments.length === 0) {
    return <span className="text-xs text-gray-500">未配置</span>;
  }
  return (
    <ul className="space-y-0.5">
      {fragments.map((f, i) => (
        <li key={i} className="text-xs text-gray-700 tabular-nums">
          {formatFragment(f.start, f.end)}
        </li>
      ))}
    </ul>
  );
}

function formatFragment(startIso: string, endIso: string): string {
  const s = new Date(startIso);
  const e = new Date(endIso);
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${pad(s.getMonth() + 1)}/${pad(s.getDate())}`;
  return `${day} ${pad(s.getHours())}:${pad(s.getMinutes())}〜${pad(e.getHours())}:${pad(e.getMinutes())}`;
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatScheduled(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
