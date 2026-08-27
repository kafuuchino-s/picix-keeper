# picix-keeper

`picix-keeper` 用站点 JSON API 做低频每日保活：领取解锁任务、从收藏片单挑一部未解锁影片、调用解锁接口，并在本地记下进度。每月目标是 50 次解锁（片单任务 20 次）。

请求走 `requests`，每次认证调用都用本地 ECDSA P-256 密钥签发 `X-Picix-Proof-*`。不要把浏览器里的 token 拿到容器外重放，站点会撤销会话。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .
```

需要 Python 3.11+。日常用法是 Docker，不必在宿主机装包。

## 初始化

```bash
picix-keeper init
```

在当前目录创建 `config.yaml` 和 `state.json`。Docker 则把这两份以及 `storage_state.json`、`proof_key.pem` 放在 `./data/`。再编辑配置：

- `base_url`
- `http_client.user_agent`（若使用 `cf_clearance`，必须和签发该 cookie 的浏览器一致）
- `resource_urls.favorite_list_ids`：按顺序解锁的收藏片单 ID；留空则使用账号里全部收藏片单
- `auto_buy`：资源包用尽时是否用积分购买
- `cron_schedule`：仅 Docker `cron` 模式生效
- `telegram`：`run` 结束后推送结果
- 初期可保留 `dry_run: true`

## 登录

```bash
picix-keeper login
```

会申请 8 位登录码。用 Telegram 打开 `@vStreamingBot` 发送 `/login <code>`（或打开打印出的 t.me 链接）。确认后写入 `proof_key.pem`（与 `storage_state.json` 同目录），并把 `token`、`auth-session-id` 写进 `storage_state.json`。

Docker：

```bash
docker exec -it picix-keeper picix-keeper login
```

Cloudflare 若拦截 API，再用 `picix-keeper extract` 从真实浏览器更新 `cf_clearance`。`extract` 不能代替 `login`。

## 命令

```bash
picix-keeper init       # 创建 config.yaml 和 state.json
picix-keeper login      # Telegram 登录并绑定签名密钥
picix-keeper extract    # 仅更新 cf_clearance 等 cookie
picix-keeper status     # 读任务中心、积分、资源包
picix-keeper run        # 领取任务 → 选片 → 解锁
picix-keeper finalize   # 只根据本地 state.json 打印月末 50 次缺口
```

`login` / `status` / `run` 接受 `-c/--config` 和 `-v/--verbose`。`extract` 和 `finalize` 只有 `-c/--config`。

`run` 流程：

1. 若 `last_run_success_date` 已是今天，直接退出。
2. 领取尚未领取的月度任务（`M_UL_50`、`M_UL_ML_20`）和每日任务（`D_UL_1`）。
3. 资源包为 0 且开启 `auto_buy` 时购买资源包。
4. 按 `favorite_list_ids` 顺序取第一部 `isUnlock: false` 的影片；片单都空时回退到配置里的 `playlist` / `normal` URL。
5. `dry_run: true` 时仍会领取任务、必要时买资源包，只是不调用解锁接口。
6. 进度达标后站点自动发奖，不再调用 `/api/Tasks/finish`。
7. 写回 `state.json`；成功或失败时若配置了 Telegram 都会推送（像是网络断开的失败除外）。

## Docker

在仓库根目录操作。镜像是 `ghcr.io/kafuuchino-s/picix-keeper:latest`，配置和状态挂在 `./data` → `/data`。容器以 `cron` 模式常驻，按 `cron_schedule`（默认每天 06:05，Asia/Shanghai）跑 `picix-keeper run`。不要在容器里执行 `picix-keeper init`，它会写到 `/app` 而不是 `/data`。

### 首次部署

```bash
mkdir -p data
cp config.example.yaml data/config.yaml   # Windows: copy config.example.yaml data\config.yaml
```

编辑 `data/config.yaml`：

- `dry_run: false`（确认流程前可先保持 `true`）
- `resource_urls.favorite_list_ids`
- `telegram.bot_token` / `telegram.chat_id`（可选）
- `http_client.user_agent` 若稍后要配 `cf_clearance`，必须和签发 cookie 的浏览器一致

相对路径（`storage_state.json`、`state.json`）会解析到 `data/` 下。`state.json` 和 `proof_key.pem` 会在首次 `run` / `login` 时自动生成。

若 GHCR 包是私有的：

```bash
echo YOUR_GHCR_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
```

启动：

```bash
docker compose pull
docker compose up -d
docker exec -it picix-keeper picix-keeper login
docker exec picix-keeper picix-keeper status
```

`login` 会打印 8 位码和 t.me 链接；用 Telegram `@vStreamingBot` 确认后才会写入 `/data/proof_key.pem`。然后可手动跑一次：

```bash
docker exec picix-keeper picix-keeper run
```

### 日常运维

```bash
docker exec picix-keeper picix-keeper status
docker exec -it picix-keeper picix-keeper login    # 登录失效或密钥丢失
cat data/log.txt                                   # cron 输出；docker logs 只看得到 cron 启动信息
```

API 返回 Cloudflare 403 时，在真实浏览器过验证后执行 `docker exec -it picix-keeper picix-keeper extract`，只更新 `cf_clearance`，不要重放浏览器 token。

重建容器不会清掉 `./data`：

```bash
docker compose pull
docker compose up -d --force-recreate
```

### 本地构建

```bash
docker build -t ghcr.io/kafuuchino-s/picix-keeper:latest .
docker compose up -d --force-recreate
```

推送到 `master` 或 `v*` 标签时，GitHub Actions 会构建并推送：

```text
ghcr.io/kafuuchino-s/picix-keeper:latest    # 默认分支
ghcr.io/kafuuchino-s/picix-keeper:master
ghcr.io/kafuuchino-s/picix-keeper:<git-sha>
ghcr.io/kafuuchino-s/picix-keeper:v1.0.0    # 打 tag 时
```
