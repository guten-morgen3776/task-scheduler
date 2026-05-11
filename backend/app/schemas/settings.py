import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WeekDay = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]
WEEKDAYS: tuple[WeekDay, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

Location = Literal["home", "university", "office", "anywhere"]
LOCATIONS: tuple[Location, ...] = ("home", "university", "office", "anywhere")

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class WorkHourSlot(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _validate_hhmm(cls, v: str) -> str:
        if not _HHMM_RE.match(v):
            raise ValueError(f"Expected HH:MM (24h), got {v!r}")
        return v

    @model_validator(mode="after")
    def _start_before_end(self) -> "WorkHourSlot":
        if self.start >= self.end:
            raise ValueError(f"start ({self.start}) must be before end ({self.end})")
        return self


class WorkHoursDay(BaseModel):
    slots: list[WorkHourSlot]


class WorkHours(BaseModel):
    monday: WorkHoursDay
    tuesday: WorkHoursDay
    wednesday: WorkHoursDay
    thursday: WorkHoursDay
    friday: WorkHoursDay
    saturday: WorkHoursDay
    sunday: WorkHoursDay
    timezone: str = "Asia/Tokyo"

    def for_weekday(self, weekday: WeekDay) -> WorkHoursDay:
        return getattr(self, weekday)


class CalendarLocationRule(BaseModel):
    """Tags a calendar event with a location.

    At least one of `calendar_id` or `event_summary_matches` must be set.
    First matching rule wins (rules evaluated in list order).

    `unless_day_has_calendar_ids`: if set, the rule is skipped for events on
    a local day where any same-day event has a calendar_id in this list.
    Used to express "intern at office UNLESS the same day has a UTAS class
    (then remote at the university)" — list the UTAS calendar id here and
    add a fallback rule below that points intern→university.
    """

    calendar_id: str | None = None
    event_summary_matches: str | None = None
    location: Location
    unless_day_has_calendar_ids: list[str] = Field(default_factory=list)

    @field_validator("event_summary_matches")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid regex: {e}") from e
        return v

    @model_validator(mode="after")
    def _at_least_one_condition(self) -> "CalendarLocationRule":
        if self.calendar_id is None and self.event_summary_matches is None:
            raise ValueError(
                "CalendarLocationRule needs at least one of calendar_id or event_summary_matches"
            )
        return self


class LocationCommute(BaseModel):
    """One-way travel time + optional lingering after the last scheduled event.

    `linger_after_min` lets the location window extend past the last event so the
    user is treated as still at that location for tasks (e.g., staying at the
    library after the last class). Commute_from is then placed at the END of the
    window (i.e., the last `from_min` minutes of the window are the actual return).
    """

    to_min: int = Field(ge=0, le=240)
    from_min: int = Field(ge=0, le=240)
    linger_after_min: int = Field(default=0, ge=0, le=480)


class DayTypeCondition(BaseModel):
    event_summary_matches: str | None = None
    weekday: WeekDay | None = None
    event_count_min: int | None = Field(default=None, ge=0)
    event_count_max: int | None = Field(default=None, ge=0)
    total_busy_hours_min: float | None = Field(default=None, ge=0)
    total_busy_hours_max: float | None = Field(default=None, ge=0)

    @field_validator("event_summary_matches")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid regex: {e}") from e
        return v


class DayTypeRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    if_: DayTypeCondition = Field(alias="if")
    energy: float = Field(ge=0.0, le=1.0)
    allowed_max_task_duration_min: int = Field(gt=0)


class DayTypeDefault(BaseModel):
    name: str
    energy: float = Field(ge=0.0, le=1.0)
    allowed_max_task_duration_min: int = Field(gt=0)


class SettingsRead(BaseModel):
    work_hours: WorkHours
    calendar_location_rules: list[CalendarLocationRule]
    location_commutes: dict[Location, LocationCommute]
    day_type_rules: list[DayTypeRule]
    day_type_default: DayTypeDefault
    day_type_overrides: dict[str, str]
    busy_calendar_ids: list[str]
    ignore_calendar_ids: list[str]
    slot_min_duration_min: int = Field(gt=0)
    slot_max_duration_min: int = Field(gt=0)
    ignore_all_day_events: bool
    voluntary_visit_locations: list[Location] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    work_hours: WorkHours | None = None
    calendar_location_rules: list[CalendarLocationRule] | None = None
    location_commutes: dict[Location, LocationCommute] | None = None
    day_type_rules: list[DayTypeRule] | None = None
    day_type_default: DayTypeDefault | None = None
    day_type_overrides: dict[str, str] | None = None
    busy_calendar_ids: list[str] | None = None
    ignore_calendar_ids: list[str] | None = None
    slot_min_duration_min: int | None = Field(default=None, gt=0)
    slot_max_duration_min: int | None = Field(default=None, gt=0)
    ignore_all_day_events: bool | None = None
    voluntary_visit_locations: list[Location] | None = None


def build_default_settings() -> SettingsRead:
    """Sensible starting values. Tunable via PUT /settings without code changes."""
    daily_slots = WorkHoursDay(
        slots=[
            WorkHourSlot(start="09:00", end="12:00"),
            WorkHourSlot(start="13:00", end="19:00"),
        ]
    )
    return SettingsRead(
        work_hours=WorkHours(
            monday=daily_slots,
            tuesday=daily_slots,
            wednesday=daily_slots,
            thursday=daily_slots,
            friday=daily_slots,
            saturday=daily_slots,
            sunday=daily_slots,
            timezone="Asia/Tokyo",
        ),
        calendar_location_rules=[
            CalendarLocationRule(
                calendar_id="u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com",
                location="university",
            ),
            # Intern at office — but remote on days where UTAS has a class.
            # When that's the case the next rule (intern→university) wins.
            CalendarLocationRule(
                event_summary_matches=r"intern|インターン",
                location="office",
                unless_day_has_calendar_ids=[
                    "u06kh7esai92ukk91jeinffulgqd7onf@import.calendar.google.com"
                ],
            ),
            # Fallback when the rule above is skipped: intern + UTAS day → uni library.
            CalendarLocationRule(
                event_summary_matches=r"intern|インターン",
                location="university",
            ),
        ],
        location_commutes={
            # 放課後 3 時間まで図書館に残ってタスクをやる前提
            "university": LocationCommute(to_min=30, from_min=30, linger_after_min=180),
            "office": LocationCommute(to_min=20, from_min=20),
        },
        day_type_rules=[
            # Pure busy-hours classification. Intern days no longer get a
            # special carve-out — if the day is 8h packed it's heavy_day,
            # same as any 8h-packed day.
            # Order matters: first matching rule wins.
            DayTypeRule(
                name="heavy_day",
                **{"if": DayTypeCondition(total_busy_hours_min=6.0)},
                energy=0.4,
                allowed_max_task_duration_min=90,
            ),
            DayTypeRule(
                name="medium_day",
                **{"if": DayTypeCondition(total_busy_hours_min=3.0, total_busy_hours_max=5.999)},
                energy=0.7,
                allowed_max_task_duration_min=180,
            ),
            DayTypeRule(
                name="light_day",
                **{"if": DayTypeCondition(total_busy_hours_min=0.001, total_busy_hours_max=2.999)},
                energy=0.9,
                allowed_max_task_duration_min=240,
            ),
            DayTypeRule(
                name="free_day",
                **{"if": DayTypeCondition(total_busy_hours_max=0)},
                energy=1.0,
                allowed_max_task_duration_min=240,
            ),
        ],
        day_type_default=DayTypeDefault(
            name="normal",
            energy=0.7,
            allowed_max_task_duration_min=180,
        ),
        day_type_overrides={},
        busy_calendar_ids=[],
        ignore_calendar_ids=[],
        slot_min_duration_min=30,
        slot_max_duration_min=120,
        ignore_all_day_events=True,
        voluntary_visit_locations=[],
    )
