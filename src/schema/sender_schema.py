import os
import pathlib

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------- Sub-config ----------
class CloudConfig(BaseModel):
    ima_url: str = Field(..., description="Cloud IMA endpoint (HTTP/HTTPS)")

    class Config:
        str_strip_whitespace = True
        extra = "ignore"


class SenderFlag(BaseModel):
    use_legacy: bool = True
    use_aggregator: bool = False

    class Config:
        extra = "ignore"


# ---------- Main config ----------
class SenderSchema(BaseModel):
    # --- Existing keys ---
    gateway_id: str
    resend_dir: str
    cloud: CloudConfig

    # --- Scheduling & freshness (unit: seconds; can be float) ---
    anchor_offset_sec: float = Field(40.0, description="Start second in each minute (0..59)")
    send_interval_sec: float = Field(60.0, description="Interval between sends in seconds (>0)")

    # Legacy key grace_period_sec for backward compatibility:
    # if tick_grace_sec is not provided, fallback to grace_period_sec
    tick_grace_sec: float | None = Field(
        1.0, description="Grace wait after label_time to collect current snapshot (seconds, >=0)"
    )
    fresh_window_sec: float = Field(
        1.0, description="Max age to consider snapshot 'fresh' at label_time (seconds, >= tick_grace_sec)"
    )

    # --- Transmission / resend ---
    attempt_count: int = Field(2, description="Retries for a single HTTP post (>=1)")
    max_retry: int = Field(3, description="Max resend rounds for a failed file (>=0)")

    # --- Authenticity strategy ---
    last_known_ttl_sec: float = Field(
        0.0, description="0 to disable. If >0, allow last-known value within TTL (seconds)."
    )

    # --- Resend space protection (MB/seconds) ---
    resend_quota_mb: int = Field(256, description="Max size for resend_dir in MB (>0)")
    fs_free_min_mb: int = Field(512, description="Minimum free space (filesystem-wide) in MB (>0)")
    resend_cleanup_batch: int = Field(100, description="Max files to delete per cleanup round (>=1)")
    resend_protect_recent_sec: float = Field(
        300.0, description="Protect newly persisted files from cleanup for N seconds (>=0)"
    )

    fail_resend_enabled: bool = Field(True, description="Enable background resend worker (no-op in Phase 0)")
    fail_resend_interval_sec: int = Field(60, description="Background resend scan interval (seconds)")
    fail_resend_batch: int = Field(10, description="Max files to process per resend cycle (>=1)")
    last_post_ok_within_sec: float = Field(300.0, description="Health window to consider cloud recently OK (seconds)")
    resend_start_delay_sec: int = Field(
        default=180,
        description="Delay before starting resend worker (seconds). "
        "Allows warmup and scheduler to establish current state visibility first.",
    )

    # --- Preserve existing block ---
    sender: SenderFlag = Field(default_factory=SenderFlag)

    resend_cleanup_enabled: bool = Field(
        False, description="Enable resend_dir cleanup. Recommended to keep disabled in POC/Phase2 to preserve all files"
    )

    class Config:
        str_strip_whitespace = True
        validate_by_name = True
        extra = "ignore"

    # ---------- Backward compatibility: grace_period_sec -> tick_grace_sec ----------
    @model_validator(mode="before")
    def _compat_grace_period(cls, values: dict):
        if "tick_grace_sec" not in values or values.get("tick_grace_sec") is None:
            legacy = values.get("grace_period_sec")
            if legacy is not None:
                values["tick_grace_sec"] = legacy
        return values

    # ---------- Default tick_grace_sec ----------
    @model_validator(mode="after")
    def _default_tick_grace_if_missing(cls, values: "SenderSchema"):
        if values.tick_grace_sec is None:
            values["tick_grace_sec"] = 0.8  # default 0.8 seconds
        return values

    # ---------- Boundary validations ----------
    @field_validator("anchor_offset_sec")
    def _check_anchor(cls, v):
        if not (0.0 <= v <= 59.0):
            raise ValueError("anchor_offset_sec must be within [0, 59]")
        return float(v)

    @field_validator("send_interval_sec")
    def _check_interval(cls, v):
        if float(v) <= 0.0:
            raise ValueError("send_interval_sec must be > 0")
        return float(v)

    @field_validator(
        "tick_grace_sec",
        "fresh_window_sec",
        "last_known_ttl_sec",
        "resend_protect_recent_sec",
        "last_post_ok_within_sec",
    )
    def _check_non_negative(cls, v, field):
        if float(v) < 0.0:
            raise ValueError(f"{field.name} must be >= 0")
        return float(v)

    @model_validator(mode="after")
    def _check_fresh_vs_grace(cls, values: "SenderSchema"):
        if values.fresh_window_sec < values.tick_grace_sec:
            raise ValueError("fresh_window_sec must be >= tick_grace_sec")
        return values

    @field_validator("attempt_count")
    def _check_attempts(cls, v):
        if v < 1:
            raise ValueError("attempt_count must be >= 1")
        return v

    @field_validator("max_retry")
    def _check_max_retry(cls, v):
        if v < -1:
            raise ValueError("max_retry must be >= 0")
        return v

    @field_validator("resend_quota_mb", "fs_free_min_mb")
    def _check_mb_positive(cls, v, field):
        if v <= 0:
            raise ValueError(f"{field.name} must be > 0")
        return v

    @field_validator("resend_cleanup_batch", "fail_resend_batch")
    def _check_cleanup_batch(cls, v, field):
        if v < 1:
            raise ValueError(f"{field.name} must be >= 1")
        return v

    # ---------- Path check / creation ----------
    def ensure_paths(self) -> None:
        path = pathlib.Path(self.resend_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        # simple write test
        testfile = path / ".talos_write_test"
        try:
            with open(testfile, "w", encoding="utf-8") as f:
                f.write("ok")
        finally:
            try:
                testfile.unlink(missing_ok=True)  # py3.8+: use os.remove if needed
            except TypeError:
                if testfile.exists():
                    os.remove(str(testfile))
