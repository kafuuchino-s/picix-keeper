"""Typer CLI for picix-keeper."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
from loguru import logger
from pydantic import ValidationError

from .config import (
    ConfigNotFoundError,
    dump_default_config,
    load_config,
    model_to_plain_dict,
)
from .constants import DEFAULT_CONFIG_EXAMPLE_PATH, DEFAULT_CONFIG_PATH
from .http_client import AuthenticationExpiredError
from .models import AppState, TaskStatus
from .notifier import notify_error, notify_status
from .scheduler import is_within_daily_window, monthly_finalize_hint
from .state import load_state, save_state
from .tasks import (
    daily_keep_alive_http,
    get_task_status_via_http,
)

app = typer.Typer(no_args_is_help=True, help="Config-driven browser task keeper.")


def _configure_logging(verbose: bool = False) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        format="{time:HH:mm:ss} | {level:<7} | {message}",
    )


def _load_config_or_exit(config_path: Path):
    try:
        return load_config(config_path)
    except ConfigNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except ValidationError as exc:
        raise typer.BadParameter(f"Invalid config: {exc}") from exc


def _echo_status(status: TaskStatus) -> None:
    typer.echo(f"daily_done: {status.daily_done}")
    typer.echo(f"monthly_unlock_progress: {status.monthly_unlock_progress}")
    typer.echo(f"playlist_unlock_progress: {status.playlist_unlock_progress}")
    typer.echo(f"points: {status.points}")
    typer.echo(f"package_remaining: {status.package_remaining}")
    typer.echo(monthly_finalize_hint(status))


@app.command("init")
def init_project(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config/state files."),
) -> None:
    """Create config.yaml and state.json."""

    config_path = DEFAULT_CONFIG_PATH
    state_path = Path("state.json")

    if config_path.exists() and not force:
        typer.echo(f"{config_path} already exists; use --force to overwrite.")
    else:
        example_path = DEFAULT_CONFIG_EXAMPLE_PATH
        if example_path.exists():
            shutil.copyfile(example_path, config_path)
        else:
            dump_default_config(config_path)
        typer.echo(f"Created {config_path}")

    if state_path.exists() and not force:
        typer.echo(f"{state_path} already exists; use --force to overwrite.")
    else:
        save_state(AppState(), state_path)
        typer.echo(f"Created {state_path}")


@app.command("status")
def status(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logs."),
) -> None:
    """Read and display the task-center status via curl_cffi (no browser)."""

    _configure_logging(verbose)
    config = _load_config_or_exit(config_path)
    try:
        task_status = get_task_status_via_http(config)
    except AuthenticationExpiredError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    _echo_status(task_status)


@app.command("run")
def run(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logs."),
) -> None:
    """Run the daily low-frequency keep-alive flow via curl_cffi (no browser)."""

    _configure_logging(verbose)
    config = _load_config_or_exit(config_path)
    state_path = config.resolve_path(config.state_file)
    state = load_state(state_path)

    if not is_within_daily_window(config):
        logger.warning(
            "Current time is outside daily_run_window; continuing because the window is advisory."
        )

    try:
        updated_state = daily_keep_alive_http(config, state)
    except AuthenticationExpiredError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        notify_error(config, str(exc))
        raise typer.Exit(1)

    save_state(updated_state, state_path)
    typer.echo("State saved.")
    typer.echo(model_to_plain_dict(updated_state))

    # 发送 Telegram 通知
    from .tasks import get_task_status_via_http
    try:
        final_status = get_task_status_via_http(config)
        notify_status(config, final_status)
    except Exception:
        pass


@app.command("extract")
def extract(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Extract cookie + localStorage from your real browser to generate storage_state.json."""

    import json

    config = _load_config_or_exit(config_path)
    typer.echo("=== 手动提取浏览器 session ===")
    typer.echo("1. 打开你的浏览器，访问 https://picix.us 并正常登录（过 Cloudflare）。")
    typer.echo("2. 登录成功后，按 F12 打开开发者工具，切换到 Console 标签。")
    typer.echo("3. 复制并执行以下整段代码：")
    typer.echo("")
    typer.echo("""(function(){
    const cookies = document.cookie.split(';').map(c => {
        const [name, ...rest] = c.trim().split('=');
        return {name: name.trim(), value: rest.join('='), domain: location.hostname, path: '/', secure: location.protocol === 'https:', httpOnly: false, sameSite: 'Lax'};
    }).filter(c => c.name);
    const ls = [];
    for(let i=0; i<localStorage.length; i++){
        const k = localStorage.key(i);
        ls.push({name: k, value: localStorage.getItem(k)});
    }
    const payload = JSON.stringify({origin: location.origin, cookies, localStorage: ls});
    navigator.clipboard.writeText(payload).then(()=>console.log('已复制到剪贴板')).catch(()=>console.log(payload));
})();""")
    typer.echo("")
    typer.echo("4. 把 Console 里输出的 JSON 字符串复制下来，粘贴到下面（直接回车结束）：")
    raw = typer.prompt("粘贴 JSON", default="")
    raw = raw.strip()
    if not raw:
        typer.secho("未收到输入，已取消。", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.secho(f"JSON 解析失败: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)

    storage_state = {
        "cookies": data.get("cookies", []),
        "origins": [
            {
                "origin": data.get("origin", "https://picix.us"),
                "localStorage": data.get("localStorage", []),
            }
        ],
    }

    storage_state_path = config.resolve_path(config.storage_state_path)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    storage_state_path.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"已保存 storage_state 到 {storage_state_path}")
    typer.echo("现在可以运行 picix-keeper status / run 了，全程使用 curl_cffi。")


@app.command("finalize")
def finalize(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
) -> None:
    """Print the month-end 50-unlock hint without unlocking anything."""

    config = _load_config_or_exit(config_path)
    state = load_state(config.resolve_path(config.state_file))
    status = TaskStatus(
        daily_done=state.daily_done,
        monthly_unlock_progress=state.monthly_unlock_progress,
        playlist_unlock_progress=state.playlist_unlock_progress,
        points=state.points,
        package_remaining=state.package_remaining,
    )
    typer.echo(monthly_finalize_hint(status))


if __name__ == "__main__":
    app()
