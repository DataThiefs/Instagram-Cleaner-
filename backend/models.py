from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class LoginSessionRequest(BaseModel):
    sessionid: str = Field(..., min_length=5, description="Instagram sessionid çerezi")


class LoginCredentialsRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    verification_code: Optional[str] = None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    demo_mode: bool = False
    username: Optional[str] = None
    full_name: Optional[str] = None
    user_id: Optional[str] = None
    profile_pic_url: Optional[str] = None


class ThreadItem(BaseModel):
    thread_id: str
    title: str
    usernames: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    is_group: bool = False
    last_message: str = ""
    last_activity: str = ""
    message_count_hint: int = 0
    is_whitelisted: bool = False


class MessageMatchItem(BaseModel):
    thread_id: str
    thread_title: str
    message_id: str
    text: str
    timestamp: str
    is_mine: bool = True
    item_type: str = "text"


class StoryArchiveItem(BaseModel):
    media_id: str
    pk: str
    taken_at: str
    taken_at_ts: int
    media_type: Literal["PHOTO", "VIDEO"] = "PHOTO"
    thumbnail_url: Optional[str] = None
    caption: Optional[str] = None


class SearchMessagesRequest(BaseModel):
    keyword: str = Field(..., min_length=1)
    thread_ids: Optional[list[str]] = None
    limit_per_thread: int = Field(default=60, ge=5, le=300)
    only_mine: bool = True
    case_sensitive: bool = False


class DeleteThreadsRequest(BaseModel):
    thread_ids: list[str] = Field(..., min_length=1)
    unsend_my_messages_first: bool = False
    dry_run: bool = False
    min_delay: float = Field(default=2.0, ge=0.5, le=30.0)
    max_delay: float = Field(default=5.0, ge=0.5, le=60.0)


class UnsendTarget(BaseModel):
    thread_id: str
    message_id: str
    preview: str = ""


class UnsendMessagesRequest(BaseModel):
    items: list[UnsendTarget] = Field(..., min_length=1)
    dry_run: bool = False
    min_delay: float = Field(default=2.0, ge=0.5, le=30.0)
    max_delay: float = Field(default=5.0, ge=0.5, le=60.0)


class DeleteStoryTarget(BaseModel):
    media_id: str
    media_type: Literal["PHOTO", "VIDEO"] = "PHOTO"
    taken_at: str = ""


class DeleteStoriesRequest(BaseModel):
    items: list[DeleteStoryTarget] = Field(..., min_length=1)
    dry_run: bool = False
    min_delay: float = Field(default=2.0, ge=0.5, le=30.0)
    max_delay: float = Field(default=5.0, ge=0.5, le=60.0)


class AllCleanRequest(BaseModel):
    delete_dm_threads: bool = True
    unsend_my_messages: bool = False
    delete_archived_stories: bool = True
    respect_whitelist: bool = True
    dry_run: bool = False
    min_delay: float = Field(default=2.5, ge=0.5, le=30.0)
    max_delay: float = Field(default=6.0, ge=0.5, le=60.0)


class WhitelistRequest(BaseModel):
    username: str = Field(..., min_length=1)


class LogEntry(BaseModel):
    time: str
    level: Literal["info", "success", "warn", "error"]
    message: str


class JobStatusResponse(BaseModel):
    job_id: Optional[str] = None
    job_type: Optional[str] = None
    status: Literal["idle", "running", "paused", "completed", "stopped", "error"] = "idle"
    dry_run: bool = False
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    current_action: str = ""
    logs: list[LogEntry] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
