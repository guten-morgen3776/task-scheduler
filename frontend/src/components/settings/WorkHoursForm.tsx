import { useEffect, useState } from "react";
import type { WeekDay, WorkHours, WorkHourSlot } from "../../api/types";
import { Button, Input } from "../ui";

const DAYS: WeekDay[] = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
];

const LABELS: Record<WeekDay, string> = {
  monday: "月",
  tuesday: "火",
  wednesday: "水",
  thursday: "木",
  friday: "金",
  saturday: "土",
  sunday: "日",
};

export function WorkHoursForm({
  value,
  onSave,
  saving,
}: {
  value: WorkHours;
  onSave: (next: WorkHours) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<WorkHours>(value);
  useEffect(() => setDraft(value), [value]);

  const updateDay = (day: WeekDay, slots: WorkHourSlot[]) => {
    setDraft({ ...draft, [day]: { slots } });
  };

  return (
    <div className="space-y-3">
      <table className="w-full text-sm">
        <tbody>
          {DAYS.map((day) => (
            <tr key={day} className="border-b border-gray-100 last:border-0">
              <td className="w-8 py-2 text-gray-700 font-medium">
                {LABELS[day]}
              </td>
              <td className="py-2">
                <div className="flex flex-wrap items-center gap-2">
                  {draft[day].slots.map((s, i) => (
                    <SlotEditor
                      key={i}
                      slot={s}
                      onChange={(next) => {
                        const list = [...draft[day].slots];
                        list[i] = next;
                        updateDay(day, list);
                      }}
                      onRemove={() => {
                        const list = draft[day].slots.filter((_, j) => j !== i);
                        updateDay(day, list);
                      }}
                    />
                  ))}
                  <Button
                    type="button"
                    onClick={() =>
                      updateDay(day, [
                        ...draft[day].slots,
                        { start: "09:00", end: "12:00" },
                      ])
                    }
                  >
                    + slot
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex justify-end">
        <Button
          variant="primary"
          disabled={saving}
          onClick={() => onSave(draft)}
        >
          {saving ? "保存中…" : "保存"}
        </Button>
      </div>
    </div>
  );
}

function SlotEditor({
  slot,
  onChange,
  onRemove,
}: {
  slot: WorkHourSlot;
  onChange: (next: WorkHourSlot) => void;
  onRemove: () => void;
}) {
  return (
    <div className="inline-flex items-center gap-1 border border-gray-200 rounded-md px-1.5 py-0.5 bg-gray-50">
      <Input
        type="time"
        value={slot.start}
        onChange={(e) => onChange({ ...slot, start: e.target.value })}
        className="w-24 text-xs"
      />
      <span className="text-gray-400">〜</span>
      <Input
        type="time"
        value={slot.end}
        onChange={(e) => onChange({ ...slot, end: e.target.value })}
        className="w-24 text-xs"
      />
      <button
        type="button"
        onClick={onRemove}
        className="text-xs text-gray-400 hover:text-red-600 px-1"
        title="削除"
      >
        ×
      </button>
    </div>
  );
}
