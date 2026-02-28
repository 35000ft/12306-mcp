import ast
import json
from typing import TypeVar, Annotated, Type

import json5
from loguru import logger
from pydantic import BaseModel, BeforeValidator
from collections.abc import Mapping, Iterable
from datetime import datetime, date
from enum import Enum


def fix_pydantic_args(v: str | dict):
    if isinstance(v, str):
        try:
            r = ast.literal_eval(v)
            if isinstance(r, dict):
                return r
            else:
                pass
        except:
            pass
        return json5.loads(v)
    return v


T = TypeVar('T')
BaseT = TypeVar('BaseT', bound=BaseModel)
PydanticArgs = Annotated[BaseT, BeforeValidator(fix_pydantic_args, )]


def pydantic_serialize(obj):
    """
    将 pydantic / list / dict / 混合嵌套对象
    自动序列化为可 JSON 化的数据结构
    """
    if obj is None:
        return None

    # Pydantic Model
    if isinstance(obj, BaseModel):
        return obj.model_dump()

    # dict
    if isinstance(obj, Mapping):
        return {
            pydantic_serialize(k): pydantic_serialize(v)
            for k, v in obj.items()
        }

    # list / tuple / set
    if isinstance(obj, Iterable) and not isinstance(obj, (str, bytes)):
        return [pydantic_serialize(i) for i in obj]

    # datetime / date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    # Enum
    if isinstance(obj, Enum):
        return obj.value

    # 基础类型（int / str / float / bool）
    return obj
