import china_railway_tools.api as cr_utils
from china_railway_tools.schemas import QueryTrainSchedule
from fastapi import Request, APIRouter
from fastmcp import FastMCP

from next_train_mcp.schemas import GenericResponse
from next_train_mcp.schemas.user import LoginForm12306, LoginVerificationCode
from next_train_mcp.services import ticket_service

mcp_next_train = FastMCP(name="next_train")

router = APIRouter()
