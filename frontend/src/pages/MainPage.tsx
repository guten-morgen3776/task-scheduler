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
      <div className="flex-1 max-w-6xl w-full mx-auto px-3 py-4 sm:px-4 sm:py-6 flex flex-col md:flex-row gap-4 md:gap-6">
        <aside className="w-full md:w-56 md:shrink-0">
          <TaskListSidebar
            activeId={activeListId}
            onSelect={setActiveListId}
          />
        </aside>
        <main className="flex-1 space-y-4 sm:space-y-6 min-w-0">
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
