import { apiFetch } from "./client";
import type { OptimizeRequest, OptimizeResponse, WriteResponse } from "./types";

export const optimizeApi = {
  optimize: (req: OptimizeRequest) =>
    apiFetch<OptimizeResponse>("/optimize", { method: "POST", body: req }),
  apply: (snapshotId: string) =>
    apiFetch<{ updated_task_count: number; snapshot_id: string }>(
      `/optimizer/snapshots/${snapshotId}/apply`,
      { method: "POST" },
    ),
  write: (
    snapshotId: string,
    opts: { dry_run: boolean; target_calendar_id?: string } = { dry_run: false },
  ) =>
    apiFetch<WriteResponse>(`/optimizer/snapshots/${snapshotId}/write`, {
      method: "POST",
      body: opts,
    }),
  deleteWritten: (snapshotId: string, onlyThisSnapshot = false) =>
    apiFetch<{ deleted_event_count: number; target_calendar_id: string }>(
      `/optimizer/snapshots/${snapshotId}/write?only_this_snapshot=${onlyThisSnapshot}`,
      { method: "DELETE" },
    ),
};
