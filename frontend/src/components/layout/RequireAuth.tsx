import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuthMe } from "../../hooks/useAuth";
import { ApiError } from "../../api/client";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data, isLoading, error } = useAuthMe();
  if (isLoading) {
    return <div className="p-8 text-gray-500">Loading…</div>;
  }
  if (error instanceof ApiError && error.status === 401) {
    return <Navigate to="/login" replace />;
  }
  if (!data) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
