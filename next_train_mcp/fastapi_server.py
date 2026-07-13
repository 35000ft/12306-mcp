import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

# Windows 上确保 Playwright 能创建子进程启动浏览器驱动
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastmcp import FastMCP
from fastmcp.server.middleware.logging import LoggingMiddleware
from loguru import logger

from next_train_mcp import __version__, mcp_12306
from next_train_mcp.mcp_12306 import mcp_12306_app
from next_train_mcp.mcp_common import mcp_common_app
from next_train_mcp.mcp_meteorology import mcp_meteo
from next_train_mcp.mcp_flight import mcp_flight_app
from next_train_mcp.mcp_next_train import mcp_next_train
from next_train_mcp.utils.config import get_settings

settings = get_settings()
SERVER_VERSION = __version__


async def setup(_app):
    for middleware in MIDDLEWARES:
        _app.add_middleware(middleware)
    await _app.import_server(mcp_12306_app, prefix="12306")
    await _app.import_server(mcp_common_app, prefix="common")
    await _app.import_server(mcp_flight_app, prefix="flight")
    await _app.import_server(mcp_next_train, prefix="next_train")
    await _app.import_server(mcp_meteo, prefix="meteo")


@dataclass
class AppContext:
    """Application context with typed dependencies."""

    pass


@asynccontextmanager
async def lifespan(_app) -> AsyncIterator[AppContext]:
    await setup(_app)
    yield AppContext()


@asynccontextmanager
async def combined_lifespan(_app):
    # Init MCP
    async with mcp_app.lifespan(_app):
        # Init FastAPI Cache
        FastAPICache.init(InMemoryBackend(), prefix="next-train-cache")
        yield


app = FastAPI(
    title="Next Train API Server with MCP Support",
    version=SERVER_VERSION,
    description=f"提供南京/广州/香港等多个城市轨道交通列车到站信息, 12306车票列车查询及一键购票等服务。"
                f"现已支持MCP服务, MCP端点: http://127.0.0.1:8000/mcp",
    debug=settings.debug,
)
# app.include_router(mcp_12306.router, prefix='/12306', tags=['12306服务'])

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
    lifespan=combined_lifespan,
)

if __name__ == "__main__":
    logger.info(f'Running environment: {os.getenv("ENV")}')
    if os.getenv("ENV") == "dev":
        import uvicorn

        uvicorn.run(
            "fastapi_server:combined_app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
