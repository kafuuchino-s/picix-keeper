FROM python:3.12-slim

RUN apt-get update -qq && apt-get install -y -qq tzdata && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai

WORKDIR /app

COPY pyproject.toml ./
COPY picix_keeper/ ./picix_keeper/

RUN pip install --no-cache-dir -e .

# 配置和状态文件通过 volume 挂载
VOLUME /data

ENV PICIX_CONFIG=/data/config.yaml

# 内置 cron + entrypoint 脚本
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["run"]
