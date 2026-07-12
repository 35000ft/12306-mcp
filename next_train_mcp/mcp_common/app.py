from fastmcp import FastMCP
from loguru import logger
from pydantic import Field

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


@mcp_common_app.tool()
async def fetch_page_html(
    url: str = Field(..., description="目标网页地址"),
    wait_until: str = Field("networkidle", description='等待策略: "load" / "domcontentloaded" / "networkidle" / "commit"'),
    timeout: int = Field(30000, description="导航超时时间（毫秒）"),
    user_agent: str | None = Field(None, description="自定义 User-Agent，留空则使用默认 Windows Chrome"),
) -> GenericResponse:
    """
    使用 Playwright 获取网页渲染后的完整 HTML。

    适用于需要执行 JavaScript 的现代网页，例如 SPA 应用、动态加载内容的页面。
    返回完整的 <html>…</html> 源码，可用于后续的数据提取与分析。
    """
    try:
        from next_train_mcp.utils.playwright_utils import fetch_rendered_html

        html = await fetch_rendered_html(
            url=url,
            wait_until=wait_until,
            timeout=timeout,
            user_agent=user_agent or None,
        )
        return GenericResponse(data={
            "url": url,
            "html_length": len(html),
            "html": html,
        })
    except Exception as e:
        logger.error(f"获取网页 HTML 失败: {repr(e)}")
        return GenericResponse.error(f"获取网页 HTML 失败: {e}")
