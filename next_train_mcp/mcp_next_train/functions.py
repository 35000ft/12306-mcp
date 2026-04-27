import os
from typing import Any

import httpx

from next_train_mcp.utils.config import get_settings

settings = get_settings()


def _get_base_url() -> str:
    url = settings.nmtr_api_baseurl or os.getenv("NMTR_API_BASEURL", "")
    return url.rstrip("/")


async def _nmtr_request(method: str, path: str, **kwargs) -> Any:
    """发送 NMTR API 请求并返回 data 字段"""
    base_url = _get_base_url()
    if not base_url:
        raise ValueError("NMTR_API_BASEURL 未配置")
    url = f"{base_url}{path}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.request(method, url, **kwargs)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("data") if isinstance(payload, dict) else payload


def _format_station_train_info(data: Any) -> str:
    """格式化车站实时列车信息"""
    if not data:
        return "暂无列车信息"

    trains = data if isinstance(data, list) else [data]
    lines = []

    lines.append("| 终点站 | 到达 | 发车 | 类型 |")
    lines.append("|--------|------|------|------|")
    for train in trains:
        if not isinstance(train, dict):
            continue
        terminal = train.get("terminal", "")
        arrival = train.get("arr", "")
        departure = train.get("dep", "")
        category = train.get("category", "")

        arrival_time = arrival[11:16] if len(arrival) > 16 else arrival
        departure_time = departure[11:16] if len(departure) > 16 else departure

        lines.append(
            f"| {terminal} | {arrival_time} | {departure_time} | {category} |"
        )

    return "\n".join(lines) if len(lines) > 2 else "暂无列车信息"


def _format_train_info_by_id(data: Any) -> str:
    """格式化单车列车信息"""
    if not data or not isinstance(data, dict):
        return "未找到列车信息"

    train_no = data.get("trainNo", data.get("train_no", "未知车次"))
    direction = data.get("direction", data.get("terminal", ""))
    current_station = data.get("currentStation", data.get("current_station", "未知"))
    next_station = data.get("nextStation", data.get("next_station", ""))
    status = data.get("status", "未知")
    delay = data.get("delay", 0)

    lines = [f"## 列车 {train_no} 实时信息"]
    if direction:
        lines.append(f"**运行方向**: {direction}")
    lines.append(f"**当前位置**: {current_station}")
    if next_station:
        lines.append(f"**下一站**: {next_station}")
    lines.append(f"**运行状态**: {status}")
    if delay:
        lines.append(f"**延误**: {delay} 分钟")
    else:
        lines.append("**延误**: 准点")

    return "\n".join(lines)


def _format_station_schedule(data: Any) -> str:
    """格式化车站时刻表为 Markdown"""
    if not data or not isinstance(data, dict):
        return "暂无时刻表信息"

    schedules = data.get("schedules", [])
    station_map = data.get("stationMap", {})

    if not schedules:
        return "暂无时刻表信息"

    lines = []

    for schedule_group in schedules:
        if not isinstance(schedule_group, dict):
            continue

        # 合并所有方向的列车并按时间排序
        all_trains = []
        dest_names = []

        for dest_id, trains in schedule_group.items():
            if not isinstance(trains, list):
                continue

            station_info = station_map.get(dest_id, {})
            dest_name = station_info.get("name", dest_id)
            dest_names.append(dest_name)

            for train in trains:
                if not isinstance(train, list) or len(train) < 2:
                    continue
                time_seconds = train[1]
                train_type = train[2][0] if len(train) > 2 and isinstance(train[2], list) else ""

                # 终点标记：河定桥 SHORT 标记为 "河"
                mark = ""
                if train_type == "SHORT":
                    mark = dest_name[:1]
                elif train_type and train_type != "LOCAL":
                    mark = train_type[0]

                all_trains.append({"time": time_seconds, "mark": mark})

        if not all_trains:
            continue

        if dest_names:
            lines.append(f"**开往**: *{'/'.join(dest_names)}*")
            lines.append("")

        # 按小时分组
        hours = {}
        for train in sorted(all_trains, key=lambda x: x["time"]):
            h = train["time"] // 3600
            m = (train["time"] % 3600) // 60
            mark = train["mark"]

            hour_key = str(h)
            if hour_key not in hours:
                hours[hour_key] = []

            minute_str = f"{m:02d}{mark}"
            hours[hour_key].append(minute_str)

        # Markdown 表格（每个分钟独立单元格，每行最多6个）
        lines.append("| 小时 | 分钟 | 分钟 | 分钟 | 分钟 | 分钟 | 分钟 |")
        lines.append("|------|------|------|------|------|------|------|")
        for h in sorted(hours.keys(), key=int):
            minute_list = hours[h]
            for i in range(0, len(minute_list), 6):
                chunk = minute_list[i:i + 6]
                hour_display = f"{h}时" if i == 0 else ""
                cells = [hour_display] + chunk + [""] * (6 - len(chunk))
                lines.append(f"| {' | '.join(cells)} |")

        lines.append("")

    return "\n".join(lines) if lines else "暂无时刻表信息"
