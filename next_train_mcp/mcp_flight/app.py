import re
from datetime import date as date_type

from fastmcp import FastMCP
from loguru import logger
from pydantic import Field

from next_train_mcp.schemas import GenericResponse

mcp_flight_app = FastMCP(name="flight_tracker")

# ── 航班号解析 ─────────────────────────────────────────────────────────

_FLIGHT_RE = re.compile(
    r"^\s*(?P<airline>[A-Za-z]{2,3})\s*[/\s-]?\s*(?P<number>\d+)\s*$"
)


def _parse_flight_number(raw: str) -> tuple[str, str]:
    """解析航班号，返回 (航空公司代码, 航班数字)。

    "TK70" / "TK 70" / "TK/70" / "TK-70" → ("TK", "70")
    """
    m = _FLIGHT_RE.match(raw.strip())
    if not m:
        raise ValueError(
            f"无法解析航班号「{raw}」，格式示例：TK70 / CZ3101 / MU 1234"
        )
    return m.group("airline").upper(), m.group("number")


# ── 页面文本解析 ───────────────────────────────────────────────────────

def _parse_page_text(text: str) -> dict:
    """从 FlightView 页面可见文本中提取结构化的航班信息。"""

    data: dict[str, object] = {}

    # 标题行: "Turkish Airlines (TK) 70"
    title_m = re.search(r"\(([A-Z0-9]+)\)\s*(\d+)", text)
    if title_m:
        data["airline_code"] = title_m.group(1)
        data["flight_number"] = title_m.group(2)

    # 航班状态: "Arrived" / "Delayed" / "On Time" / "Cancelled" / "Scheduled"
    status_m = re.search(
        r"FLIGHT\s*STATUS\s*\n+\s*(.+?)\s*\n",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if status_m:
        data["status"] = status_m.group(1).strip()

    # ── 出发信息 ──
    dep = _extract_section(text, "Departure", "Arrival")
    if dep:
        data["departure"] = dep

    # ── 到达信息 ──
    arr = _extract_section(text, "Arrival", "Flight Details")
    if not arr:
        arr = _extract_section(text, "Arrival", None)
    if arr:
        data["arrival"] = arr

    # ── 机型 ──
    aircraft_m = re.search(r"Aircraft\s+([^\n]+)", text)
    if aircraft_m:
        data["aircraft"] = aircraft_m.group(1).strip()

    return data


def _extract_section(text: str, start: str, end: str | None) -> dict[str, str] | None:
    """提取文本中 start → end 之间的键值对区域。

    每行格式为 "Key\tValue" 或 "Key: Value"。
    """
    if end:
        pat = re.escape(start) + r"\s*\n(.*?)\n" + re.escape(end)
    else:
        pat = re.escape(start) + r"\s*\n(.*)"
    m = re.search(pat, text, re.DOTALL)
    if not m:
        return None

    block = m.group(1).strip()
    result: dict[str, str] = {}
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        # "Key:\tValue" 或 "Key:\s+Value" 或 "Key\tValue"
        kv = re.split(r":\s*|\t+", line, maxsplit=1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip()
            if key and val and key not in (
                "More airport info",
                "Departures",
                "Arrivals",
                "Weather",
            ):
                result[key] = val
    return result if result else None


# ── MCP 工具 ───────────────────────────────────────────────────────────

@mcp_flight_app.tool()
async def track_flight(
    flight_number: str = Field(
        ...,
        description='航班号，例如 "TK70"、"CZ3101"、"MU 1234"、"TK/70"',
    ),
    flight_date: str | None = Field(
        None,
        description='航班日期，格式 YYYY-MM-DD（可选，默认为今天）',
    ),
) -> GenericResponse:
    """
    查询全球航班实时状态与详情。

    使用 FlightView 数据源，返回航班的出发/到达机场、计划与实际时间、
    航站楼、登机口、行李转盘、机型等信息。
    """
    try:
        # 1. 解析航班号
        airline, number = _parse_flight_number(flight_number)
        flight_date = flight_date or date_type.today().isoformat()

        # 2. 验证日期格式
        date_type.fromisoformat(flight_date)

        url = f"https://www.flightview.com/flight-tracker/{airline}/{number}?date={flight_date}"
        logger.info(f"Fetching flight data: {url}")

        # 3. 获取渲染后页面文本
        from next_train_mcp.utils.playwright_utils import fetch_page_text

        text = await fetch_page_text(url, timeout=30000, extra_wait=6)

        if not text or len(text.strip()) < 100:
            return GenericResponse.error(
                f"未能获取到航班 {airline}{number} 的信息（{flight_date}），"
                f"请确认航班号与日期是否正确，或该航班暂不支持"
            )

        # 4. 解析结构化数据
        data = _parse_page_text(text)

        if not data:
            return GenericResponse.error(
                f"无法解析航班 {airline}{number} 的页面数据"
            )

        data["flight_number_display"] = f"{airline}{number}"
        data["source_url"] = url
        data["query_date"] = flight_date

        return GenericResponse(data=data)

    except ValueError as e:
        return GenericResponse.error(str(e))
    except Exception as e:
        logger.error(f"查询航班失败: {repr(e)}")
        return GenericResponse.error(f"查询航班失败: {e}")
