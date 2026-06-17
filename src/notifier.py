"""统一通知出口：Windows toast 弹窗 + 邮件 + 微信(Server酱/PushPlus)推送。"""
from __future__ import annotations

import logging
import smtplib
import threading
from email.header import Header
from email.mime.text import MIMEText
from typing import Callable, Optional

log = logging.getLogger("water.notifier")


class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self._toast_available = self._check_toast()

    @staticmethod
    def _check_toast() -> bool:
        import importlib.util

        if importlib.util.find_spec("win11toast") is not None:
            return True
        log.warning("win11toast 不可用，弹窗将退化为日志")
        return False

    # ---------- 桌面弹窗 ----------
    def show_reminder(self, title: str, body: str, on_drink: Optional[Callable[[], None]] = None) -> None:
        """显示带「喝一杯」按钮的提醒。点击按钮触发 on_drink 回调。"""
        if not self._toast_available:
            log.info("[提醒] %s - %s", title, body)
            return

        def _run():
            try:
                from win11toast import toast

                buttons = ["喝一杯", "稍后"]
                result = toast(
                    title,
                    body,
                    buttons=buttons,
                    duration="short",
                )
                # win11toast 返回点击的按钮信息(dict)
                clicked = ""
                if isinstance(result, dict):
                    clicked = result.get("arguments", "") or ""
                if on_drink and "喝一杯" in str(clicked):
                    on_drink()
            except Exception as exc:  # noqa: BLE001
                log.warning("弹窗失败: %s", exc)

        threading.Thread(target=_run, daemon=True).start()

    def show_message(self, title: str, body: str) -> None:
        """显示一条普通通知(无按钮)。"""
        if not self._toast_available:
            log.info("[通知] %s - %s", title, body)
            return

        def _run():
            try:
                from win11toast import toast

                toast(title, body, duration="short")
            except Exception as exc:  # noqa: BLE001
                log.warning("通知失败: %s", exc)

        threading.Thread(target=_run, daemon=True).start()

    # ---------- 报告推送(多渠道) ----------
    def push_report(self, title: str, content: str) -> None:
        """把报告推送到所有已启用的渠道，并弹窗显示摘要。"""
        self.show_message(title, content[:200])
        # 各渠道独立 try，互不影响
        if self.cfg.get("push.email.enabled", False):
            self._safe(self._push_email, title, content)
        if self.cfg.get("push.serverchan.enabled", False):
            self._safe(self._push_serverchan, title, content)
        if self.cfg.get("push.pushplus.enabled", False):
            self._safe(self._push_pushplus, title, content)

    def _safe(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s 推送失败: %s", fn.__name__, exc)

    def _push_email(self, title: str, content: str) -> None:
        host = self.cfg.get("push.email.smtp_host")
        port = int(self.cfg.get("push.email.smtp_port", 465))
        use_ssl = bool(self.cfg.get("push.email.use_ssl", True))
        username = self.cfg.get("push.email.username")
        password = self.cfg.get("push.email.password")
        to_addr = self.cfg.get("push.email.to")
        if not all([host, username, password, to_addr]):
            log.warning("邮件配置不完整，跳过")
            return

        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = Header(title, "utf-8")
        msg["From"] = username
        msg["To"] = to_addr

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        try:
            server.login(username, password)
            server.sendmail(username, [to_addr], msg.as_string())
            log.info("邮件已发送至 %s", to_addr)
        finally:
            server.quit()

    def _push_serverchan(self, title: str, content: str) -> None:
        import requests

        sendkey = self.cfg.get("push.serverchan.sendkey")
        if not sendkey:
            return
        url = f"https://sctapi.ftqq.com/{sendkey}.send"
        resp = requests.post(url, data={"title": title, "desp": content}, timeout=20)
        resp.raise_for_status()
        log.info("Server酱推送完成")

    def _push_pushplus(self, title: str, content: str) -> None:
        import requests

        token = self.cfg.get("push.pushplus.token")
        if not token:
            return
        url = "https://www.pushplus.plus/send"
        payload = {"token": token, "title": title, "content": content, "template": "txt"}
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        log.info("PushPlus 推送完成")
