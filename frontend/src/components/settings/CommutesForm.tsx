import { useEffect, useState } from "react";
import type { Location, LocationCommute } from "../../api/types";
import { Button, Input } from "../ui";

const LOCATIONS: Location[] = ["home", "university", "office", "anywhere"];

type CommuteMap = Partial<Record<Location, LocationCommute>>;

export function CommutesForm({
  value,
  onSave,
  saving,
}: {
  value: CommuteMap;
  onSave: (next: CommuteMap) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<CommuteMap>(value);
  useEffect(() => setDraft(value), [value]);

  const updateLoc = (loc: Location, patch: Partial<LocationCommute>) => {
    const current: LocationCommute = draft[loc] ?? {
      to_min: 0,
      from_min: 0,
      linger_after_min: 0,
    };
    setDraft({ ...draft, [loc]: { ...current, ...patch } });
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        場所ごとの片道の通学/通勤時間と linger（最後の予定後にその場所に滞在する分数）を設定します。
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-500">
            <th className="text-left py-1 w-28">場所</th>
            <th className="text-left py-1 w-28">片道(分)</th>
            <th className="text-left py-1 w-28">linger(分)</th>
          </tr>
        </thead>
        <tbody>
          {LOCATIONS.map((loc) => {
            const c = draft[loc];
            return (
              <tr key={loc} className="border-t border-gray-100">
                <td className="py-2 text-gray-800">{loc}</td>
                <td className="py-2">
                  <Input
                    type="number"
                    min={0}
                    max={240}
                    value={c?.to_min ?? 0}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      updateLoc(loc, { to_min: n, from_min: n });
                    }}
                    className="w-20"
                  />
                </td>
                <td className="py-2">
                  <Input
                    type="number"
                    min={0}
                    max={480}
                    value={c?.linger_after_min ?? 0}
                    onChange={(e) =>
                      updateLoc(loc, {
                        linger_after_min: Number(e.target.value),
                      })
                    }
                    className="w-20"
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="flex justify-end">
        <Button
          variant="primary"
          disabled={saving}
          onClick={() => {
            // Drop entries that are entirely zero so backend keeps default behavior tight.
            const cleaned: CommuteMap = {};
            for (const loc of LOCATIONS) {
              const c = draft[loc];
              if (
                c &&
                (c.to_min > 0 || c.from_min > 0 || c.linger_after_min > 0)
              ) {
                // Mirror to_min onto from_min in case the underlying record was loaded
                // with asymmetric values from before this UI consolidation.
                cleaned[loc] = { ...c, from_min: c.to_min };
              }
            }
            onSave(cleaned);
          }}
        >
          {saving ? "保存中…" : "保存"}
        </Button>
      </div>
    </div>
  );
}
