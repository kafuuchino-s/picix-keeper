"""Project constants."""

import os
from pathlib import Path

PROJECT_NAME = "picix-keeper"

# 支持 PICIX_CONFIG 环境变量覆盖默认路径
_env_config = os.environ.get("PICIX_CONFIG")
DEFAULT_CONFIG_PATH = Path(_env_config) if _env_config else Path("config.yaml")
DEFAULT_CONFIG_EXAMPLE_PATH = Path("config.example.yaml")
DEFAULT_STATE_FILE = Path("state.json")
DEFAULT_STORAGE_STATE_PATH = Path("storage_state.json")

PLAYLIST_UNLOCK_TARGET = 20
MONTHLY_UNLOCK_TARGET = 50
UNLOCK_COST_POINTS = 20
MONTHLY_REWARD_POINTS = 640
