import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tasksApi } from "../api/tasks";

export function useScheduled(start?: string, end?: string) {
  return useQuery({
    queryKey: ["tasks", "scheduled", { start, end }],
    queryFn: () => tasksApi.scheduled(start, end),
  });
}

export function useSyncFromCalendar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => tasksApi.syncFromCalendar(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}
