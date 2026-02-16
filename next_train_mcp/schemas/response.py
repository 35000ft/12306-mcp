from enum import StrEnum
from typing import Any, TypeVar, Optional

from pydantic import BaseModel, Field


class Status(StrEnum):
    SUCCESS = "success"
    FAIL = "fail"


class GenericResponse(BaseModel):
    status: Optional[Status] = Field(Status.SUCCESS, title="Status")
    msg: Optional[str] = Field("", title="Message")
    data: Optional[Any] = Field(None, title="Data")
    total: Optional[int] = Field(None, title="Total", description="Total data item if data is list")

    @staticmethod
    def error(msg: str):
        return GenericResponse(status=Status.FAIL, msg=msg, data=None)
