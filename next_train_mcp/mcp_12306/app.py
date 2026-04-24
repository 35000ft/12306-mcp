import china_railway_tools.api as cr_utils
from china_railway_tools.schemas import QueryTrainSchedule, QueryTrains
from fastapi import Request, APIRouter
from fastapi_cache import FastAPICache
from fastmcp import FastMCP, Context
from loguru import logger
from pydantic import Field

from next_train_mcp.schemas import GenericResponse, BuyTicketReq
from next_train_mcp.schemas.user import LoginForm12306, LoginVerificationCode
from next_train_mcp.services import ticket_service
from next_train_mcp.utils.cr12306_web_utils import Web12306Playwright
from next_train_mcp.utils.serializer import PydanticArgs, pydantic_serialize

mcp_12306_app = FastMCP(name="12306")

router = APIRouter()


@router.post("/login")
async def login_12306(request: Request, form: LoginForm12306):
    return await ticket_service.login_12306(request, form)


@router.post("/login_verification")
async def login_verification_12306(request: Request, form: LoginVerificationCode):
    return await ticket_service.login_verification_12306(request, form)


@mcp_12306_app.tool()
async def search_stations(ctx: Context,
                          query: str = Field(..., description='车站搜索关键词，支持：车站名称、拼音、简拼、三字码等'),
                          limit: int = Field(10, description='返回结果的最大数量，范围1-50')):
    """
    智能车站搜索。支持中文名、拼音、简拼、三字码（Code）。可用于模糊搜索（如“北京”），也可用于精确获取车站代码（如输入“BJP”返回北京站信息）。
    """
    try:
        query = query.strip()
        if not query:
            return GenericResponse.error("请输入搜索关键词")
        if limit < 1 or limit > 50:
            limit = 10
        params = {}
        if query.endswith("站"):
            params['exact'] = True
            query = query[:-1]
        stations = await cr_utils.query_station(query, limit=limit, **params)
        return GenericResponse(data={
            "query": query,
            "count": len(stations),
            "stations": pydantic_serialize(stations)
        })
    except Exception as e:
        logger.error("车站搜索失败", exc_info=e)
        return GenericResponse.error('车站搜索失败')


@mcp_12306_app.tool()
async def query_train_schedule(ctx: Context,
                               form: PydanticArgs[QueryTrainSchedule] = Field(
                                   description=f'{QueryTrainSchedule.model_json_schema()}')):
    f"""
    Query train schedule, including each stop arrival time and departure time
    """
    try:
        result = await cr_utils.query_train_schedule(form)
        return GenericResponse(data=result)
    except Exception as e:
        logger.error("查询列车时刻表失败", exc_info=e)
        return GenericResponse.error('查询列车时刻表失败')


@mcp_12306_app.tool()
async def query_ticket(ctx: Context,
                       form: PydanticArgs[QueryTrains] = Field(description=f'{QueryTrains.model_json_schema()}'),
                       limit: int = Field(10, description='限制返回条数')
                       ):
    """
       Query 12306 train tickets, including price, left ticket. Multiple condition filter supported.
       """
    result = await cr_utils.query_tickets(form, limit=limit)
    return GenericResponse(data=result[0:limit])


@mcp_12306_app.tool()
async def buy_ticket(ctx: Context,
                     form: PydanticArgs[BuyTicketReq] = Field(description=f'{BuyTicketReq.model_json_schema()}')):
    f"""
           Buy ticket via 12306 website
           """
    request = ctx.request_context.request
    app = request.app
    cache = FastAPICache.get_backend()
    session_key = f'12306_login_user_session_{form.username}'
    session_id = await cache.get(session_key)
    if not session_id or form.session_id != str(session_id):
        return GenericResponse.error("session_id不存在, 请重新登录")
    key = f'12306_browser_context_{form.username}'
    context = app.state.browser_dict.get(key)
    if not context:
        return GenericResponse.error("请先登录")
    p = Web12306Playwright(context)
    try:
        await p.buy_ticket(from_station=form.from_station, to_station=form.to_station, train_no=form.train_no,
                           date=form.date, passenger_names=form.passengers)
        return GenericResponse.error("下单成功, 请至12306应用程式支付订单")
    except ValueError as e:
        return GenericResponse.error(f"下单失败: {e}")
    except Exception as e:
        logger.error(f"12306下单失败:{e}", exc_info=e)
        return GenericResponse.error("下单失败")
