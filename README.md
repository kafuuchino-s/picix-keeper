# picix-keeper

`picix-keeper` 是一个配置驱动的浏览器任务运行器。它记录本地任务状态，按配置读取任务进度，执行一次资源解锁流程，并在月末提示是否需要补足月度 50 次解锁任务。

项目使用 Playwright 启动浏览器，支持配置自定义 Chromium 可执行文件路径。它只做普通浏览器启动、手动登录态保存、状态读取和资源点击流程，不内置验证码绕过、风控绕过、反检测策略、批量注册或多账号操作。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

也可以使用脚本安装 Playwright 浏览器：

```bash
scripts/install_playwright.sh
```

Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m playwright install chromium
```

## 初始化

```bash
picix-keeper init
```

这会创建：

- `config.yaml`
- `state.json`

首次运行后，请编辑 `config.yaml`：

- 将 `base_url` 改成实际站点地址
- 如需使用自定义 Chromium 浏览器，将 `browser.executable_path` 改为浏览器可执行文件路径
- 将 `selectors` 里的占位选择器替换为你确认过的页面选择器
- 将 `resource_urls.playlist` 和 `resource_urls.normal` 改成你希望解锁的资源 URL
- 初期建议保留 `dry_run: true`

自定义浏览器示例：

```yaml
browser:
  executable_path: "C:/path/to/chrome-or-chromium.exe"
```

## 登录

```bash
picix-keeper login
```

命令会打开一个可见浏览器。请手动完成登录，回到终端按 Enter 后，工具会保存 Playwright `storage_state`，后续命令会复用该登录态。

## 查看状态

```bash
picix-keeper status
```

该命令会打开任务中心，根据 `config.yaml` 中配置的选择器读取任务状态。项目不会猜测真实 DOM，选择器必须由你在配置文件中提供。

## 每日运行

```bash
picix-keeper run
```

流程概要：

1. 如果本地状态显示今天已经完成，则直接退出。
2. 打开任务中心读取任务状态。
3. 如果每日任务已完成，则保存状态后退出。
4. 如果片单进度小于 20，优先选择片单资源。
5. 否则选择普通资源。
6. `dry_run: true` 时只打印将要解锁的资源，不点击。
7. `dry_run: false` 时才进入资源页并点击配置的解锁按钮。
8. 解锁后重新读取任务状态并保存。

## dry-run

`config.yaml` 默认启用：

```yaml
dry_run: true
```

此模式只验证配置、登录态、状态读取和资源选择逻辑，不会点击解锁按钮。确认流程符合预期后，再改为：

```yaml
dry_run: false
```

## 人工校验和无障碍

如果站点出现验证码或其他人工校验，本项目不会绕过它。你可以在 `config.yaml` 配置一个人工校验元素选择器，让运行流程自动停下来，保留浏览器窗口，并在终端提示你处理完后继续：

```yaml
accessibility:
  pause_on_challenge: true
  challenge_check_timeout_ms: 1500

selectors:
  challenge: "TODO_SELECTOR_CHALLENGE_OR_CAPTCHA_CONTAINER"
```

处理完成后回到终端按 Enter，流程会继续读取状态或执行后续步骤。若用于无人值守定时任务，请谨慎配置；无人值守环境遇到人工校验时不适合继续自动执行。

## 月末提示

```bash
picix-keeper finalize
```

该命令只基于本地 `state.json` 计算提示，不会自动批量解锁。提示格式：

```text
当前月解锁进度 x/50，还差 n 个，需要 n*20 积分，完成后可领取 640 积分
```

## Docker

本地构建与运行（配置与状态挂载到 `./data`）：

```bash
docker compose build
docker compose up -d
```

容器默认以 `cron` 模式按 `config.yaml` 中的 `cron_schedule` 定时执行 `picix-keeper run`。

### GitHub Actions → GHCR

推送到 `master` 或推送 `v*` 标签时，[`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml) 会自动构建并推送到 GitHub Container Registry：

```text
ghcr.io/kafuuchino-s/picix-keeper:latest   # master 分支
ghcr.io/kafuuchino-s/picix-keeper:master
ghcr.io/kafuuchino-s/picix-keeper:<git-sha>
ghcr.io/kafuuchino-s/picix-keeper:v1.0.0    # 打 tag 时
```

拉取并运行示例（将 `./data` 换成你的配置目录）：

```bash
docker pull ghcr.io/kafuuchino-s/picix-keeper:latest
docker run -d --name picix-keeper --restart unless-stopped \
  -v "$(pwd)/data:/data" -e TZ=Asia/Shanghai \
  ghcr.io/kafuuchino-s/picix-keeper:latest cron
```

首次使用 GHCR 若包为私有，需在 GitHub → Packages 中将镜像设为 Public，或使用 `docker login ghcr.io`（Personal Access Token 需 `read:packages`）。

## crontab 示例

建议每天运行一次，例如每天 09:15：

```cron
15 9 * * * cd /path/to/picix-keeper && /path/to/picix-keeper/.venv/bin/picix-keeper run >> logs/picix-keeper.log 2>&1
```

请确保 `logs/` 目录已存在：

```bash
mkdir -p logs
```
