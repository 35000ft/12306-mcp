import asyncio
import os
import uuid
import datetime
from pathlib import Path
from typing import List

from fastapi_cache import FastAPICache
from loguru import logger
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, BrowserContext
from playwright.async_api import async_playwright, Page

from mcp_12306.utils.command_manager import command_manager


class Web12306Playwright:
    context: BrowserContext
    page: Page

    def __init__(self, context: BrowserContext):
        self.context = context
        self.page = None
        if self.context.pages:
            self.page = self.context.pages[0]

    async def get_page(self, require_context: bool = False) -> Page:
        if self.page is None:
            if require_context:
                raise Exception("This operation need a preceding page")
            self.page = await self.context.new_page()
            return self.page
        else:
            return self.page

    async def login(self, username: str, password: str, id_last_4_digits: str):
        page = await self.get_page()
        await page.goto("https://kyfw.12306.cn/otn/resources/login.html")
        await page.locator('#J-userName').type(username)
        await asyncio.sleep(0.2)
        await page.locator('#J-password').type(password)
        await asyncio.sleep(0.2)
        await page.locator('#J-login').click()
        await self.handle_verification_code(username, id_last_4_digits)

    async def handle_verification_code(self, username: str, id_last_4_digits: str):
        page = await self.get_page(require_context=True)
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
        code_key = f'12306_login_verification_code_{username}'
        try:
            # 等待验证码
            code = await command_manager.get_result(code_key, timeout=3 * 60)
        except TimeoutError:
            raise ValueError("等待验证码超时，请重新登录")
        login_result_key = f'12306_login_verification_result_{username}'
        await page.locator('#code').click()
        await page.locator('#code').type(code)
        await page.locator('#code').click()
        await page.locator('#sureClick').click()
        await page.wait_for_load_state('load')
        await page.wait_for_load_state('networkidle')
        await page.wait_for_load_state('domcontentloaded')
        cache = FastAPICache.get_backend()
        is_success = await page.locator('.logout,a').count() > 0
        if is_success:
            session_id = uuid.uuid4()
            await cache.set(f'12306_login_user_session_{username}', session_id, 10 * 60)
            await command_manager.set_result(login_result_key,
                                             {'msg': "登录12306成功", 'data': {'session_id': session_id},
                                              'status': 'success'})
        else:
            await command_manager.set_result(login_result_key,
                                             {'msg': "登录失败，请检查账户与密码是否匹配", 'status': 'fail'})
            raise ValueError("登录失败，请检查账户与密码是否匹配")

    async def buy_ticket(self, from_station: str, to_station: str, train_no: str,
                         passenger_names: List[str] = None,
                         date: datetime.date = datetime.date.today(), ):
        page = await self.get_page()
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


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            headless=False
        )
        p = Web12306Playwright(browser)
        await p.login(os.getenv('12306_USERNAME'), os.getenv('12306_PWD'), os.getenv('12306_ID_LAST_4DIGITS'))
        await p.buy_ticket('南京南', '杭州东', train_no='G1861', )
        await browser.close()


# 解析票务字符串

def parse_ticket_string(ticket_str, query):
    parts = ticket_str.split('|')
    if len(parts) < 35:
        return None
    return {
        "train_no": parts[3],
        "start_time": parts[8],
        "arrive_time": parts[9],
        "duration": parts[10],
        "business_seat_num": parts[32] or "",
        "first_class_num": parts[31] or "",
        "second_class_num": parts[30] or "",
        "advanced_soft_sleeper_num": parts[21] or "",
        "soft_sleeper_num": parts[23] or "",
        "dongwo_num": parts[33] or "",
        "hard_sleeper_num": parts[28] or "",
        "soft_seat_num": parts[24] or "",
        "hard_seat_num": parts[29] or "",
        "no_seat_num": parts[26] or "",
        "from_station": query["from_station"],
        "to_station": query["to_station"],
        "train_date": query["train_date"]
    }


if __name__ == '__main__':
    asyncio.run(main())
