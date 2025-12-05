import os
import pathlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------- Sub-config ----------
class CloudConfig(BaseModel):
    ima_url: str = Field(..., description="Cloud IMA endpoint (HTTP/HTTPS)")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
    )


class SenderFlag(BaseModel):
    use_legacy: bool = True
    use_aggregator: bool = False

    model_config = ConfigDict(
        extra="ignore",
    )


# ---------- Main config ----------
class SenderSchema(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Existing keys ---
    gateway_id: str
    resend_dir: str
    cloud: CloudConfig

    # --- Scheduling & freshness (unit: seconds; can be float) ---
    anchor_offset_sec: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Anchor offset for scheduler (0-59 seconds, aligns to minute boundary)",
    )
    send_interval_sec: int = Field(default=60, ge=1, description="Scheduler send interval in seconds")

    # Legacy key grace_period_sec for backward compatibility:
    # if tick_grace_sec is not provided, fallback to grace_period_sec
    tick_grace_sec: float = Field(default=1.0, ge=0, description="Grace period after tick in seconds")
    fresh_window_sec: float = Field(default=2.0, ge=0, description="Maximum delay considered 'fresh' in seconds")

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

    fail_resend_enabled: bool = Field(True, description="Enable background resend worker (no-op in Phase 0)")
    fail_resend_interval_sec: int = Field(60, description="Background resend scan interval (seconds)")
    fail_resend_batch: int = Field(10, description="Max files to process per resend cycle (>=1)")

    resend_protect_recent_sec: float = Field(
        300.0, description="Protect newly persisted files from cleanup for N seconds (>=0)"
    )
    resend_anchor_offset_sec: int = Field(
        default=5,
        ge=0,
        description="Anchor offset for resend worker within each interval (0 to fail_resend_interval_sec-1)",
    )
    last_post_ok_within_sec: float = Field(300.0, description="Health window to consider cloud recently OK (seconds)")
    resend_start_delay_sec: int = Field(
        default=180,
        description=(
            "Delay before starting resend worker (seconds). "
            "Allows warmup and scheduler to establish current state visibility first."
        ),
    )

    # --- Preserve existing block ---
    sender: SenderFlag = Field(default_factory=SenderFlag)

    resend_cleanup_enabled: bool = Field(
        False,
        description="Enable resend_dir cleanup. Recommended to keep disabled in POC/Phase2 to preserve all files",
    )

    # ---------- Backward compatibility: grace_period_sec -> tick_grace_sec ----------
    @model_validator(mode="before")
    @classmethod
    def _compat_grace_period(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "tick_grace_sec" not in data or data.get("tick_grace_sec") is None:
            legacy = data.get("grace_period_sec")
            if legacy is not None:
                data["tick_grace_sec"] = legacy
        return data

    # ---------- Default tick_grace_sec ----------
    @model_validator(mode="after")
    def _default_tick_grace_if_missing(self) -> "SenderSchema":
        if self.tick_grace_sec is None:
            self.tick_grace_sec = 0.8  # default 0.8 seconds
        return self

    @model_validator(mode="after")
    def _check_fresh_vs_grace(self) -> "SenderSchema":
        """
        fresh_window_sec 必須 >= tick_grace_sec
        """
        if self.fresh_window_sec < self.tick_grace_sec:
            raise ValueError("fresh_window_sec must be >= tick_grace_sec")
        return self

    @model_validator(mode="after")
    def validate_resend_anchor(self) -> "SenderSchema":
        """Validate that resend_anchor_offset_sec must be less than fail_resend_interval_sec"""
        if self.resend_anchor_offset_sec >= self.fail_resend_interval_sec:
            raise ValueError(
                f"resend_anchor_offset_sec ({self.resend_anchor_offset_sec}) "
                f"must be less than fail_resend_interval_sec ({self.fail_resend_interval_sec})"
            )
        return self

    # ---------- Boundary validations ----------
    @field_validator("anchor_offset_sec")
    @classmethod
    def _check_anchor(cls, v: int) -> float:
        if not (0.0 <= v <= 59.0):
            raise ValueError("anchor_offset_sec must be within [0, 59]")
        return float(v)

    @field_validator("send_interval_sec")
    @classmethod
    def _check_interval(cls, v: int) -> float:
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
    @classmethod
    def _check_non_negative(cls, v: float, field) -> float:
        if float(v) < 0.0:
            raise ValueError(f"{field.name} must be >= 0")
        return float(v)

    @field_validator("attempt_count")
    @classmethod
    def _check_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("attempt_count must be >= 1")
        return v

    @field_validator("max_retry")
    @classmethod
    def _check_max_retry(cls, v: int) -> int:
        if v < -1:
            raise ValueError("max_retry must be >= 0")
        return v

    @field_validator("resend_quota_mb", "fs_free_min_mb")
    @classmethod
    def _check_mb_positive(cls, v: int, field) -> int:
        if v <= 0:
            raise ValueError(f"{field.name} must be > 0")
        return v

    @field_validator("resend_cleanup_batch", "fail_resend_batch")
    @classmethod
    def _check_cleanup_batch(cls, v: int, field) -> int:
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
                testfile.unlink(missing_ok=True)
            except TypeError:
                if testfile.exists():
                    os.remove(str(testfile))
