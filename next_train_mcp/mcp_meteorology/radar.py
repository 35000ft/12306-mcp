import asyncio
import json
import os
import random
import urllib.parse
from pathlib import Path

from loguru import logger
import aiofiles
import httpx
from lxml import etree

headers = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
}
base_url = 'http://www.nmc.cn'

init_lock = False
radar_station_filepath = Path('data') / 'cma/cma-radar-stations.json'
RADAR_STATIONS = None


def calc_text_similarity(target: str, to_compare: str) -> float:
    if to_compare not in target:
        return 0.0
    set1, set2 = set(target), set(to_compare)
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union


async def get_radar_stations():
    global RADAR_STATIONS
    if RADAR_STATIONS:
        return RADAR_STATIONS
    if os.path.exists(radar_station_filepath):
        async with aiofiles.open(radar_station_filepath, mode='r') as f:
            RADAR_STATIONS = json.loads(await f.read())
        return RADAR_STATIONS
    else:
        if init_lock:
            raise Exception("雷达站信息正在初始化中, 请稍后重试")
        await init_radar_stations()
        return await get_radar_stations()


async def find_radar_station_url(station_name: str):
    radar_stations = await get_radar_stations()
    stations: dict = radar_stations['city_url']
    if url := stations.get(station_name):
        return url
    city_names = list(stations.keys())
    max_similarity = 0.0
    most_similar_city = None

    for city_name in city_names:
        similarity = calc_text_similarity(city_name, station_name)
        if similarity > max_similarity:
            max_similarity = similarity
            most_similar_city = city_name

    # 如果找到了相似度最高的城市
    if most_similar_city:
        return stations.get(most_similar_city)
    return None


async def get_radar_image(station_name: str):
    url = await find_radar_station_url(station_name)
    if not url:
        raise Exception(f"没有找到 {station_name} 这个雷达站哦")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        tree = etree.HTML(resp.text)
        img_url = tree.xpath("//img[@id='imgpath']/@src")
        if not img_url:
            raise Exception("获取雷达图失败")
        return img_url[0]


async def init_radar_stations():
    async def fetch_province(_url: str):
        async with httpx.AsyncClient() as _client:
            _resp = await _client.get(_url)
            _resp.raise_for_status()
            _tree = etree.HTML(_resp.text)
            city_list = _tree.xpath("//div[contains(text(),'城市/地区')]/following-sibling::*[1]/li/a")
            __url_dict = {}
            province = _tree.xpath(
                "//div[contains(text(),'省份/市')]/following-sibling::*[1]/li/a[@class='actived']/text()")[0]
            city_names = [x.text.strip() for x in city_list]

            for city_a in city_list:
                city_name = city_a.text.strip()
                city_url = urllib.parse.urljoin(base_url, city_a.attrib.get('href'))
                if city_url and city_name:
                    url_dict[city_name] = city_url
                else:
                    raise Exception(f"URL not found, city:{city_name} url:{_url}")
            return __url_dict, {province: city_names}

    global init_lock
    if not init_lock:
        init_lock = True
    else:
        raise Exception("Lock already initialized")
    logger.info('initialing radar stations data')
    start_url = 'http://www.nmc.cn/publish/radar/bei-jing/da-xing.htm'
    region_url = 'http://www.nmc.cn/publish/radar/chinaall.html'

    url_dict = {}
    province_city_dict = {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(start_url, headers=headers)
        resp.raise_for_status()
        tree = etree.HTML(resp.text)
        province_urls = tree.xpath("//div[contains(text(),'省份/市')]/following-sibling::*[1]/li/a/@href")

        resp = await client.get(region_url, headers=headers)
        resp.raise_for_status()
        tree = etree.HTML(resp.text)
        regions = tree.xpath("//div[contains(text(),'区域')]/following-sibling::*[1]/li/a")
        for region_a in regions:
            region_name = region_a.text.strip()
            region_url = urllib.parse.urljoin(base_url, region_a.attrib.get('href'))
            if region_url and region_name:
                url_dict[region_name] = region_url

    for url in province_urls:
        _url_dict, province_cities = await fetch_province(urllib.parse.urljoin(base_url, url))
        url_dict.update(_url_dict)
        province_city_dict.update(province_cities)
        await asyncio.sleep(random.uniform(1, 2))

    result = {
        'city_url': url_dict,
        'province_city': province_city_dict
    }
    result = json.dumps(result, ensure_ascii=False)
    filedir = os.path.dirname(radar_station_filepath)
    if not os.path.exists(os.path.dirname(radar_station_filepath)):
        os.makedirs(filedir)
    filepath = os.path.join(radar_station_filepath)
    async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
        await f.write(result)
