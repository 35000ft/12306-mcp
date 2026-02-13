import json
from typing import Optional, List

import china_railway_tools.api as cr_utils
from china_railway_tools.schemas import Station

from next_train_mcp.utils.serializer import pydantic_serialize


# 车站模糊搜索工具
async def search_station(args: dict) -> list:
    query = args.get("query", "").strip()
    limit = args.get("limit", 10)
    if not query:
        return [
            {"type": "text", "text": json.dumps({"success": False, "error": "请输入搜索关键词"}, ensure_ascii=False)}]
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        limit = 10
    params = {}
    if query.endswith("站"):
        params['exact'] = True
        query = query[:-1]

    stations: List[Station] = await cr_utils.query_station(query, limit=limit, **params)
    if stations:
        response_data = {
            "success": True,
            "query": query,
            "count": len(stations),
            "stations": pydantic_serialize(stations)
        }
        return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
    else:
        response_data = {
            "success": False,
            "query": query,
            "count": 0,
            "stations": [],
            "message": "未找到匹配的车站",
            "suggestions": [
                "尝试完整城市名称 (如: 北京)",
                "尝试拼音 (如: beijing)",
                "尝试简拼 (如: bj)",
                "检查拼写是否正确"
            ]
        }
        return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
