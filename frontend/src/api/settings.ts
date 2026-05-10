import { apiFetch } from "./client";
import type { SettingsRead, SettingsUpdate } from "./types";

export const settingsApi = {
  get: () => apiFetch<SettingsRead>("/settings"),
  update: (patch: SettingsUpdate) =>
    apiFetch<SettingsRead>("/settings", { method: "PUT", body: patch }),
  reset: () => apiFetch<SettingsRead>("/settings/reset", { method: "POST" }),
};
