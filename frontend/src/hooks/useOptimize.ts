import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { optimizeApi } from "../api/optimize";
import type { OptimizeRequest, OptimizeResponse, WriteResponse } from "../api/types";

export function useOptimize() {
  const [last, setLast] = useState<OptimizeResponse | null>(null);
  const m = useMutation({
    mutationFn: (req: OptimizeRequest) => optimizeApi.optimize(req),
    onSuccess: (res) => setLast(res),
  });
  return { ...m, last, clear: () => setLast(null) };
}

export function useApplySnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (snapshotId: string) => optimizeApi.apply(snapshotId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useWriteSnapshot() {
  const qc = useQueryClient();
  const [last, setLast] = useState<WriteResponse | null>(null);
  const m = useMutation({
    mutationFn: ({
      snapshotId,
      dryRun,
    }: {
      snapshotId: string;
      dryRun: boolean;
    }) => optimizeApi.write(snapshotId, { dry_run: dryRun }),
    onSuccess: (res) => {
      setLast(res);
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  return { ...m, last, clear: () => setLast(null) };
}

export function useDeleteWritten() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (snapshotId: string) => optimizeApi.deleteWritten(snapshotId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}
