# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional, Dict, Any, AsyncIterator, Callable
from .schema import Incoming, ChannelType

AsyncGenHandler = Callable[[Incoming], AsyncIterator[str]]


class BaseGateway:
    channel: ChannelType

    def __init__(self, handler: AsyncGenHandler):
        self._handler = handler

    @classmethod
    def from_env(cls, handler: AsyncGenHandler) -> "BaseGateway":
        raise NotImplementedError

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError
