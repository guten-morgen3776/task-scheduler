import { useEffect, useState } from "react";
import { Header } from "../components/layout/Header";
import { TaskListSidebar } from "../components/task/TaskListSidebar";
import { TaskTable } from "../components/task/TaskTable";
import { AddTaskForm } from "../components/task/AddTaskForm";
import { OptimizePanel } from "../components/optimize/OptimizePanel";
import { CurrentSchedulePanel } from "../components/schedule/CurrentSchedulePanel";
import { useLists } from "../hooks/useLists";

export function MainPage() {
  const { data: lists } = useLists();
  const [activeListId, setActiveListId] = useState<string | null>(null);

  // Auto-select the first list once they load.
  useEffect(() => {
    if (!activeListId && lists && lists.length > 0) {
      setActiveListId(lists[0].id);
    }
  }, [lists, activeListId]);

  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <div className="flex-1 max-w-6xl w-full mx-auto px-4 py-6 flex gap-6">
        <aside className="w-56 shrink-0">
          <TaskListSidebar
            activeId={activeListId}
            onSelect={setActiveListId}
          />
        </aside>
        <main className="flex-1 space-y-6 min-w-0">
          <section>
            <CurrentSchedulePanel />
          </section>
          {activeListId ? (
            <>
              <section>
                <AddTaskForm listId={activeListId} />
              </section>
              <section>
                <TaskTable listId={activeListId} />
              </section>
              <section>
                <OptimizePanel activeListId={activeListId} />
              </section>
            </>
          ) : (
            <div className="text-gray-500 text-sm">
              リストを作成・選択してください。
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
