import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tasksApi } from "../api/tasks";
import type { TaskCreate, TaskUpdate } from "../api/types";

export function useTasks(listId: string | null, includeCompleted = false) {
  return useQuery({
    queryKey: ["tasks", listId, { includeCompleted }],
    queryFn: () => tasksApi.listInList(listId!, includeCompleted),
    enabled: !!listId,
  });
}

export function useCreateTask(listId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TaskCreate) => tasksApi.create(listId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", listId] });
      qc.invalidateQueries({ queryKey: ["lists"] });
    },
  });
}

export function useUpdateTask(listId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: TaskUpdate }) =>
      tasksApi.update(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", listId] }),
  });
}

export function useToggleComplete(listId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, completed }: { id: string; completed: boolean }) =>
      completed ? tasksApi.complete(id) : tasksApi.uncomplete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", listId] });
      qc.invalidateQueries({ queryKey: ["lists"] });
    },
  });
}

export function useDeleteTask(listId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tasksApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", listId] });
      qc.invalidateQueries({ queryKey: ["lists"] });
    },
  });
}
