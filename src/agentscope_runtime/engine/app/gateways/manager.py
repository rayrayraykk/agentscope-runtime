# -*- coding: utf-8 -*-

from __future__ import annotations

import logging

from typing import List

from .base import BaseGateway, AsyncGenHandler
from .imessage import IMessageGateway
from .discord_ import DiscordGateway
from .dingtalk import DingTalkGateway

logger = logging.getLogger(__name__)


class GatewayManager:
    def __init__(self, gateways: List[BaseGateway]):
        self.gateways = gateways

    @classmethod
    def from_env(cls, handler: AsyncGenHandler) -> "GatewayManager":
        gateways: list[BaseGateway] = [
            IMessageGateway.from_env(handler),
            DiscordGateway.from_env(handler),
            DingTalkGateway.from_env(handler),
        ]
        return cls(gateways)

    async def start_all(self) -> None:
        logger.info("starting gateways=%s", [g.channel for g in self.gateways])
        for g in self.gateways:
            try:
                await g.start()
            except Exception:
                logger.exception("failed to start gateway=%s", g.channel)

    async def stop_all(self) -> None:
        logger.info("stopping gateways=%s", [g.channel for g in self.gateways])
        for g in reversed(self.gateways):
            try:
                await g.stop()
            except Exception:
                logger.exception("failed to stop gateway=%s", g.channel)
