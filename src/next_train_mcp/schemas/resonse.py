from enum import StrEnum
from typing import Any, TypeVar, Optional

from pydantic import BaseModel, Field


class Status(StrEnum):
    SUCCESS = "success"
    FAIL = "fail"


class GenericResponse(BaseModel):
    status: Status | None = Field(Status.SUCCESS, title="Status")
    msg: str | None = Field("", title="Message")
    data: Optional[Any] = Field(None, title="Data")
