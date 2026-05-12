import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useCreateTask } from "../../hooks/useTasks";
import { Button, Input, Label, Select } from "../ui";

const schema = z.object({
  title: z.string().trim().min(1, "タイトルは必須"),
  duration_min: z.number().int().min(5).max(720),
  priority: z.number().int().min(1).max(5),
  deadline: z.string().optional(),
  location: z.enum(["", "home", "university", "office", "anywhere"]).optional(),
});

type FormValues = z.infer<typeof schema>;

export function AddTaskForm({ listId }: { listId: string }) {
  const create = useCreateTask(listId);
  const { register, handleSubmit, reset, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      duration_min: 60,
      priority: 3,
      deadline: "",
      location: "",
    },
  });

  return (
    <form
      className="grid grid-cols-2 sm:flex sm:flex-wrap sm:items-end gap-2 sm:gap-3"
      onSubmit={handleSubmit((v) => {
        const deadlineIso =
          v.deadline && v.deadline !== ""
            ? new Date(v.deadline).toISOString()
            : null;
        create.mutate(
          {
            title: v.title,
            duration_min: v.duration_min,
            priority: v.priority,
            deadline: deadlineIso,
            location: v.location ? v.location : null,
          },
          { onSuccess: () => reset({ title: "", duration_min: 60, priority: 3, deadline: "", location: "" }) },
        );
      })}
    >
      <div className="col-span-2 sm:flex-1 sm:min-w-[12rem]">
        <Label>タイトル</Label>
        <Input className="w-full" {...register("title")} placeholder="新しいタスク" />
      </div>
      <div>
        <Label>分</Label>
        <Input type="number" min={5} max={720} step={5} className="w-full sm:w-20" {...register("duration_min", { valueAsNumber: true })} />
      </div>
      <div>
        <Label>優先度</Label>
        <Select className="w-full sm:w-20" {...register("priority", { valueAsNumber: true })}>
          {[1, 2, 3, 4, 5].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </Select>
      </div>
      <div>
        <Label>場所</Label>
        <Select className="w-full sm:w-32" {...register("location")}>
          <option value="">指定なし</option>
          <option value="home">home</option>
          <option value="university">university</option>
          <option value="office">office</option>
          <option value="anywhere">anywhere</option>
        </Select>
      </div>
      <div>
        <Label>締切</Label>
        <Input type="datetime-local" {...register("deadline")} className="w-full sm:w-44" />
      </div>
      <Button
        type="submit"
        variant="primary"
        className="col-span-2 sm:col-auto w-full sm:w-auto justify-center"
        disabled={create.isPending || !formState.isValid}
      >
        追加
      </Button>
    </form>
  );
}
