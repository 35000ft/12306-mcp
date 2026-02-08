import asyncio
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from playwright.async_api import async_playwright, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from loguru import logger


async def handle_verification_code(page: Page, id_last_4_digits: str):
    try:
        await page.locator('#id_card').click()
        await page.locator('#id_card').type(id_last_4_digits)
    except PlaywrightTimeoutError:
        logger.info("No login verification code required")
        return
    logger.info("Require login verification code")
    await asyncio.sleep(0.5)
    # 获取验证码
    await page.locator('#verification_code').click()
    # TODO 等待验证码
    code = input("Enter verification code: ")
    await page.locator('#code').click()
    await page.locator('#code').type(code)
    await page.locator('#code').click()
    await page.locator('#sureClick').click()
    await page.wait_for_load_state('networkidle')
    await asyncio.sleep(5)


async def buy_ticket(page: Page, from_station: str, to_station: str, train_no: str,
                     passenger_names: List[str] = None,
                     date: datetime.date = datetime.today(), ):
    await page.goto('https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc')
    await page.wait_for_load_state('domcontentloaded')
    await page.click('#fromStationText')
    await page.evaluate(f"""navigator.clipboard.writeText("{from_station}")""")
    await page.keyboard.press('Control+V')
    await page.wait_for_load_state('networkidle')
    await asyncio.sleep(1)
    await page.keyboard.press('Enter')
    await page.click('#toStationText')
    await page.evaluate(f"""navigator.clipboard.writeText("{to_station}")""")
    await page.keyboard.press('Control+V')
    await asyncio.sleep(1)
    await page.keyboard.press('Enter')
    await page.click('#train_date')
    await page.fill('#train_date', date.strftime('%Y-%m-%d'))
    await page.keyboard.press('Enter')
    await asyncio.sleep(0.2)
    await page.click('#query_ticket')
    await page.wait_for_load_state('networkidle')
    try:
        await page.locator(
            f"xpath=//div[@class='train']//a[text()='{train_no}']/ancestor::td[1]/following-sibling::td/a[text()='预订']").click()
        await page.wait_for_load_state('load')
    except PlaywrightTimeoutError:
        raise ValueError("找不到该车次或该车次已售罄")

    # 选择乘车人
    if not passenger_names:
        try:
            await page.locator('#normal_passenger_id li input').first.click()
        except PlaywrightTimeoutError:
            raise ValueError("No passenger provided, No default passenger")
    else:
        selected_passenger_names = []
        for passenger_name in set(passenger_names):
            try:
                await page.locator(
                    f"xpath=//ul[@id='normal_passenger_id']/li/label[text()='{passenger_name}']/preceding-sibling::input[1]").first.click(
                    timeout=1)
                selected_passenger_names.append(passenger_name)
            except PlaywrightTimeoutError:
                logger.warning(f"Select passenger error, passenger name:{passenger_name}")
        logger.info(f"Selected passenger: {selected_passenger_names}")
        if not selected_passenger_names:
            raise ValueError("No passenger match the provided passengers")

        order_preview_img = Path('data/playwright/screenshots') / f'order_preview-{uuid.uuid4()}.png'
        await page.locator("#ticketInfo_id").first.screenshot(path=order_preview_img)

    try:
        await page.locator('#submitOrder_id').click()
    except PlaywrightTimeoutError:
        raise ValueError("Click submit order error")


async def login(page: Page, username: str, password: str, id_last_4_digits: str):
    await page.goto("https://kyfw.12306.cn/otn/resources/login.html")
    await page.locator('#J-userName').type(username)
    await asyncio.sleep(0.2)
    await page.locator('#J-password').type(password)
    await asyncio.sleep(0.2)
    await page.locator('#J-login').click()
    await handle_verification_code(page, id_last_4_digits)


async def main():
    user_data_dir = Path('data') / "playwright" / "user1"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False
        )
        page = await browser.new_page()

        await login(page, os.getenv('12306_USERNAME'),os.getenv('12306_PWD') , os.getenv('12306_ID_LAST_4DIGITS'))
        await buy_ticket(page, '南京南', '杭州东', train_no='G1861', )
        await browser.close()


asyncio.run(main())
