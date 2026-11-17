"""Telegram opcional. Desligado por padrão e silencioso quando falta credencial."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import requests

from daytrade.common.logging_setup import log_event


class Notifier:
    def send(self, text: str) -> None:
        return


class NullNotifier(Notifier):
    pass


class TelegramNotifier(Notifier):
    def __init__(
        self,
        *,
        enabled: bool,
        env: Mapping[str, str],
        logger: logging.Logger,
        timeout: float = 5.0,
    ) -> None:
        self.logger = logger
        self.timeout = timeout
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        chat = env.get("TELEGRAM_CHAT_ID", "")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage" if token else ""
        self._chat = chat
        self.enabled = bool(enabled and token and chat)
        if enabled and not self.enabled:
            log_event(logger, logging.WARNING, "Telegram ligado sem token ou chat; notificações ignoradas")

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            response = requests.post(
                self._url,
                json={"chat_id": self._chat, "text": text[:3500]},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "Telegram recusou a mensagem",
                    status=response.status_code,
                )
        except requests.RequestException as exc:
            log_event(self.logger, logging.WARNING, "falha ao falar com o Telegram", erro=str(exc))


def build_notifier(enabled: bool, env: Mapping[str, str], logger: logging.Logger) -> Notifier:
    if not enabled:
        return NullNotifier()
    return TelegramNotifier(enabled=True, env=env, logger=logger)
