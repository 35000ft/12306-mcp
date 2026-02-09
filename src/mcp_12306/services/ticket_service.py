import asyncio

from fastapi import FastAPI, Request
from loguru import logger

from mcp_12306.utils.command_manager import command_manager
from mcp_12306.schemas import GenericResponse, Status

from mcp_12306.utils.cr12306_web_utils import Web12306Playwright
from mcp_12306.schemas.user import LoginForm12306, LoginVerificationCode


async def auto_close_context(ctx, delay):
    try:
        await asyncio.sleep(delay)
        await ctx.close()
        logger.info("Context auto closed by TTL")
    except asyncio.CancelledError:
        pass


async def login_12306(request: Request, form: LoginForm12306):
    key = f'12306_{form.username}'
    app = request.app
    context = app.state.browser_dict.get(key)
    if not context:
        async with app.state.pw_semaphore:
            if len(app.state.browser_dict) >= 5:
                return GenericResponse(status=Status.FAIL, msg="当前服务繁忙, 请稍后重试")
            context = await app.state.browser.new_context()
            app.state.browser_dict[key] = context
            CONTEXT_TTL = 15 * 60  # 15 分钟
            auto_close_task = asyncio.create_task(
                auto_close_context(context, CONTEXT_TTL)
            )
    p = Web12306Playwright(context)
    await p.login(form.username, form.password, form.id_last_4_digits)
    return GenericResponse(status=Status.SUCCESS, msg="验证码已发送")


async def login_verification_12306(request: Request, form: LoginVerificationCode):
    app = request.app
    key = f'12306_{form.username}'
    context = app.state.browser_dict.get(key)
    if not context:
        return GenericResponse(status=Status.FAIL, msg="登录请求已过期，请重新调用login接口获取新的验证码")
    result_key = f'12306_login_verification_code_{form.username}'
    await command_manager.set_result(result_key, form.code)
    login_result_key = f'12306_login_verification_result_{form.username}'
    try:
        result = await command_manager.get_result(login_result_key, timeout=60)
        return GenericResponse(**result)
    except asyncio.TimeoutError:
        return GenericResponse(status=Status.FAIL, msg="登录操作失败，请重新登录")


async def buy_ticket(form: LoginVerificationCode):
    pass
