from datetime import time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Single time interval
class TimeInterval(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    start: time
    end: time

    @model_validator(mode="after")
    def _validate_non_empty(cls, m: "TimeInterval"):
        # Allow overnight spans (start > end), but disallow start == end (zero-length interval)
        if m.start == m.end:
            raise ValueError("interval 'start' and 'end' must differ")
        return m


# Schedule for a single device
class DeviceSchedule(BaseModel):
    model_config = ConfigDict(extra="allow")  # Accept legacy start/end
    weekdays: set[int] = Field(default_factory=set)  # 1..7 (ISO: Mon..Sun)
    intervals: list[TimeInterval] = Field(default_factory=list)
    timezone: str | None = None  # Override global timezone (optional)

    # --- Legacy support ---
    start: time | None = None
    end: time | None = None

    @field_validator("weekdays", mode="after")
    @classmethod
    def _validate_weekdays(cls, v: set[int]) -> set[int]:
        if not v:
            return v
        bad = [d for d in v if d < 1 or d > 7]
        if bad:
            raise ValueError(f"weekdays must be in 1..7, got {bad}")
        return v

    @model_validator(mode="after")
    def _build_intervals_from_legacy(self) -> "DeviceSchedule":
        # If no intervals are provided but legacy start/end exist, build a single interval from them
        if not self.intervals and self.start and self.end:
            self.intervals = [TimeInterval(start=self.start, end=self.end)]
        # Normalize: sort intervals and deduplicate
        seen: set[tuple[time, time]] = set()
        uniq: list[TimeInterval] = []
        for itv in sorted(self.intervals, key=lambda i: (i.start, i.end)):
            key = (itv.start, itv.end)
            if key not in seen:
                seen.add(key)
                uniq.append(itv)
        self.intervals = uniq
        return self


# Whole configuration file (aligned with the existing yml structure)
class TimeControlConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    timezone: str | None = None  # Global default timezone (optional)
    work_hours: dict[str, DeviceSchedule]
    model_config = ConfigDict(extra="ignore")
    timezone: str | None = None  # Global default timezone (optional)
    work_hours: dict[str, DeviceSchedule]
