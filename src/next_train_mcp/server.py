import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Dict

import china_railway_tools.api as cr_utils
from china_railway_tools.schemas import QueryTrains, QueryTrainSchedule
import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from playwright.async_api import async_playwright

from next_train_mcp.schemas import BuyTicketReq
from next_train_mcp.schemas.user import LoginForm12306, LoginVerificationCode
from next_train_mcp.services import ticket_service, station_service
from . import __version__
from .utils.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# MCP Protocol Version - Support 2025-03-26 Streamable HTTP transport
MCP_PROTOCOL_VERSION = "2025-03-26"  # Updated to latest protocol version
SERVER_NAME = "mcp-server-12306"
SERVER_VERSION = __version__

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# Connected clients for session management
connected_clients: Dict[str, Dict] = {}

# MCP Tools Definition according to spec
MCP_TOOLS = [
    {
        "name": "query-ticket-price",
        "description": "查询火车票价信息。输入出发站、到达站、日期，返回各车次的票价详情。支持指定车次号过滤。\n\n【智能筛选指南】返回结果通常包含出发/到达城市的所有相关车站（如北京/北京西/北京南）。请根据用户输入语境灵活处理：\n1. 用户仅输入城市名（如'九江'）：请展示所有相关站点的车次，不要过滤。\n2. 用户指定具体车站（如'九江站'）：优先展示匹配车站的车次，但若其他同城车站有更优方案（如时间更短、有票），也应作为补充选项提供。\n请避免机械地仅通过字符串匹配过滤车次，以免遗漏用户可能感兴趣的出行方案。",
        "inputSchema": QueryTrains.model_json_schema(),
    },
    {
        "name": "search-stations",
        "description": "智能车站搜索。支持中文名、拼音、简拼、三字码（Code）。可用于模糊搜索（如“北京”），也可用于精确获取车站代码（如输入“BJP”返回北京站信息）。",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "车站搜索参数",
            "description": "搜索火车站所需的参数",
            "properties": {
                "query": {"type": "string", "title": "搜索关键词",
                          "description": "车站搜索关键词，支持：车站名称、拼音、简拼等", "minLength": 1, "maxLength": 20},
                "limit": {"type": "integer", "title": "结果数量限制", "description": "返回结果的最大数量", "minimum": 1,
                          "maximum": 50, "default": 10}
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "query-transfer",
        "description": "官方中转换乘方案查询。输入出发站、到达站、日期，可选中转站/无座/学生票，自动分页抓取全部中转方案，输出每段车次、时刻、余票、等候时间、总历时等详细信息。",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "中转查询参数",
            "description": "查询A到B的中转换乘（含一次换乘）",
            "properties": {
                "from_station": {"type": "string", "title": "出发站"},
                "to_station": {"type": "string", "title": "到达站"},
                "train_date": {"type": "string", "title": "出发日期", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                "middle_station": {"type": "string", "title": "中转站（可选）",
                                   "description": "指定中转站名称或三字码，可选"},
                "isShowWZ": {"type": "string", "title": "是否显示无座车次（Y/N）",
                             "description": "Y=显示无座车次，N=不显示，默认N", "default": "N"},
                "purpose_codes": {"type": "string", "title": "乘客类型（00=普通，0X=学生）",
                                  "description": "00为普通，0X为学生，默认00"}
            },
            "required": ["from_station", "to_station", "train_date"],
            "additionalProperties": False
        }
    },
    {
        "name": "query-train-schedule",
        "description": "列车经停站全表查询。支持输入车次号或官方编号，自动转换，返回所有经停站、到发时刻、停留时间。支持三字码/全名。",
        "inputSchema": QueryTrainSchedule.model_json_schema()
    },
    {
        "name": "get-current-time",
        "description": "获取当前日期和时间信息，支持相对日期计算。返回当前日期、时间，以及常用的相对日期（明天、后天等），方便用户在查询火车票时选择正确的日期。",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "获取当前时间参数",
            "description": "获取当前时间和日期信息",
            "properties": {
                "timezone": {"type": "string", "title": "时区", "description": "时区设置，默认为中国时区",
                             "default": "Asia/Shanghai"},
                "format": {"type": "string", "title": "日期格式", "description": "返回的日期格式，默认为YYYY-MM-DD",
                           "default": "YYYY-MM-DD"}
            },
            "additionalProperties": False
        }
    },
    {
        "name": "12306-buy-ticket",
        "description": "操作12306网页购买车票，需要登录",
        "inputSchema": BuyTicketReq.model_json_schema()
    }
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pw_semaphore = asyncio.Semaphore(1)
    app.state.browser_dict = {}
    app.state.playwright = await async_playwright().start()
    app.state.browser = await app.state.playwright.chromium.launch(
        headless=True if os.getenv('ENV') == 'prod' else False,
    )

    FastAPICache.init(
        InMemoryBackend(),
        prefix="fastapi-cache"
    )

    logger.info("Playwright started")

    try:
        yield
    finally:
        # ===== 关闭阶段 =====
        await app.state.browser.close()
        await app.state.playwright.stop()
        logger.info("Playwright stopped")


app = FastAPI(
    title=SERVER_NAME,
    version=SERVER_VERSION,
    description=f"基于MCP协议(2025-03-26 Streamable HTTP)的12306火车票查询服务，支持直达、过站和换乘查询",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
async def root():
    return {
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
        "status": "running",
        "mcp_endpoint": "/mcp",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "transport": "Streamable HTTP (2025-03-26)",
        "tools": [tool["name"] for tool in MCP_TOOLS],
        "active_sessions": len(connected_clients)
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(connected_clients)
    }


@app.get("/schema/tools")
async def get_tools_schema():
    return {
        "tools": MCP_TOOLS,
        "schema_version": "http://json-schema.org/draft-07/schema#"
    }


# MCP Streamable HTTP Transport Endpoints (2025-03-26 spec)

@app.options("/mcp")
async def mcp_options():
    """Handle CORS preflight for /mcp endpoint"""
    return JSONResponse(
        {},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id",
        }
    )


@app.get("/mcp")
async def mcp_endpoint_get(request: Request):
    """MCP Streamable HTTP Endpoint - GET for SSE connection (optional)"""
    # Generate session ID for this connection
    session_id = str(uuid.uuid4())
    logger.info(f"New MCP GET connection established - Session ID: {session_id}")

    # Store client connection info
    connected_clients[session_id] = {
        "connected_at": datetime.now().isoformat(),
        "user_agent": request.headers.get("user-agent", ""),
        "client_ip": request.client.host if request.client else "unknown",
        "initialized": False,
        "protocol_version": MCP_PROTOCOL_VERSION
    }

    async def generate_events():
        try:
            # Keep connection alive with periodic pings
            while True:
                await asyncio.sleep(30)  # Send ping every 30 seconds
                payload = {
                    "jsonrpc": "2.0",
                    "method": "mcp/ping",  # 或 notifications/ping
                    "params": {
                        "timestamp": datetime.now().isoformat()
                    }
                }

                yield (
                        "event: message\n"
                        "data: " + json.dumps(payload) + "\n\n"
                )

        except asyncio.CancelledError:
            logger.info(f"MCP GET connection closed - Session ID: {session_id}")
            # Clean up client connection
            if session_id in connected_clients:
                del connected_clients[session_id]
        except Exception as e:
            logger.error(f"MCP GET error for session {session_id}: {e}")
            # Clean up client connection
            if session_id in connected_clients:
                del connected_clients[session_id]

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Mcp-Session-Id": session_id  # Return session ID in header
        }
    )


