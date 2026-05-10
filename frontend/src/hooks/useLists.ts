import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listsApi } from "../api/lists";

export function useLists() {
  return useQuery({ queryKey: ["lists"], queryFn: listsApi.list });
}

export function useCreateList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => listsApi.create(title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lists"] }),
  });
}

export function useDeleteList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => listsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lists"] }),
  });
}

export function useUpdateList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      listsApi.update(id, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lists"] }),
  });
}
