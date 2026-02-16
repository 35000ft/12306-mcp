from fastmcp import FastMCP
from loguru import logger

from next_train_mcp.schemas import GenericResponse

mcp_common_app = FastMCP(name="Common")


@mcp_common_app.tool()
async def get_current_time(timezone_str="Asia/Shanghai", date_format="YYYY-MM-DD") -> GenericResponse:
    """
    返回当前时间信息JSON格式
    """
    try:
        from datetime import datetime
        import pytz
        try:
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
        except pytz.exceptions.UnknownTimeZoneError:
            tz = pytz.timezone("Asia/Shanghai")
            now = datetime.now(tz)

        response_data = {
            "success": True,
            "timezone": tz.zone,
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": int(now.timestamp())
        }
        return GenericResponse(data=response_data)
    except Exception as e:
        logger.error(f"获取时间信息失败: {repr(e)}")
        return GenericResponse.error(f'获取时间信息失败, err:{e}')
