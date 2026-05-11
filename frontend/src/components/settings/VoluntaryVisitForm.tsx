import { useEffect, useState } from "react";
import type { Location } from "../../api/types";
import { Button } from "../ui";

const CANDIDATES: { value: Location; label: string }[] = [
  { value: "university", label: "university" },
  { value: "office", label: "office" },
];

export function VoluntaryVisitForm({
  value,
  onSave,
  saving,
}: {
  value: Location[];
  onSave: (next: Location[]) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<Set<Location>>(new Set(value));
  useEffect(() => setDraft(new Set(value)), [value]);

  const toggle = (loc: Location) => {
    const next = new Set(draft);
    if (next.has(loc)) {
      next.delete(loc);
    } else {
      next.add(loc);
    }
    setDraft(next);
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        ON にした場所は、その場所指定のタスクが既存の予定だけで収まらないときに
        「暇な日に自発的に通学/通勤して片付ける」候補として最適化に組み込まれます。
        必要な日数だけ自動で追加され、不要なら通学/通勤は発生しません。
      </p>
      <div className="flex flex-wrap gap-2">
        {CANDIDATES.map((c) => {
          const on = draft.has(c.value);
          return (
            <button
              type="button"
              key={c.value}
              onClick={() => toggle(c.value)}
              className={
                on
                  ? "px-3 py-1.5 rounded-md text-sm border border-indigo-300 bg-indigo-50 text-indigo-800"
                  : "px-3 py-1.5 rounded-md text-sm border border-gray-200 bg-white text-gray-600 hover:border-gray-300"
              }
            >
              {on ? "✓ " : ""}
              {c.label}
            </button>
          );
        })}
      </div>
      <div className="flex justify-end">
        <Button
          variant="primary"
          disabled={saving}
          onClick={() => onSave(Array.from(draft))}
        >
          {saving ? "保存中…" : "保存"}
        </Button>
      </div>
    </div>
  );
}
