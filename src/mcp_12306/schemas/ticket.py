import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BuyTicketReq(BaseModel):
    username: str = Field(title="用户名", description="12306 登录用户名")
    session_id: str = Field(title="会话ID", description="登录后返回的 session_id")
    from_station: str = Field(title="出发站")
    to_station: str = Field(title="到达站")
    train_no: str = Field(title="车次号")
    date: datetime.date = Field(
        default_factory=datetime.date.today,
        title="出发日期",
        description="乘车日期，默认当天"
    )
    passengers: Optional[List[str]] = Field(
        default=[],
        title="乘客列表",
        description="乘车人姓名列表"
    )
