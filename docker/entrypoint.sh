#!/bin/sh
set -e

# 配置文件路径
CONFIG="${PICIX_CONFIG:-/data/config.yaml}"

# 如果第一参数是 cron，设置定时任务然后保持容器运行
if [ "$1" = "cron" ]; then
    SCHEDULE="${CRON_SCHEDULE:-5 9 * * *}"
    echo "Setting up cron: $SCHEDULE picix-keeper run"
    echo "$SCHEDULE cd /app && picix-keeper run --config $CONFIG >> /data/log.txt 2>&1" > /etc/crontab
    # 安装 cron 并启动
    apt-get update -qq && apt-get install -y -qq cron > /dev/null 2>&1
    cron
    echo "Cron started. Container staying alive."
    tail -f /data/log.txt 2>/dev/null || sleep infinity

# 否则直接执行传入的命令（如 run, status, extract）
else
    exec picix-keeper "$@" --config "$CONFIG"
fi
