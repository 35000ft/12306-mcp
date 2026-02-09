from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, Field


class Status(StrEnum):
    SUCCESS = "success"
    FAIL = "fail"


class GenericResponse(BaseModel):
    status: Status | None = Field(Status.SUCCESS, title="Status")
    msg: str | None = Field("", title="Message")
    data: Any | None = Field(None, title="Data")
