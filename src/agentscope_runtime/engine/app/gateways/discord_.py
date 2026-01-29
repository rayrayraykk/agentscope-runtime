# -*- coding: utf-8 -*-
# app/gateways/discord_.py
from __future__ import annotations

import os
import logging
import asyncio
from typing import Optional

from .schema import Incoming
from .base import BaseGateway, AsyncGenHandler

logger = logging.getLogger(__name__)


class DiscordGateway(BaseGateway):
    channel = "discord"

    def __init__(
        self,
        handler: AsyncGenHandler,
        enabled: bool,
        token: str,
        http_proxy: str,
        http_proxy_auth: str,
        bot_prefix: str,
    ):
        super().__init__(handler)
        self.enabled = enabled
        self.token = token
        self.http_proxy = http_proxy
        self.http_proxy_auth = http_proxy_auth
        self.bot_prefix = bot_prefix
        self._task: Optional[asyncio.Task] = None
        self._client = None

        if self.enabled:
            import discord  # type: ignore

            intents = discord.Intents.default()
            intents.message_content = True
            intents.dm_messages = True
            intents.messages = True
            intents.guilds = True

            proxy_auth = None
            if self.http_proxy_auth:
                import aiohttp  # type: ignore

                u, p = self.http_proxy_auth.split(":", 1)
                proxy_auth = aiohttp.BasicAuth(u, p)

            self._client = discord.Client(
                intents=intents,
                proxy=self.http_proxy,
                proxy_auth=proxy_auth,
            )

            @self._client.event  # type: ignore
            async def on_message(message):
                if message.author.bot:
                    return
                text = (message.content or "").strip()
                if not text or text.startswith(self.bot_prefix):
                    return

                msg = Incoming(
                    channel="discord",
                    sender=str(message.author),
                    text=text,
                    meta={
                        "channel_id": str(message.channel.id),
                        "guild_id": str(message.guild.id)
                        if message.guild
                        else None,
                        "message_id": str(message.id),
                        "is_dm": message.guild is None,
                    },
                )

                try:
                    async for chunk in self._handler(msg):
                        if not chunk:
                            continue
                        out = self.bot_prefix + chunk
                        await message.channel.send(out)
                except Exception:
                    logger.exception("handler/send failed")

    @classmethod
    def from_env(cls, handler: AsyncGenHandler) -> "DiscordGateway":
        return cls(
            handler=handler,
            enabled=os.getenv("DISCORD_ENABLED", "1") == "1",
            token=os.getenv("DISCORD_BOT_TOKEN", ""),
            http_proxy=os.getenv(
                "DISCORD_HTTP_PROXY",
                "http://127.0.0.1:18118",
            ),
            http_proxy_auth=os.getenv("DISCORD_HTTP_PROXY_AUTH", ""),
            bot_prefix=os.getenv("DISCORD_BOT_PREFIX", "[BOT] "),
        )

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        """
        Proactive send for Discord.

        Notes:
        - Discord cannot send to a "user handle" directly without resolving
            a User/Channel.
        - This implementation supports:
            1) meta["channel_id"]  -> send to that channel
            2) meta["user_id"]     -> DM that user (opens/uses DM channel)
        - If neither is provided, this raises ValueError.
        """
        if not self.enabled:
            return
        if not self._client:
            raise RuntimeError("Discord client is not initialized")
        if not self._client.is_ready():  # type: ignore
            raise RuntimeError("Discord client is not ready yet")

        meta = meta or {}

        channel_id = meta.get("channel_id")
        user_id = meta.get("user_id")

        if channel_id:
            ch = self._client.get_channel(int(channel_id))  # type: ignore
            if ch is None:
                ch = await self._client.fetch_channel(
                    int(channel_id),
                )  # type: ignore
            await ch.send(text)  # type: ignore
            return

        if user_id:
            user = self._client.get_user(int(user_id))  # type: ignore
            if user is None:
                user = await self._client.fetch_user(
                    int(user_id),
                )  # type: ignore
            dm = user.dm_channel or await user.create_dm()  # type: ignore
            await dm.send(text)  # type: ignore
            return

        raise ValueError(
            "DiscordGateway.send requires meta['channel_id'] or meta["
            "'user_id']",
        )

    async def _run(self) -> None:
        if not self.enabled or not self.token or not self._client:
            return
        await self._client.start(self.token, reconnect=True)  # type: ignore

    async def start(self) -> None:
        if not self.enabled:
            return
        self._task = asyncio.create_task(self._run(), name="discord_gateway")

    async def stop(self) -> None:
        if not self.enabled:
            return
        if self._client:
            await self._client.close()  # type: ignore
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except Exception:
                pass
