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
COPY docs ./docs
COPY scripts ./scripts
COPY src ./src
COPY README.md ./

# 安装项目本身
RUN uv sync
RUN uv run playwright install --with-deps


# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uv", "run", "python", "-m", "mcp_12306.server"]