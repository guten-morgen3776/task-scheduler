import { apiFetch } from "./client";
import type { AuthMe } from "./types";

export const authApi = {
  me: () =>
    apiFetch<AuthMe>("/auth/me", { method: "GET", skipAuthRedirect: true }),
  startGoogleLocalFlow: () =>
    apiFetch<AuthMe>("/auth/google/local", {
      method: "POST",
      skipAuthRedirect: true,
    }),
  logout: () =>
    apiFetch<void>("/auth/google", {
      method: "DELETE",
      skipAuthRedirect: true,
    }),
};
