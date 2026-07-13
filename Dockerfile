# 基础镜像
FROM python:3.12-bullseye AS mcp_12306_base

# 设置工作目录
WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY pyproject.toml uv.lock ./

RUN pip install --upgrade pip && \
    pip install uv && \
    uv sync --no-install-project

# 设置时区（可选）
ENV TZ=Asia/Shanghai

FROM mcp_12306_base

# 复制项目代码
COPY next_train_mcp ./next_train_mcp

# 安装项目本身
RUN uv sync

# 安装 Playwright 浏览器及其系统依赖
RUN uv run playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/*

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uv", "run", "uvicorn", "next_train_mcp.fastapi_server:combined_app", "--host", "0.0.0.0", "--port", "8000"]
