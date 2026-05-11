import { apiFetch } from "./client";
import type { AuthMe } from "./types";

export const authApi = {
  me: () =>
    apiFetch<AuthMe>("/auth/me", { method: "GET", skipAuthRedirect: true }),
  /** Local dev: opens browser on the host machine via InstalledAppFlow. */
  startGoogleLocalFlow: () =>
    apiFetch<AuthMe>("/auth/google/local", {
      method: "POST",
      skipAuthRedirect: true,
    }),
  /** Production / web: fetch the Google authorization URL and navigate to it. */
  startGoogleWebFlow: () =>
    apiFetch<{ authorize_url: string }>("/auth/google/start", {
      method: "GET",
      skipAuthRedirect: true,
    }),
  logout: () =>
    apiFetch<void>("/auth/google", {
      method: "DELETE",
      skipAuthRedirect: true,
    }),
};
