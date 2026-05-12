import { Link, useLocation } from "react-router-dom";
import { useAuthMe, useLogout } from "../../hooks/useAuth";
import { Button } from "../ui";

export function Header() {
  const { data: me } = useAuthMe();
  const logout = useLogout();
  const { pathname } = useLocation();
  return (
    <header className="border-b border-gray-200 bg-white sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-3 sm:px-4 py-2 sm:py-3 flex items-center gap-3 sm:gap-6">
        <Link to="/" className="font-semibold text-gray-900 text-sm sm:text-base shrink-0">
          tasks
        </Link>
        <nav className="flex gap-3 sm:gap-4 text-sm">
          <Link
            to="/"
            className={pathname === "/" ? "text-indigo-700 font-medium" : "text-gray-600"}
          >
            メイン
          </Link>
          <Link
            to="/settings"
            className={pathname === "/settings" ? "text-indigo-700 font-medium" : "text-gray-600"}
          >
            設定
          </Link>
        </nav>
        <div className="flex-1" />
        {me && (
          <span className="hidden md:inline text-xs text-gray-500 truncate max-w-[12rem]">
            {me.google_email ?? me.user_id.slice(0, 8)}
          </span>
        )}
        {me && (
          <Button
            variant="ghost"
            className="text-xs sm:text-sm px-2 sm:px-3"
            onClick={() => {
              logout.mutate(undefined, {
                onSuccess: () => {
                  window.location.href = "/login";
                },
              });
            }}
          >
            ログアウト
          </Button>
        )}
      </div>
    </header>
  );
}
