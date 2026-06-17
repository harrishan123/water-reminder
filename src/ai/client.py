"""大模型客户端封装。

支持两种 wire_api:
  - "chat"      -> POST {base_url}/chat/completions (OpenAI 兼容: DeepSeek/通义/智谱/Kimi/OpenAI)
                   通过 openai SDK 调用。
  - "responses" -> POST {base_url}/responses        (yescode 等路由网关)
                   直接用 requests 发请求，避免 SDK 默认参数与网关不兼容导致空响应。

未配置 api_key 时 is_enabled() 返回 False，调用方应走降级逻辑。
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger("water.ai")


class AIClient:
    def __init__(
        self,
        enabled: bool,
        api_key: str,
        base_url: str,
        model: str,
        wire_api: str = "chat",
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.wire_api = (wire_api or "chat").lower()
        self._sdk_client = None
        self._enabled = False

        if not enabled or not api_key:
            return

        if self.wire_api == "responses":
            # Responses 协议直接用 HTTP，不依赖 SDK
            self._enabled = True
            return

        try:
            from openai import OpenAI

            self._sdk_client = OpenAI(api_key=api_key, base_url=self.base_url or None, timeout=30.0)
            self._enabled = True
        except Exception as exc:  # noqa: BLE001 - 任何初始化失败都降级
            log.warning("AI 客户端初始化失败，将使用降级逻辑: %s", exc)

    def is_enabled(self) -> bool:
        return self._enabled

    def chat(self, system: str, user: str, temperature: float = 0.7) -> str | None:
        """发送一次对话，返回文本内容；失败返回 None。"""
        if not self.is_enabled():
            return None
        try:
            if self.wire_api == "responses":
                return self._chat_responses(system, user)
            return self._chat_completions(system, user, temperature)
        except Exception as exc:  # noqa: BLE001
            log.warning("AI 调用失败，使用降级逻辑: %s", exc)
            return None

    def _chat_completions(self, system: str, user: str, temperature: float) -> str:
        resp = self._sdk_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()

    def _chat_responses(self, system: str, user: str) -> str:
        # 仅传 yescode 已验证可工作的最小字段集合，避免 SDK 加默认参数后返回空文本
        body: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "store": True,
        }
        r = requests.post(
            f"{self.base_url}/responses",
            json=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if r.status_code != 200:
            log.warning("Responses API HTTP %s: %s", r.status_code, r.text[:300])
            return ""
        data = r.json()
        text = (data.get("output_text") or "").strip()
        if text:
            return text
        for item in data.get("output") or []:
            if item.get("type") == "message":
                for c in item.get("content") or []:
                    t = c.get("text") or c.get("output_text")
                    if t:
                        return str(t).strip()
        return ""


def build_client(cfg) -> AIClient:
    """从 Config 构造 AIClient。

    api_key 优先读环境变量 WATER_AI_API_KEY，便于把密钥放在配置文件之外。
    """
    api_key = os.environ.get("WATER_AI_API_KEY") or str(cfg.get("ai.api_key", "") or "")
    return AIClient(
        enabled=bool(cfg.get("ai.enabled", False)),
        api_key=api_key,
        base_url=str(cfg.get("ai.base_url", "") or ""),
        model=str(cfg.get("ai.model", "deepseek-chat") or "deepseek-chat"),
        wire_api=str(cfg.get("ai.wire_api", "chat") or "chat"),
    )
