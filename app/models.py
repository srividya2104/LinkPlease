from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class RuleCreateRequest(BaseModel):
    keyword: str
    dm_message: str


class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str


class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int


class UserData(BaseModel):
    user_id: str
    username: Optional[str] = None


class CommentData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[str] = None
    from_user: Optional[UserData] = Field(default=None, alias="from")


class WebhookPayload(BaseModel):
    event_id: str
    event_type: str
    sent_at: Optional[str] = None
    data: CommentData
