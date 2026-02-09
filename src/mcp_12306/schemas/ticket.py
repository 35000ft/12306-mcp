from pydantic import BaseModel


class BuyTicket(BaseModel):
    username: str
    session_id: str
