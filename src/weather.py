"""天气获取(可选)。未启用或失败时返回配置的默认气温。"""
from __future__ import annotations

import logging

log = logging.getLogger("water.weather")


def get_temperature(cfg) -> float:
    """返回当前气温(摄氏度)。未启用天气或获取失败时返回 default_temp_c。"""
    default = float(cfg.get("weather.default_temp_c", 22))
    if not cfg.get("weather.enabled", False):
        return default

    provider = str(cfg.get("weather.provider", "wttr")).lower()
    try:
        if provider == "wttr":
            return _wttr(cfg, default)
        if provider == "openweather":
            return _openweather(cfg, default)
        if provider == "qweather":
            return _qweather(cfg, default)
    except Exception as exc:  # noqa: BLE001
        log.warning("天气获取失败，使用默认气温 %s°C: %s", default, exc)
    return default


def _wttr(cfg, default: float) -> float:
    """wttr.in：完全免费，无需注册和 API Key。"""
    import requests
    from urllib.parse import quote

    city = cfg.get("weather.city", "Beijing")
    url = f"https://wttr.in/{quote(str(city))}?format=j1"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "curl/8"})
    resp.raise_for_status()
    data = resp.json()
    return float(data["current_condition"][0]["temp_C"])


def _qweather(cfg, default: float) -> float:
    """和风天气：需注册免费 key。city 需填 LocationID 或经纬度(如 116.41,39.92)。"""
    import requests

    api_key = cfg.get("weather.api_key")
    location = cfg.get("weather.city", "")
    if not api_key or not location:
        return default
    url = "https://devapi.qweather.com/v7/weather/now"
    params = {"location": location, "key": api_key}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return float(data["now"]["temp"])


def _openweather(cfg, default: float) -> float:
    import requests

    api_key = cfg.get("weather.api_key")
    city = cfg.get("weather.city", "Beijing")
    if not api_key:
        return default
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": "metric"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return float(data["main"]["temp"])
