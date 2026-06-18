"""本地 Web 控制面板：Flask 后端，提供仪表盘与 REST API。

在后台线程中运行，与托盘程序同进程共享 AppService。
"""
from __future__ import annotations

import logging
import os
import threading
import webbrowser

from flask import Flask, jsonify, request, send_from_directory

from ..config import save_config
from ..paths import resource_path

log = logging.getLogger("water.web")

# 网页文件随 exe 一起打包；保持与源码相同的相对结构 src/web/static
STATIC_DIR = resource_path("src", "web", "static")

# 允许通过 Web 表单编辑的配置字段(白名单，防止写入任意键)
EDITABLE_PATHS = {
    "reminder": ["interval_minutes", "cup_ml", "active_start", "active_end", "quiet_start", "quiet_end"],
    "profile": ["weight_kg", "exercise_level", "daily_goal_ml", "health_conditions", "health_notes"],
    "ai": ["enabled", "api_key", "base_url", "model", "wire_api"],
    "weather": ["enabled", "provider", "api_key", "city", "default_temp_c"],
    "report": ["daily_time", "weekly_weekday", "weekly_time"],
    "web": ["port", "auto_open"],
}


def create_app(service) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.route("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/api/status")
    def api_status():
        return jsonify(service.status())

    @app.route("/api/drink", methods=["POST"])
    def api_drink():
        data = request.get_json(silent=True) or {}
        amount = data.get("amount")
        service.drink(int(amount) if amount else None)
        return jsonify(service.status())

    @app.route("/api/undo", methods=["POST"])
    def api_undo():
        amount = service.undo_last_drink()
        return jsonify({"undone": amount, **service.status()})

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        paused = service.toggle_pause()
        return jsonify({"paused": paused})

    @app.route("/api/goal/recompute", methods=["POST"])
    def api_recompute():
        goal = service.recompute_goal()
        return jsonify({"goal": goal})

    @app.route("/api/report/<kind>", methods=["POST"])
    def api_report(kind):
        data = request.get_json(silent=True) or {}
        force = bool(data.get("force"))  # True 时忽略缓存强制重新调用 AI
        if kind == "weekly":
            content = service.send_weekly_report(force=force)
        else:
            content = service.send_daily_report(force=force)
        return jsonify({"content": content})

    @app.route("/api/config", methods=["GET"])
    def api_get_config():
        # 返回可编辑字段(不含敏感推送密码细节，但 ai/weather key 仍返回以便编辑)
        out = {}
        for section, keys in EDITABLE_PATHS.items():
            out[section] = {k: service.cfg.get(f"{section}.{k}") for k in keys}
        return jsonify(out)

    @app.route("/api/config", methods=["POST"])
    def api_set_config():
        data = request.get_json(silent=True) or {}
        partial = _filter_editable(data)
        if not partial:
            return jsonify({"ok": False, "error": "没有可保存的字段"}), 400
        try:
            save_config(partial)
            service.reload_config()
            return jsonify({"ok": True})
        except Exception as exc:  # noqa: BLE001
            log.exception("保存配置失败")
            return jsonify({"ok": False, "error": str(exc)}), 500

    return app


def _coerce(key: str, value):
    """根据字段名做基本类型转换。"""
    int_keys = {"interval_minutes", "cup_ml", "daily_goal_ml", "weight_kg", "default_temp_c", "port"}
    bool_keys = {"enabled", "auto_open"}
    if key in bool_keys:
        return bool(value)
    if key in int_keys:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    return value


def _filter_editable(data: dict) -> dict:
    out: dict = {}
    for section, keys in EDITABLE_PATHS.items():
        if section not in data or not isinstance(data[section], dict):
            continue
        section_out = {}
        for key in keys:
            if key in data[section]:
                section_out[key] = _coerce(key, data[section][key])
        if section_out:
            out[section] = section_out
    return out


def run_in_thread(service, cfg) -> threading.Thread | None:
    """在后台守护线程中启动 Web 服务。返回线程对象(失败返回 None)。"""
    if not cfg.get("web.enabled", True):
        return None
    port = int(cfg.get("web.port", 8765))
    app = create_app(service)

    def _serve():
        try:
            # 关闭重载器与调试，避免在线程中产生信号问题
            app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False, debug=False)
        except Exception as exc:  # noqa: BLE001
            log.error("Web 面板启动失败(端口 %s): %s", port, exc)

    thread = threading.Thread(target=_serve, daemon=True, name="web-panel")
    thread.start()
    log.info("控制面板运行在 http://127.0.0.1:%s", port)

    if cfg.get("web.auto_open", False):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    return thread


def open_panel(cfg) -> None:
    port = int(cfg.get("web.port", 8765))
    webbrowser.open(f"http://127.0.0.1:{port}")
