import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settingsApi } from "../api/settings";
import type { SettingsUpdate } from "../api/types";
import { Header } from "../components/layout/Header";
import { Card, ErrorBanner } from "../components/ui";
import { WorkHoursForm } from "../components/settings/WorkHoursForm";
import { CommutesForm } from "../components/settings/CommutesForm";
import { VoluntaryVisitForm } from "../components/settings/VoluntaryVisitForm";

export function SettingsPage() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: settingsApi.get,
  });
  const update = useMutation({
    mutationFn: (patch: SettingsUpdate) => settingsApi.update(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <div className="max-w-4xl w-full mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4 sm:space-y-6">
        {isLoading && <div className="text-sm text-gray-500">読み込み中…</div>}
        {error && <ErrorBanner message={(error as Error).message} />}
        {data && (
          <>
            <Card className="p-4 space-y-3">
              <h2 className="text-base font-semibold">作業時間</h2>
              <WorkHoursForm
                value={data.work_hours}
                onSave={(work_hours) => update.mutate({ work_hours })}
                saving={update.isPending}
              />
            </Card>

            <Card className="p-4 space-y-3">
              <h2 className="text-base font-semibold">通学/通勤・linger</h2>
              <CommutesForm
                value={data.location_commutes}
                onSave={(location_commutes) => update.mutate({ location_commutes })}
                saving={update.isPending}
              />
            </Card>

            <Card className="p-4 space-y-3">
              <h2 className="text-base font-semibold">自発的に通う場所</h2>
              <VoluntaryVisitForm
                value={data.voluntary_visit_locations}
                onSave={(voluntary_visit_locations) =>
                  update.mutate({ voluntary_visit_locations })
                }
                saving={update.isPending}
              />
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
