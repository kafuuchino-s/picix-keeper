"""YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .constants import DEFAULT_CONFIG_PATH


DEFAULT_CONFIG_TEMPLATE = """\
base_url: "https://picix.us/"
dry_run: true
storage_state_path: "storage_state.json"
state_file: "state.json"

# cf_clearance cookie 是在真实浏览器指纹下签发的，
# user_agent 必须与签发 cookie 的浏览器版本一致
http_client:
  user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

# 资源包不够时自动购买（用积分）
auto_buy:
  enabled: true
  # goodId: 1=轻量包(30次/450分), 2=标准包(90次/1000分), 3=增强包(200次/1600分)
  good_id: 1

# 按填写的顺序依次解锁片单中的电影
# 留空则自动获取所有收藏片单（顺序由 API 返回决定）
resource_urls:
  favorite_list_ids:
    - 1
  playlist: []
  normal: []

# Docker cron 模式下的定时表达式（分钟 小时 日 月 星期）
# 仅在 docker command: cron 时生效
cron_schedule: "5 6 * * *"

# Telegram 通知（填写后 run 完成会自动推送结果）
telegram:
  bot_token: ""
  chat_id: ""
"""


class ConfigNotFoundError(FileNotFoundError):
    """Raised when config.yaml is missing."""


class ResourceUrlConfig(BaseModel):
    """Configured resource pools."""

    playlist: list[str] = Field(default_factory=list)
    normal: list[str] = Field(default_factory=list)
    favorite_list_ids: list[int] = Field(default_factory=list)


class HttpClientConfig(BaseModel):
    """HTTP client configuration."""

    model_config = ConfigDict(extra="forbid")

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )


class AutoBuyConfig(BaseModel):
    """Auto-purchase resource packs when quota runs out."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    good_id: int = 1


class TelegramConfig(BaseModel):
    """Telegram Bot notification settings."""

    model_config = ConfigDict(extra="forbid")

    bot_token: str = ""
    chat_id: str = ""


class AppConfig(BaseModel):
    """Top-level application config."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    dry_run: bool = True
    storage_state_path: Path = Path("storage_state.json")
    state_file: Path = Path("state.json")
    http_client: HttpClientConfig = Field(default_factory=HttpClientConfig)
    auto_buy: AutoBuyConfig = Field(default_factory=AutoBuyConfig)
    resource_urls: ResourceUrlConfig = Field(default_factory=ResourceUrlConfig)
    cron_schedule: str = "5 9 * * *"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    _config_dir: Path = PrivateAttr(default=Path("."))

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve config-relative paths."""

        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        return (self._config_dir / path_obj).resolve()


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config.yaml, raising a user-friendly error if it is absent."""

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigNotFoundError(
            f"{config_path} does not exist. Run `picix-keeper init` or copy "
            "config.example.yaml to config.yaml first."
        )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} must contain a YAML mapping.")

    config = AppConfig.model_validate(raw)
    config._config_dir = config_path.resolve().parent
    return config


def dump_default_config(path: str | Path) -> None:
    """Write the default example config template."""

    Path(path).write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")


def model_to_plain_dict(model: BaseModel) -> dict[str, Any]:
    """Small helper for CLI output and tests."""

    return model.model_dump(mode="json")
