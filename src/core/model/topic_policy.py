from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DropPolicyEnum(StrEnum):
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


class TopicPolicyModel(BaseModel):
    """
    PubSub topic policy.

    queue_maxsize:
      Bounded queue size per subscriber.

    drop_policy:
      When queue is full:
        - drop_newest: drop the incoming message
        - drop_oldest: pop one item then enqueue the new one
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    queue_maxsize: int = Field(default=200, ge=1, le=100_000)
    drop_policy: DropPolicyEnum = Field(default=DropPolicyEnum.DROP_OLDEST)

    @field_validator("drop_policy", mode="before")
    @classmethod
    def _normalize_drop_policy(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v
