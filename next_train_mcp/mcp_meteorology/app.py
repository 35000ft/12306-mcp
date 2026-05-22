import base64
import json

import httpx
from fastmcp import FastMCP
from loguru import logger

from next_train_mcp.mcp_meteorology.radar import get_radar_image as _get_radar_image, get_radar_stations
from next_train_mcp.schemas import GenericResponse
from next_train_mcp.utils.dify_client import DifyAIClient

mcp_meteo = FastMCP(name="Meteorology")


@mcp_meteo.tool()
async def get_radar_image(city: str, with_analysis: bool = False):
    """
    查询雷达图
    :param with_analysis: 是否需要AI解读
    :param city: 城市名或雷达站点名
    :return 图片的url和base64编码的图片内容
    """
    try:
        img_url = await _get_radar_image(city)
        contents = [
            {
                "type": "image_url",
                "image_url": img_url
            },

        ]
        if with_analysis:
            client = DifyAIClient('ANALYSIS_IMAGE')
            response = await client.run_workflow(
                inputs={"image": {
                    "type": "image",
                    "transfer_method": "remote_url",
                    "url": img_url
                }, 'query': '简要分析雷达图, 指出图中主要区域的天气雷达信息, 不得扩展'})
            analysis = response.data.outputs
            contents.append({
                "description": "对天气图的分析",
                "type": "text",
                "text": analysis
            })
        return {
            "content": contents
        }
    except Exception as e:
        logger.error(f"获取雷达图失败: {e}")
        return {
            "content": [{"type": "text", "text": f"获取雷达图失败: {e}"}],
            "isError": True
        }


@mcp_meteo.tool()
async def get_supported_radar_stations():
    s = await get_radar_stations()
    return {
        "content": [{"type": "text", "text": json.dumps(s, ensure_ascii=False)}]
    }


@mcp_meteo.tool()
async def get_airport_metar(airport_icao_code: str):
    """
    获取机场天气metar信息
    :param airport_icao_code: ICAO代码 (4 letters)
    :return: json
    解释 {name} (ICAO代码: {airport_icao_code})
        报告时间: {reportTime} (UTC)
        接收时间: {receiptTime} (UTC)
        温度: {temp}°C, 露点: {dewp}°C
        风向: {wind_speed_obj.get("direction")} 风速: {wind_speed_obj.get('speed')} {wind_speed_obj.get('unit')}
        能见度: {visib}
        气压: {altim} hPa
        云层信息: {', '.join([f"{cloud.cover} {f'{cloud.base}ft' if cloud.base else ''}" for cloud in clouds])}
        METAR原始报告: {rawOb}
        TAF原始预报: {rawTaf}
    """
    url = 'https://aviationweather.gov/api/data/metar'
    params = {
        'ids': airport_icao_code,
        "format": 'json',
        "taf": True
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        j_obj = resp.json()
        if len(j_obj) == 0:
            return GenericResponse.error("Unsupported Airport Code")
        return GenericResponse.ok(j_obj[0])
