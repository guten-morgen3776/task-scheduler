import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  useAuthMe,
  useStartLogin,
  useStartWebLogin,
} from "../hooks/useAuth";
import { Button, Card, ErrorBanner } from "../components/ui";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: me } = useAuthMe();
  const webLogin = useStartWebLogin();
  const localLogin = useStartLogin();

  useEffect(() => {
    if (me) navigate("/", { replace: true });
  }, [me, navigate]);

  const params = new URLSearchParams(location.search);
  const callbackError = params.get("error");
  const callbackDetail = params.get("detail");

  const errorMessage =
    (webLogin.error instanceof Error ? webLogin.error.message : null) ??
    (localLogin.error instanceof Error ? localLogin.error.message : null) ??
    (callbackError
      ? `OAuth error: ${callbackError}${callbackDetail ? ` (${callbackDetail})` : ""}`
      : null);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-md p-8 space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold text-gray-900">task-scheduler</h1>
          <p className="text-sm text-gray-600">
            Google アカウントでログインしてカレンダーと連携します。
          </p>
        </header>
        <Button
          variant="primary"
          className="w-full justify-center py-2"
          disabled={webLogin.isPending}
          onClick={() => webLogin.mutate()}
        >
          {webLogin.isPending ? "Google に遷移中…" : "Google でログイン"}
        </Button>
        <ErrorBanner message={errorMessage} />
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer">ローカル開発用ログイン</summary>
          <div className="mt-2 space-y-2">
            <p>
              Mac で backend を起動している場合のみ動作（InstalledAppFlow が
              localhost にブラウザを開きます）。本番では使えません。
            </p>
            <Button
              className="w-full justify-center"
              disabled={localLogin.isPending}
              onClick={() => localLogin.mutate()}
            >
              {localLogin.isPending ? "ブラウザで認可中…" : "ローカル Flow でログイン"}
            </Button>
          </div>
        </details>
      </Card>
    </div>
  );
}
