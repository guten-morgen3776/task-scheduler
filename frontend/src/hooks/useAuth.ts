import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi } from "../api/auth";
import { ApiError } from "../api/client";

export function useAuthMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: authApi.me,
    retry: (count, err) => {
      if (err instanceof ApiError && err.status === 401) return false;
      return count < 1;
    },
  });
}

export function useStartLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.startGoogleLocalFlow,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth", "me"] }),
  });
}

export function useStartWebLogin() {
  return useMutation({
    mutationFn: authApi.startGoogleWebFlow,
    onSuccess: (data) => {
      // Full-page navigation to Google's consent screen. After authorization
      // Google redirects back to the backend callback, which then redirects
      // to the configured frontend URL — at which point useAuthMe refetches.
      window.location.href = data.authorize_url;
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => qc.invalidateQueries(),
  });
}