@app.post("/mcp")
async def mcp_endpoint_post(request: Request):
    """MCP Streamable HTTP Endpoint - POST for JSON-RPC messages"""
    request_id = None
    _app = request.app
    try:
        data = await request.json()

        # Validate JSON-RPC 2.0 format
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
            raise HTTPException(status_code=400, detail="Invalid JSON-RPC 2.0 message")

        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id")

        if not method:
            raise HTTPException(status_code=400, detail="Method is required")

        logger.info(f"Received MCP request: {method} (ID: {request_id})")

        # Handle initialization - no session ID required for this
        if method == "initialize":
            client_capabilities = params.get("capabilities", {})
            client_protocol_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION)
            client_info = params.get("clientInfo", {})

            logger.info(f"Initialize request - Client Protocol: {client_protocol_version}")
            logger.info(f"Client Info: {client_info}")

            # Generate new session ID for this client
            session_id = str(uuid.uuid4())

            # Store session info
            connected_clients[session_id] = {
                "connected_at": datetime.now().isoformat(),
                "user_agent": request.headers.get("user-agent", ""),
                "client_ip": request.client.host if request.client else "unknown",
                "initialized": False,
                "protocol_version": client_protocol_version
            }

            # Accept the client's protocol version or use our default
            accepted_version = client_protocol_version if client_protocol_version else MCP_PROTOCOL_VERSION

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": accepted_version,
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                        "description": "12306火车票查询服务，提供车票查询、车站搜索、中转查询等功能"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            }

            # Return response with Mcp-Session-Id header
            logger.info(f"Initialize response sent - Protocol: {accepted_version}, Session: {session_id}")
            return JSONResponse(
                response,
                headers={
                    "Mcp-Session-Id": session_id,
                    "Access-Control-Allow-Origin": "*"
                }
            )

        # For all other methods, require session ID
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            logger.error("Missing Mcp-Session-Id header for non-initialize request")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Bad Request: No valid session ID provided"
                    }
                },
                status_code=400
            )

        # Validate session exists
        if session_id not in connected_clients:
            logger.error(f"Invalid session ID: {session_id}")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Invalid session ID"
                    }
                },
                status_code=404  # Use 404 for invalid session as per spec
            )

        logger.info(f"Processing message for session: {session_id}")

        # Handle tool listing
        if method == "tools/list":
            logger.info("Tools list requested")
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": MCP_TOOLS
                }
            }
            return JSONResponse(response)

        # Handle tool execution
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not tool_name:
                raise HTTPException(status_code=400, detail="Tool name is required")

            logger.info(f"Executing tool: {tool_name}")
            logger.info(f"Arguments: {arguments}")

            # Execute the appropriate tool
            try:
                # Map tool names with hyphens to underscores for internal functions
                if tool_name == "query-ticket-price":
                    content = await ticket_service.query_ticket_price_validated(QueryTrains.model_validate(arguments))
                elif tool_name == "search-stations":
                    content = await station_service.search_station(arguments)
                elif tool_name == "query-transfer":
                    content = await query_transfer_validated(arguments)
                elif tool_name == "query-train-schedule":
                    content = await ticket_service.query_train_schedule(QueryTrainSchedule.model_validate(arguments))
                elif tool_name == "get-current-time":
                    content = await get_current_time_validated(arguments)
                elif tool_name == '12306-buy-ticket':
                    content = await ticket_service.buy_ticket(_app, BuyTicketReq.model_validate(arguments))
                else:
                    content = [{
                        "type": "text",
                        "text": f"未知工具: {tool_name}"
                    }]

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": content,
                        "isError": False
                    }
                }
                logger.info(f"Tool {tool_name} executed successfully")

            except Exception as tool_error:
                logger.error(f"Tool execution error: {tool_error}", exc_info=tool_error)
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": f"工具执行失败: {str(tool_error)}"
                        }],
                        "isError": True
                    }
                }

            return JSONResponse(response)

        # Handle notifications (no response required)
        elif method and method.startswith("notifications/"):
            notification_type = method.replace("notifications/", "")
            logger.info(f"Received notification: {notification_type}")

            # Process notification but don't send response
            if notification_type == "initialized":
                logger.info("Client initialized successfully - MCP handshake complete!")
                # Mark session as fully initialized
                if session_id in connected_clients:
                    connected_clients[session_id]["initialized"] = True

            # Notifications should return 202 Accepted according to MCP spec
            return Response(status_code=202)  # Accepted

        # Handle ping requests
        elif method == "ping":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "timestamp": datetime.now().isoformat(),
                    "status": "alive"
                }
            }
            return JSONResponse(response)

        # Unknown method
        else:
            logger.warning(f"Unknown method: {method}")
            error_response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": "Method not found",
                    "data": {"method": method}
                }
            }
            return JSONResponse(error_response, status_code=404)

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            },
            status_code=400
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": {"error": str(e)}
                }
            },
            status_code=500
        )


