"""配置加载：读取 config.yaml，提供默认值与点路径访问。"""
from __future__ import annotations

import copy
import os
from datetime import time
from typing import Any

import yaml

from .paths import data_path

# 可写数据目录：源码运行时为项目根，打包后为 exe 同级目录
ROOT_DIR = data_path()
CONFIG_PATH = data_path("config.yaml")
DATA_DIR = data_path("data")

DEFAULTS: dict[str, Any] = {
    "reminder": {
        "interval_minutes": 60,
        "cup_ml": 250,
        "active_start": "09:00",
        "active_end": "22:00",
        "quiet_start": "",
        "quiet_end": "",
        "quick_amounts": [100, 150, 200, 250],
    },
    "profile": {
        "weight_kg": 65,
        "exercise_level": "light",
        "daily_goal_ml": 0,
    },
    "ai": {
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "wire_api": "chat",   # "chat" | "responses"，yescode 用 responses
    },
    "weather": {
        "enabled": False,
        "provider": "wttr",
        "api_key": "",
        "city": "Beijing",
        "default_temp_c": 22,
    },
    "web": {
        "enabled": True,
        "port": 8765,
        "auto_open": False,
    },
    "report": {
        "daily_time": "21:30",
        "weekly_weekday": "sun",
        "weekly_time": "20:00",
    },
    "push": {
        "email": {
            "enabled": False,
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
            "use_ssl": True,
            "username": "",
            "password": "",
            "to": "",
        },
        "serverchan": {"enabled": False, "sendkey": ""},
        "pushplus": {"enabled": False, "token": ""},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """用 override 覆盖 base，递归合并字典，返回新字典。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """配置容器，支持 cfg.get('reminder.interval_minutes', 60) 形式访问。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def parse_time(self, path: str, default: str = "") -> time | None:
        """把 "HH:MM" 字符串解析为 datetime.time；空字符串返回 None。"""
        value = self.get(path, default)
        if not value:
            return None
        try:
            hour, minute = str(value).split(":")
            return time(int(hour), int(minute))
        except (ValueError, AttributeError):
            return None

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def update(self, partial: dict[str, Any]) -> None:
        """用 partial(可嵌套)就地更新当前配置数据。"""
        self._data = _deep_merge(self._data, partial)

    def replace(self, data: dict[str, Any]) -> None:
        self._data = data


def load_config(path: str | None = None) -> Config:
    """加载配置文件并与默认值合并。

    文件不存在时(如打包后的 exe 首次运行)会在该位置写出一份默认配置，
    方便用户直接编辑(默认 AI 关闭、不含任何密钥)。
    """
    path = path or CONFIG_PATH
    user_data: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            user_data = yaml.safe_load(fh) or {}
    else:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(DEFAULTS, fh, allow_unicode=True, sort_keys=False)
        except OSError:
            pass  # 只读目录等情况下静默使用内存默认值
    merged = _deep_merge(DEFAULTS, user_data)
    os.makedirs(DATA_DIR, exist_ok=True)
    return Config(merged)


def save_config(partial: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    """把 partial 合并进磁盘配置并写回，返回写回后的完整数据。

    注意：写回会使用 yaml 序列化，原文件中的注释会丢失。
    """
    path = path or CONFIG_PATH
    current: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            current = yaml.safe_load(fh) or {}
    merged = _deep_merge(_deep_merge(DEFAULTS, current), partial)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(merged, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return merged
