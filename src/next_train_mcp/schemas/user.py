from pydantic import BaseModel


class LoginForm12306(BaseModel):
    username: str
    password: str
    id_last_4_digits: str


class LoginVerificationCode(BaseModel):
    code: str
    username: str
