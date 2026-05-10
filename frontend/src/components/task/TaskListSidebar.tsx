import { useState } from "react";
import { clsx } from "clsx";
import { useCreateList, useDeleteList, useLists } from "../../hooks/useLists";
import { Button, ErrorBanner, Input } from "../ui";

export function TaskListSidebar({
  activeId,
  onSelect,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data: lists, isLoading, error } = useLists();
  const create = useCreateList();
  const remove = useDeleteList();
  const [newTitle, setNewTitle] = useState("");

  return (
    <div className="space-y-3">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        リスト
      </div>
      {isLoading && <div className="text-xs text-gray-500">読み込み中…</div>}
      {error && <ErrorBanner message={(error as Error).message} />}
      <ul className="space-y-1">
        {lists?.map((list) => (
          <li key={list.id} className="flex items-center group">
            <button
              type="button"
              onClick={() => onSelect(list.id)}
              className={clsx(
                "flex-1 text-left text-sm px-2 py-1.5 rounded-md flex items-center gap-2",
                activeId === list.id
                  ? "bg-indigo-50 text-indigo-800 font-medium"
                  : "text-gray-700 hover:bg-gray-100",
              )}
            >
              <span className="truncate">{list.title}</span>
              <span className="text-xs text-gray-400 ml-auto">
                {list.task_count - list.completed_count}
              </span>
            </button>
            <button
              type="button"
              className="opacity-0 group-hover:opacity-100 text-xs text-gray-400 hover:text-red-600 px-1"
              onClick={() => {
                if (confirm(`「${list.title}」とその配下タスクを削除しますか？`)) {
                  remove.mutate(list.id);
                }
              }}
              title="リスト削除"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-1.5 pt-2 border-t border-gray-200"
        onSubmit={(e) => {
          e.preventDefault();
          if (!newTitle.trim()) return;
          create.mutate(newTitle.trim(), {
            onSuccess: (created) => {
              setNewTitle("");
              onSelect(created.id);
            },
          });
        }}
      >
        <Input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="新規リスト"
          className="flex-1"
        />
        <Button type="submit" disabled={!newTitle.trim() || create.isPending}>
          +
        </Button>
      </form>
    </div>
  );
}
