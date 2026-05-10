# 使用官方 Python 3.12 镜像（与 pyproject.toml 一致）
FROM  pcr-sh.paic.com.cn/gbd-gface-stg/python:3.12.9-bullseye

# 设置工作目录
WORKDIR /app

RUN pip3 install uv \
    --index-url http://maven.paic.com.cn:8445/repository/pypi/simple/ \
    --trusted-host maven.paic.com.cn

# 将 uv 添加到 PATH
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/app/src"

# 复制项目文件
COPY src /app/src
COPY pyproject.toml .
COPY README.md .
COPY data /app/data
COPY scripts /app/scripts
RUN chmod +x /app/scripts/start.sh

RUN uv sync --index-url http://maven.paic.com.cn/repository/pypi/simple/ && rm -rf /root/.cache/uv

# 暴露端口
EXPOSE 8080 8265 10001 6379

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV USE_GPU=true
ENV HF_HUB_OFFLINE=1

# 启动命令
ENTRYPOINT ["/app/scripts/start.sh"]
