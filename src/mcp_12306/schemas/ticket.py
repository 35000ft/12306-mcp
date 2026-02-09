import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BuyTicketReq(BaseModel):
    username: str
    session_id: str
    from_station: str
    to_station: str
    train_no: str
    date: datetime.date = Field(default_factory=datetime.date.today)
    passengers: Optional[List[str]] = Field([], title='乘客列表')
