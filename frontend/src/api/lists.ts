import { apiFetch } from "./client";
import type { TaskList } from "./types";

export const listsApi = {
  list: () => apiFetch<TaskList[]>("/lists"),
  get: (id: string) => apiFetch<TaskList>(`/lists/${id}`),
  create: (title: string) =>
    apiFetch<TaskList>("/lists", { method: "POST", body: { title } }),
  update: (id: string, patch: { title?: string; position?: string }) =>
    apiFetch<TaskList>(`/lists/${id}`, { method: "PATCH", body: patch }),
  remove: (id: string) =>
    apiFetch<void>(`/lists/${id}`, { method: "DELETE" }),
};
