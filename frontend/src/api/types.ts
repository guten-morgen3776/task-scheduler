// Hand-written TypeScript counterparts to the backend's Pydantic schemas.
// Sync rule of thumb: if you change a Pydantic model, update the matching
// type here (see backend/app/schemas/*.py).

export type Location = "home" | "university" | "office" | "anywhere";

export interface AuthMe {
  user_id: string;
  google_email: string | null;
  scopes: string[];
  token_expires_at: string | null;
}

export interface TaskList {
  id: string;
  title: string;
  position: string;
  created_at: string;
  updated_at: string;
  task_count: number;
  completed_count: number;
}

export interface ScheduledFragment {
  start: string;
  end: string;
}

export interface Task {
  id: string;
  user_id: string;
  list_id: string;
  title: string;
  notes: string | null;
  parent_id: string | null;
  position: string;
  completed: boolean;
  completed_at: string | null;
  due: string | null;
  duration_min: number;
  priority: number;
  deadline: string | null;
  location: Location | null;
  scheduled_event_id: string | null;
  scheduled_start: string | null;
  scheduled_end: string | null;
  scheduled_fragments: ScheduledFragment[] | null;
  scheduled_fixed: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskCreate {
  title: string;
  notes?: string | null;
  parent_id?: string | null;
  due?: string | null;
  duration_min?: number;
  priority?: number;
  deadline?: string | null;
  location?: Location | null;
}

export interface TaskUpdate {
  title?: string;
  notes?: string | null;
  due?: string | null;
  duration_min?: number;
  priority?: number;
  deadline?: string | null;
  location?: Location | null;
  position?: string;
  scheduled_fixed?: boolean;
}

export interface FragmentRead {
  slot_id: string;
  start: string;
  duration_min: number;
}

export interface TaskAssignmentRead {
  task_id: string;
  task_title: string;
  fragments: FragmentRead[];
  total_assigned_min: number;
}

export interface UnassignedRead {
  task_id: string;
  task_title: string;
}

export type SolveStatus =
  | "optimal"
  | "feasible"
  | "infeasible"
  | "timed_out"
  | "error";

export interface OptimizeResponse {
  status: SolveStatus;
  objective_value: number | null;
  snapshot_id: string;
  assignments: TaskAssignmentRead[];
  unassigned: UnassignedRead[];
  solve_time_sec: number;
  notes: string[];
}

export interface OptimizeRequest {
  start: string;
  end: string;
  list_ids?: string[] | null;
  task_ids?: string[] | null;
  note?: string | null;
}

export interface WriteResponse {
  snapshot_id: string;
  dry_run: boolean;
  target_calendar_id: string;
  deleted_event_count: number;
  created_events: {
    task_id: string;
    task_title: string;
    event_id: string | null;
    start: string;
    end: string;
    fragment_index: number;
  }[];
}

// Settings — partial; expand as the settings UI grows.
export interface WorkHourSlot {
  start: string;
  end: string;
}
export interface WorkHoursDay {
  slots: WorkHourSlot[];
}
export type WeekDay =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";
export interface WorkHours
  extends Record<WeekDay, WorkHoursDay> {
  timezone: string;
}

export interface CalendarLocationRule {
  calendar_id: string | null;
  event_summary_matches: string | null;
  location: Location;
  unless_day_has_calendar_ids?: string[];
}

export interface LocationCommute {
  to_min: number;
  from_min: number;
  linger_after_min: number;
}

export interface DayTypeCondition {
  event_summary_matches: string | null;
  weekday: WeekDay | null;
  event_count_min: number | null;
  event_count_max: number | null;
  total_busy_hours_min: number | null;
  total_busy_hours_max: number | null;
}
export interface DayTypeRule {
  name: string;
  if: DayTypeCondition;
  energy: number;
  allowed_max_task_duration_min: number;
}
export interface DayTypeDefault {
  name: string;
  energy: number;
  allowed_max_task_duration_min: number;
}

export interface SettingsRead {
  work_hours: WorkHours;
  calendar_location_rules: CalendarLocationRule[];
  location_commutes: Partial<Record<Location, LocationCommute>>;
  day_type_rules: DayTypeRule[];
  day_type_default: DayTypeDefault;
  day_type_overrides: Record<string, string>;
  busy_calendar_ids: string[];
  ignore_calendar_ids: string[];
  slot_min_duration_min: number;
  slot_max_duration_min: number;
  ignore_all_day_events: boolean;
  voluntary_visit_locations: Location[];
}

export type SettingsUpdate = Partial<SettingsRead>;

export interface ApiErrorBody {
  detail?: { error?: string; message?: string } | string;
}
