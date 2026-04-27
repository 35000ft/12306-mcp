from fastapi import APIRouter
from fastmcp import FastMCP, Context
from loguru import logger
from pydantic import Field

from next_train_mcp.mcp_next_train.functions import (
    _format_station_schedule,
    _format_station_train_info,
    _nmtr_request,
)
from next_train_mcp.mcp_next_train.obfuscator import LongIdObfuscator
from next_train_mcp.schemas import GenericResponse

mcp_next_train = FastMCP(name="next_train")

router = APIRouter()


@mcp_next_train.tool()
async def fetch_station_train_info(ctx: Context,
                                   station_id: str = Field(..., description='车站ID'),
                                   line_id: str = Field(..., description='线路ID')):
    """
    查询车站实时列车信息
    """
    try:
        obfuscated_line_id = LongIdObfuscator.id_to_code(int(line_id))
        path = f"/metro-realtime/realtime/train-info/station/v2/{station_id}/{obfuscated_line_id}"
        data = await _nmtr_request("POST", path)
        return GenericResponse(data=_format_station_train_info(data))
    except ValueError as e:
        return GenericResponse.error(str(e))
    except Exception as e:
        logger.error("查询车站列车信息失败", exc_info=e)
        return GenericResponse.error(f"查询失败: {e}")


@mcp_next_train.tool()
async def fetch_station_schedule(ctx: Context,
                                 station_id: str = Field(..., description='车站ID'),
                                 schedule_id: str = Field(..., description='时刻表ID')):
    """
    查询车站时刻表，返回格式化后的 Markdown 文本
    使用说明: 调用本工具前, 需先调用next_train_fetch_line_schedules工具获取线路的时刻表信息, 根据用户需要再传入相应的时刻表id和车站id
    """
    try:
        path = f"/metro-realtime/realtime/train-info/station/schedule/v3/{station_id}/{schedule_id}"
        data = await _nmtr_request("POST", path)
        return GenericResponse(data=_format_station_schedule(data))
    except ValueError as e:
        return GenericResponse.error(str(e))
    except Exception as e:
        logger.error("查询车站时刻表失败", exc_info=e)
        return GenericResponse.error(f"查询失败: {e}")


@mcp_next_train.tool()
async def fetch_line_schedules(ctx: Context,
                               line_id: str = Field(..., description='线路ID')):
    """
    查询线路使用的时刻表列表

    Response data 字段说明:
        - name: 时刻表名称，如 "2411-1号线周一至周四"
        - period: 适用星期几，如 [1,2,3,4] 表示周一至周四
        - lineId: 所属线路ID
        - scheduleId: 时刻表ID，可用于查询具体时刻
        - category: 时刻表分类，WORKDAY 工作日 / WEEKEND 周末
        - fromDate: 生效起始日期，格式 [年, 月, 日]
        - toDate: 生效结束日期，格式 [年, 月, 日]
        - specifiedDates: 指定日期，null 表示按周期生效
    """
    try:
        obfuscated_line_id = LongIdObfuscator.id_to_code(int(line_id))
        path = f"/metro-realtime/schedules/header/get/line/{obfuscated_line_id}"
        data = await _nmtr_request("GET", path)
        return GenericResponse(data=data)
    except ValueError as e:
        return GenericResponse.error(str(e))
    except Exception as e:
        logger.error("查询线路时刻表失败", exc_info=e)
        return GenericResponse.error(f"查询失败: {e}")
