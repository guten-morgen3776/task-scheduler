import { apiFetch } from "./client";
import type { Task, TaskCreate, TaskUpdate } from "./types";

export const tasksApi = {
  listInList: (listId: string, includeCompleted = false) =>
    apiFetch<Task[]>(
      `/lists/${listId}/tasks${includeCompleted ? "?include_completed=true" : ""}`,
    ),
  get: (id: string) => apiFetch<Task>(`/tasks/${id}`),
  create: (listId: string, data: TaskCreate) =>
    apiFetch<Task>(`/lists/${listId}/tasks`, { method: "POST", body: data }),
  update: (id: string, patch: TaskUpdate) =>
    apiFetch<Task>(`/tasks/${id}`, { method: "PATCH", body: patch }),
  complete: (id: string) =>
    apiFetch<Task>(`/tasks/${id}/complete`, { method: "POST" }),
  uncomplete: (id: string) =>
    apiFetch<Task>(`/tasks/${id}/uncomplete`, { method: "POST" }),
  remove: (id: string) =>
    apiFetch<void>(`/tasks/${id}`, { method: "DELETE" }),
  move: (id: string, body: { list_id?: string; position?: string }) =>
    apiFetch<Task>(`/tasks/${id}/move`, { method: "POST", body }),
  scheduled: (start?: string, end?: string) => {
    const qs = new URLSearchParams();
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return apiFetch<Task[]>(`/tasks/scheduled${suffix}`);
  },
  syncFromCalendar: () =>
    apiFetch<{
      updated_task_count: number;
      cleared_task_count: number;
      event_count: number;
    }>("/tasks/sync-from-calendar", { method: "POST" }),
};