@app.delete("/mcp")
async def mcp_endpoint_delete(request: Request):
    """MCP Streamable HTTP Endpoint - DELETE for session termination"""
    session_id = request.headers.get("mcp-session-id")

    if not session_id:
        return JSONResponse(
            {"error": "Missing Mcp-Session-Id header"},
            status_code=400
        )

    if session_id in connected_clients:
        del connected_clients[session_id]
        logger.info(f"Session terminated: {session_id}")
        return Response(status_code=200)
    else:
        return JSONResponse(
            {"error": "Invalid session ID"},
            status_code=404
        )


@app.post("/12306/login")
async def login_12306(request: Request, form: LoginForm12306):
    return await ticket_service.login_12306(request, form)


@app.post("/12306/login_verification")
async def login_verification_12306(request: Request, form: LoginVerificationCode):
    return await ticket_service.login_verification_12306(request, form)


# ========== query_transfer_validated 函数实现 ==========
async def query_transfer_validated(args: dict) -> list:
    """
    查询中转换乘方案。使用参考代码的正确实现方式。
    支持指定中转站、学生票、无座车次等选项，自动分页获取所有中转方案。
    """
    try:
        from_station = args.get("from_station", "").strip()
        to_station = args.get("to_station", "").strip()
        train_date = args.get("train_date", "").strip()
        middle_station = args.get("middle_station", "").strip() if "middle_station" in args else ""
        isShowWZ = args.get("isShowWZ", "N").strip().upper() or "N"
        purpose_codes = args.get("purpose_codes", "00").strip().upper() or "00"

        # 参数校验
        if not from_station or not to_station or not train_date:
            response_data = {"success": False, "error": "请输入出发站、到达站和出发日期"}
            return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]

        # 日期格式校验
        try:
            dt = datetime.strptime(train_date, "%Y-%m-%d")
            if dt.date() < date.today():
                response_data = {"success": False, "error": "出发日期不能早于今天"}
                return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
        except Exception:
            response_data = {"success": False, "error": "出发日期格式错误，应为YYYY-MM-DD"}
            return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]

        # 自动转三字码 - 使用参考代码的实现
        async def ensure_telecode(val):
            if val.isalpha() and val.isupper() and len(val) == 3:
                return val
            code = await cr_utils.get_station(val)
            return code

        from_code = await ensure_telecode(from_station)
        to_code = await ensure_telecode(to_station)
        if not from_code:
            response_data = {"success": False, "error": f"出发站无效或无法识别：{from_station}"}
            return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
        if not to_code:
            response_data = {"success": False, "error": f"到达站无效或无法识别：{to_station}"}
            return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]

        # 处理中转站：如果是中文名称，尝试转换为三字码
        middle_station_code = ""
        if middle_station:
            middle_station_code = await ensure_telecode(middle_station)
            if not middle_station_code:
                # 如果转换失败，记录日志但继续尝试使用原值（虽然很可能失败）
                logger.warning(f"无法识别中转站: {middle_station}")
                middle_station_code = middle_station

                # 使用中转查询专用接口
        url_init = "https://kyfw.12306.cn/otn/leftTicket/init"
        url = "https://kyfw.12306.cn/lcquery/queryG"  # 中转查询专用接口
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Host": "kyfw.12306.cn",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://kyfw.12306.cn"
        }

        all_transfer_list = []
        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(follow_redirects=False, timeout=8, verify=False) as client:
                    # 先访问init获取cookie
                    await client.get(url_init, headers=headers)

                    # 分页查询所有中转方案
                    page_size = 10
                    result_index = 0
                    page_num = 1

                    while True:
                        params = {
                            "train_date": train_date,
                            "from_station_telecode": from_code,
                            "to_station_telecode": to_code,
                            "middle_station": middle_station_code,
                            "result_index": str(result_index),
                            "can_query": "Y",
                            "isShowWZ": isShowWZ,
                            "purpose_codes": purpose_codes,
                            "channel": "E"
                        }

                        resp = await client.get(url, headers=headers, params=params)

                        # 检查反爬虫
                        if resp.status_code == 302 or "error.html" in str(resp.headers.get("location", "")):
                            if page_num == 1:
                                response_data = {"success": False,
                                                 "error": "12306反爬虫拦截（302跳转），请稍后重试或更换网络环境"}
                                return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
                            else:
                                break

                        try:
                            data = resp.json().get("data", {})
                            transfer_list = data.get("middleList", [])
                        except Exception:
                            if page_num == 1:
                                response_data = {"success": False, "error": "12306反爬拦截或数据异常，请稍后重试"}
                                return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
                            else:
                                break

                        if not transfer_list:
                            break

                        all_transfer_list.extend(transfer_list)

                        # 如果返回的数据少于页面大小，说明已经是最后一页
                        if len(transfer_list) < page_size:
                            break

                        result_index += page_size
                        page_num += 1

                    # Success
                    break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as e:
                last_exception = e
                # 清空可能已获取的部分数据，准备重试
                all_transfer_list = []
                if attempt < max_retries - 1:
                    logger.warning(f"中转查询网络请求失败，正在重试 ({attempt + 1}/{max_retries}): {str(e)}")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"中转查询网络请求重试次数已耗尽: {str(e)}")
        else:
            response_data = {"success": False, "error": f"网络请求失败 (已重试{max_retries}次): {str(last_exception)}"}
            return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]

        if not all_transfer_list:
            response_data = {
                "success": False,
                "from_station": from_station,
                "to_station": to_station,
                "train_date": train_date,
                "count": 0,
                "transfers": [],
                "message": "未查到中转方案"
            }
            return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]

        # 构建JSON格式的中转方案数据
        transfers_list = []
        for item in all_transfer_list:
            try:
                # 优先用 fullList，降级用 trainList
                full_list = item.get("fullList") or item.get("trainList") or []
                if len(full_list) < 2:
                    continue

                # 解析每段车次
                segments = []
                for seg in full_list:
                    # 座位余票信息 - 只包含有票的座位类型
                    seats = {}
                    seat_num = seg.get("swz_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["商务座"] = seat_num
                    seat_num = seg.get("tz_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["特等座"] = seat_num
                    seat_num = seg.get("zy_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["一等座"] = seat_num
                    seat_num = seg.get("ze_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["二等座"] = seat_num
                    seat_num = seg.get("gr_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["高级软卧"] = seat_num
                    seat_num = seg.get("rw_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["软卧"] = seat_num
                    seat_num = seg.get("rz_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["一等卧"] = seat_num
                    seat_num = seg.get("yw_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["硬卧"] = seat_num
                    seat_num = seg.get("yz_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["硬座"] = seat_num
                    seat_num = seg.get("wz_num", "")
                    if seat_num and seat_num != "--" and seat_num != "":
                        seats["无座"] = seat_num

                    segment_data = {
                        "train_code": seg.get("station_train_code", ""),
                        "from_station": seg.get("from_station_name", ""),
                        "to_station": seg.get("to_station_name", ""),
                        "start_time": seg.get("start_time", ""),
                        "arrive_time": seg.get("arrive_time", ""),
                        "duration": seg.get("lishi", ""),
                        "seats": seats
                    }
                    segments.append(segment_data)

                transfer_data = {
                    "middle_station": item.get("middle_station_name") or (
                        full_list[0].get("to_station_name", "") if full_list else ""),
                    "wait_time": item.get("wait_time", ""),
                    "total_duration": item.get("all_lishi", ""),
                    "segments": segments
                }
                transfers_list.append(transfer_data)

            except Exception as e:
                logger.warning(f"解析中转方案失败: {e}")
                continue

        response_data = {
            "success": True,
            "from_station": from_station,
            "to_station": to_station,
            "train_date": train_date,
            "count": len(transfers_list),
            "transfers": transfers_list
        }
        return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]

    except Exception as e:
        logger.error(f"查询中转失败: {repr(e)}")
        response_data = {"success": False, "error": "查询中转失败", "detail": str(e)}
        return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]


# ========== get_current_time_validated 新增时间工具 ==========
async def get_current_time_validated(args: dict) -> list:
    """
    返回当前时间信息JSON格式
    """
    try:
        from datetime import datetime
        import pytz
        timezone_str = args.get("timezone", "Asia/Shanghai")
        date_format = args.get("format", "YYYY-MM-DD")
        try:
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
        except pytz.exceptions.UnknownTimeZoneError:
            tz = pytz.timezone("Asia/Shanghai")
            now = datetime.now(tz)

        response_data = {
            "success": True,
            "timezone": tz.zone,
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": int(now.timestamp())
        }
        return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]
    except Exception as e:
        logger.error(f"获取时间信息失败: {repr(e)}")
        response_data = {"success": False, "error": "获取时间信息失败", "detail": str(e)}
        return [{"type": "text", "text": json.dumps(response_data, ensure_ascii=False)}]


async def main_server():
    """启动MCP服务器"""
    logger.info("启动12306 MCP服务器...")
    logger.info(f"协议版本: {MCP_PROTOCOL_VERSION}")
    logger.info(f"传输类型: Streamable HTTP")
    logger.info(f"MCP端点: http://{settings.server_host}:{settings.server_port}/mcp")
    logger.info(f"健康检查: http://{settings.server_host}:{settings.server_port}/health")

    config = uvicorn.Config(
        app,
        host=settings.server_host,
        port=settings.server_port,
        log_level=settings.log_level.lower()
    )
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()


def main():
    asyncio.run(main_server())


if __name__ == "__main__":
    main()
