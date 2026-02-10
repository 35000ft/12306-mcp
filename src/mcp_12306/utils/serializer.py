from pydantic import BaseModel
from collections.abc import Mapping, Iterable
from datetime import datetime, date
from enum import Enum


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
