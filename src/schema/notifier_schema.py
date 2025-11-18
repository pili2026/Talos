from pydantic import BaseModel, Field, field_validator

from model.enum.alert_enum import AlertSeverity
from model.enum.notification_mode_enum import NotificationMode


class SmsNotifierConfig(BaseModel):
    """SMS notifier configuration"""

    enabled: bool = Field(default=False, description="Enable SMS notifications")
    priority: int = Field(default=1, ge=1, le=10, description="Notifier priority (1=highest)")
    phone_numbers: list[str] = Field(default_factory=list, description="List of phone numbers")

    @field_validator("phone_numbers")
    def validate_phone_numbers(cls, v):
        if not v:
            return v
        # Basic phone number validation
        for phone in v:
            if not phone.startswith("+"):
                raise ValueError(f"Phone number must start with '+': {phone}")
        return v


class TelegramNotifierConfig(BaseModel):
    """Telegram notifier configuration"""

    enabled: bool = Field(default=False)
    priority: int = Field(default=2, ge=1, le=10)
    bot_token: str = Field(default="", description="Telegram bot token")
    chat_id: str = Field(default="", description="Telegram chat/group ID")
    timeout_sec: float = Field(default=5.0, gt=0)
    parse_mode: str = Field(default="HTML", description="Message parse mode (HTML/Markdown)")

    @field_validator("parse_mode")
    def validate_parse_mode(cls, v):
        if v not in ["HTML", "Markdown", "MarkdownV2"]:
            raise ValueError(f"parse_mode must be HTML, Markdown, or MarkdownV2, got: {v}")
        return v

    @field_validator("chat_id", mode="before")
    def convert_chat_id_to_str(cls, v):
        """Convert chat_id to string if it's an integer"""
        if isinstance(v, int):
            return str(v)
        return v


class EmailNotifierConfig(BaseModel):
    """Email notifier configuration"""

    enabled: bool = Field(default=True, description="Email is always enabled as fallback")
    priority: int = Field(default=3, ge=1, le=10)
    config_path: str = Field(default="./res/mail_config.yml", description="Path to email config")


class NotifierConfigSchema(BaseModel):
    """All notifier configurations"""

    sms: SmsNotifierConfig | None = None
    telegram: TelegramNotifierConfig | None = None
    email: EmailNotifierConfig = Field(default_factory=EmailNotifierConfig)


class RoutingRule(BaseModel):
    """Routing rule for a specific severity level"""

    mode: NotificationMode = Field(description="Notification delivery mode")
    notifiers: list[str] = Field(description="List of notifier names to use")
    min_success: int = Field(default=1, ge=1, description="Minimum successful sends required")

    @field_validator("notifiers")
    def validate_notifiers(cls, v):
        valid_notifiers = {"sms", "telegram", "email"}
        for notifier in v:
            if notifier not in valid_notifiers:
                raise ValueError(f"Unknown notifier: {notifier}. Valid: {valid_notifiers}")
        return v

    @field_validator("min_success")
    def validate_min_success(cls, v, info):
        # Ensure min_success doesn't exceed number of notifiers
        notifiers = info.data.get("notifiers", [])
        if v > len(notifiers):
            raise ValueError(f"min_success ({v}) cannot exceed number of notifiers ({len(notifiers)})")
        return v


class NotificationStrategySchema(BaseModel):
    """Notification routing strategy"""

    mode: str = Field(default="severity_based", description="Overall strategy mode")
    routing: dict[AlertSeverity, RoutingRule] = Field(
        default_factory=dict, description="Routing rules per severity level"
    )

    @field_validator("mode")
    def validate_mode(cls, v):
        if v not in ["severity_based", "simple"]:
            raise ValueError(f"Unknown strategy mode: {v}")
        return v


class RetryConfigSchema(BaseModel):
    """Retry configuration"""

    max_attempts: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")
    backoff_base_sec: float = Field(default=1.0, gt=0, description="Base backoff time in seconds")
    backoff_multiplier: float = Field(default=2.0, ge=1.0, description="Backoff multiplier")


class NotificationConfigSchema(BaseModel):
    """Root notification configuration schema"""

    strategy: NotificationStrategySchema = Field(default_factory=NotificationStrategySchema)
    notifiers: NotifierConfigSchema = Field(default_factory=NotifierConfigSchema)
    retry: RetryConfigSchema = Field(default_factory=RetryConfigSchema)

    class Config:
        str_strip_whitespace = True
        validate_assignment = True
        extra = "forbid"  # Reject unknown fields (catch typos)
