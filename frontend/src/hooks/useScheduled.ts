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

export function useToggleFixed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fixed }: { id: string; fixed: boolean }) =>
      tasksApi.update(id, { scheduled_fixed: fixed }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}
