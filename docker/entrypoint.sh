#!/bin/sh

CONFIG="${PICIX_CONFIG:-/data/config.yaml}"

# 从 config.yaml 中提取 cron_schedule，环境变量 CRON_SCHEDULE 优先
if [ -z "$CRON_SCHEDULE" ]; then
    CRON_SCHEDULE=$(python3 -c "
import yaml, sys
try:
    c = yaml.safe_load(open('$CONFIG'))
    print(c.get('cron_schedule', '5 6 * * *'))
except:
    print('5 6 * * *')
")
fi

# 如果第一参数是 cron，设置定时任务然后保持容器运行
if [ "$1" = "cron" ]; then
    KEEPER=$(which picix-keeper || echo "/usr/local/bin/picix-keeper")
    echo "Setting up cron: $CRON_SCHEDULE picix-keeper run"
    echo "$CRON_SCHEDULE root cd /app && $KEEPER run --config $CONFIG >> /data/log.txt 2>&1" > /etc/crontab
    # 设置系统时区（cron 读 /etc/localtime 不读 TZ 环境变量）
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
    echo "Asia/Shanghai" > /etc/timezone

    # cron 由镜像提供；缺失说明镜像构建有问题，直接失败而不是静默空转
    if ! command -v cron >/dev/null 2>&1; then
        echo "ERROR: cron is not installed in this image, cannot schedule runs" >&2
        exit 1
    fi

    touch /data/log.txt
    cron
    echo "Cron started. Container staying alive."
    exec sleep infinity

# 否则直接执行传入的命令（如 run, status, extract）
else
    exec picix-keeper "$@" --config "$CONFIG"
fi
