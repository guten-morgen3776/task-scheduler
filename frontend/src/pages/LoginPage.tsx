import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthMe, useStartLogin } from "../hooks/useAuth";
import { Button, Card, ErrorBanner } from "../components/ui";

export function LoginPage() {
  const navigate = useNavigate();
  const { data: me } = useAuthMe();
  const start = useStartLogin();

  useEffect(() => {
    if (me) navigate("/", { replace: true });
  }, [me, navigate]);

  const errorMessage = start.error instanceof Error ? start.error.message : null;

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
          disabled={start.isPending}
          onClick={() => start.mutate()}
        >
          {start.isPending ? "ブラウザで認可中…" : "Google でログイン"}
        </Button>
        <ErrorBanner message={errorMessage} />
        <p className="text-xs text-gray-500">
          ボタンを押すとローカルマシン上でブラウザが開き、Google の認可画面に遷移します。
        </p>
      </Card>
    </div>
  );
}
