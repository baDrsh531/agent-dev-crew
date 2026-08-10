"""Reference solution — tag validation."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

MAX_TAGS = 10
MAX_TAG_LENGTH = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_tags(tags: list[str]) -> list[str]:
    if len(tags) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags are allowed")
    seen: list[str] = []
    for tag in tags:
        if not tag or not tag.strip():
            raise ValueError("tags must not be blank")
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"a tag may not exceed {MAX_TAG_LENGTH} characters")
        if tag not in seen:  # de-duplicate, keep first appearance
            seen.append(tag)
    return seen


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, value: list[str]) -> list[str]:
        return _validate_tags(value)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=10_000)
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def check_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_tags(value)


class Note(BaseModel):
    id: int
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
