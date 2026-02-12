import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.middleware.logging import LoggingMiddleware

from next_train_mcp import __version__, mcp_12306
from next_train_mcp.mcp_12306 import mcp_12306_app
from next_train_mcp.utils.config import get_settings

settings = get_settings()
SERVER_VERSION = __version__


async def setup(_app):
    for middleware in MIDDLEWARES:
        _app.add_middleware(middleware)
    await _app.import_server(mcp_12306_app, prefix="12306")


@dataclass
class AppContext:
    """Application context with typed dependencies."""

    pass


@asynccontextmanager
async def lifespan(_app) -> AsyncIterator[AppContext]:
    await setup(_app)
    yield AppContext()


app = FastAPI(
    title="Next Train API Server with MCP Support",
    version=SERVER_VERSION,
    description=f"提供南京/广州/香港等多个城市轨道交通列车到站信息, 12306车票列车查询及一键购票等服务。"
                f"现已支持MCP服务, MCP端点: http://127.0.0.1:8000/mcp",
    debug=settings.debug,
)
app.include_router(mcp_12306.router, prefix='/12306', tags=['12306服务'])

mcp = FastMCP("Next Train", lifespan=lifespan)

# Create ASGI app from MCP server
mcp_app = mcp.http_app(path='/mcp')

MIDDLEWARES = [
    LoggingMiddleware(),
]

combined_app = FastAPI(
    title="Next Train API Server with MCP Support",
    routes=[
        *mcp_app.routes,
        *app.routes,
    ],
    lifespan=mcp_app.lifespan,
)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fastapi_server:combined_app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
