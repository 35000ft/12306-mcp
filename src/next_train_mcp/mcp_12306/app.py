import china_railway_tools.api as cr_utils
from china_railway_tools.schemas import QueryTrainSchedule
from fastapi import Request, APIRouter
from fastmcp import FastMCP

from next_train_mcp.schemas import GenericResponse
from next_train_mcp.schemas.user import LoginForm12306, LoginVerificationCode
from next_train_mcp.services import ticket_service

mcp_12306_app = FastMCP(name="12306")

router = APIRouter()


@router.post("/login")
async def login_12306(request: Request, form: LoginForm12306):
    return await ticket_service.login_12306(request, form)


@router.post("/login_verification")
async def login_verification_12306(request: Request, form: LoginVerificationCode):
    return await ticket_service.login_verification_12306(request, form)


@mcp_12306_app.tool()
async def query_train_schedule(ctx, form: QueryTrainSchedule):
    """
    查询指定车次的所有经停站及时刻信息。
    参数: train_no(列车编号或车次号), from_station(出发站), to_station(到达站), train_date(日期)
    自动检测输入是车次号还是列车编号，如果是车次号则先转换为列车编号。
    """
    try:
        result = await cr_utils.query_train_schedule(form)
        return GenericResponse(data=result)
    except Exception as e:
        return GenericResponse.error('查询列车时刻表失败')
