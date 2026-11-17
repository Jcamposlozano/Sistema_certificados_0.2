from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    category: str
    date: date | None
    hours: int | None
    available: bool


@dataclass(frozen=True)
class CertificateGeneration:
    template_id: str
    name: str
    identification: str


@dataclass(frozen=True)
class Certificate:
    id: str
    event_id: str
    title: str
    category: str
    role: str
    status: str
    s3_bucket: str | None
    s3_key: str | None
    s3_version_id: str | None
    generation: CertificateGeneration | None = None


@dataclass
class Challenge:
    id: str
    email: str
    provider_state: str
    created_at: int
    expires_at: int
    attempts: int = 0
    consumed: bool = False


@dataclass(frozen=True)
class Session:
    token_hash: str
    participant_id: str
    expires_at: int


@dataclass(frozen=True)
class Participant:
    id: str
    name: str
    email: str
    subject: str | None = None


class ErrorKind(Enum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


class AppError(Exception):
    def __init__(self, kind: ErrorKind, message: str):
        self.kind = kind
        self.message = message
        super().__init__(message)
