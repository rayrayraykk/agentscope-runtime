# -*- coding: utf-8 -*-
"""DingTalk Gateway."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Dict, List, Optional

import dingtalk_stream
from dingtalk_stream import CallbackMessage, ChatbotMessage

from .schema import Incoming
from .base import BaseGateway, OutgoingContentPart, ProcessHandler

logger = logging.getLogger(__name__)


class _DingTalkGatewayHandler(dingtalk_stream.ChatbotHandler):
    """Internal handler: convert DingTalk message to Incoming, enqueue it,
    await reply_future, then reply."""

    def __init__(
        self,
        main_loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[Incoming],
        bot_prefix: str,
    ):
        super().__init__()
        self._main_loop = main_loop
        self._queue = queue
        self._bot_prefix = bot_prefix

    def _emit_incoming_threadsafe(self, msg: Incoming) -> None:
        self._main_loop.call_soon_threadsafe(self._queue.put_nowait, msg)

    async def process(self, callback: CallbackMessage) -> tuple[int, str]:
        try:
            incoming_message = ChatbotMessage.from_dict(callback.data)

            text = (incoming_message.text.content or "").strip()
            # Ignore empty messages and messages that already start with bot
            # prefix.
            if not text or text.startswith(self._bot_prefix):
                return dingtalk_stream.AckMessage.STATUS_OK, "ok"

            sender = (
                getattr(incoming_message, "sender_id", None)
                or getattr(incoming_message, "senderId", None)
                or ""
            ).strip()
            if not sender:
                return dingtalk_stream.AckMessage.STATUS_OK, "ok"

            loop = asyncio.get_running_loop()
            reply_future: asyncio.Future[str] = loop.create_future()

            msg = Incoming(
                channel="dingtalk",
                sender=sender,
                text=text,
                meta={
                    "incoming_message": incoming_message,
                    "reply_future": reply_future,
                    "reply_loop": loop,
                },
            )
            logger.info("recv from=%s text=%r", sender, text[:100])
            self._emit_incoming_threadsafe(msg)

            response_text = await reply_future
            out = self._bot_prefix + response_text
            self.reply_text(out, incoming_message)
            logger.info("sent to=%s text=%r", sender, out[:100])
            return dingtalk_stream.AckMessage.STATUS_OK, "ok"

        except Exception:
            logger.exception("process failed")
            return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, "error"


class DingTalkGateway(BaseGateway):
    """DingTalk Gateway: DingTalk Stream -> Incoming -> to_agent_request ->
    process -> send_response -> DingTalk reply.
    """

    channel = "dingtalk"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        client_id: str,
        client_secret: str,
        bot_prefix: str,
    ):
        super().__init__(process)
        self.enabled = enabled
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_prefix = bot_prefix

        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[Incoming]] = None
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @classmethod
    def from_env(cls, process: ProcessHandler) -> "DingTalkGateway":
        return cls(
            process=process,
            enabled=os.getenv("DINGTALK_GATEWAY_ENABLED", "1") == "1",
            client_id=os.getenv("DINGTALK_CLIENT_ID", ""),
            client_secret=os.getenv("DINGTALK_CLIENT_SECRET", ""),
            bot_prefix=os.getenv("DINGTALK_BOT_PREFIX", "[BOT] "),
        )

    def _reply_sync(self, meta: Dict[str, Any], text: str) -> None:
        """Resolve reply_future on the stream thread's loop so process()
        can continue and reply.
        """
        reply_loop = meta.get("reply_loop")
        reply_future = meta.get("reply_future")
        if reply_loop is None or reply_future is None:
            return
        reply_loop.call_soon_threadsafe(reply_future.set_result, text)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Build one reply body from parts and deliver via _reply_sync
        (one reply per request).
        """
        text_parts = []
        for p in parts:
            t = p.get("type")
            if t == "text" and p.get("text"):
                text_parts.append(p["text"])
            elif t == "refusal" and p.get("refusal"):
                text_parts.append(p["refusal"])
            elif t == "image" and p.get("image_url"):
                text_parts.append(f"[Image: {p['image_url']}]")
            elif t == "video" and p.get("video_url"):
                text_parts.append(f"[Video: {p['video_url']}]")
            elif t == "file" and (p.get("file_url") or p.get("file_id")):
                text_parts.append(
                    f"[File: {p.get('file_url') or p.get('file_id')}]",
                )
            elif t == "audio" and p.get("data"):
                text_parts.append("[Audio]")
            elif t == "data":
                text_parts.append("[Data]")
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", "") or ""
        if prefix and body:
            body = prefix + body
        elif prefix:
            body = prefix
        self._reply_sync(meta or {}, body)

    async def _consume_loop(self) -> None:
        from ...schemas.agent_schemas import RunStatus

        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            try:
                request = self.to_agent_request(msg)
                last_response = None
                accumulated_parts: list = []
                event_count = 0
                async for event in self._process(request):
                    event_count += 1
                    obj = getattr(event, "object", None)
                    status = getattr(event, "status", None)
                    ev_type = getattr(event, "type", None)
                    logger.debug(
                        "dingtalk event #%s: object=%s status=%s type=%s",
                        event_count,
                        obj,
                        status,
                        ev_type,
                    )
                    if obj == "message" and status == RunStatus.Completed:
                        parts = self._message_to_content_parts(event)
                        logger.info(
                            "dingtalk completed message: type=%s "
                            "parts_count=%s",
                            ev_type,
                            len(parts),
                        )
                        accumulated_parts.extend(parts)
                    elif obj == "response":
                        last_response = event
                logger.info(
                    "dingtalk stream done: event_count=%s "
                    "accumulated_parts=%s",
                    event_count,
                    len(accumulated_parts),
                )
                send_meta = {**(msg.meta or {}), "bot_prefix": self.bot_prefix}
                if last_response and getattr(last_response, "error", None):
                    err = getattr(
                        last_response.error,
                        "message",
                        str(last_response.error),
                    )
                    self._reply_sync(
                        send_meta,
                        self.bot_prefix + f"Error: {err}",
                    )
                elif accumulated_parts:
                    await self.send_content_parts(
                        msg.sender,
                        accumulated_parts,
                        send_meta,
                    )
                elif last_response is None:
                    self._reply_sync(
                        send_meta,
                        self.bot_prefix
                        + "An error occurred while processing your request.",
                    )
            except Exception:
                logger.exception("process/reply failed")
                self._reply_sync(
                    msg.meta or {},
                    "An error occurred while processing your request.",
                )

    def _run_stream_forever(self) -> None:
        logger.info(
            "dingtalk stream thread started (client_id=%s)",
            self.client_id,
        )
        try:
            if self._client:
                self._client.start_forever()
        except Exception:
            logger.exception("dingtalk stream thread failed")
        finally:
            self._stop_event.set()
            logger.info("dingtalk stream thread stopped")

    async def start(self) -> None:
        if not self.enabled:
            logger.info("disabled by env DINGTALK_GATEWAY_ENABLED=0")
            return
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET are required "
                "when gateway is enabled.",
            )

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=1000)
        self._consumer_task = asyncio.create_task(
            self._consume_loop(),
            name="dingtalk_gateway_consumer",
        )

        credential = dingtalk_stream.Credential(
            self.client_id,
            self.client_secret,
        )
        self._client = dingtalk_stream.DingTalkStreamClient(credential)
        internal_handler = _DingTalkGatewayHandler(
            main_loop=self._loop,
            queue=self._queue,
            bot_prefix=self.bot_prefix,
        )
        self._client.register_callback_handler(
            ChatbotMessage.TOPIC,
            internal_handler,
        )

        self._stop_event.clear()
        self._stream_thread = threading.Thread(
            target=self._run_stream_forever,
            daemon=True,
        )
        self._stream_thread.start()

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=5)
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._client = None

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Not supported: this gateway is reply-only
        (no proactive send by to_handle).
        """
        if not self.enabled:
            return
        logger.warning(
            "DingTalkGateway.send not implemented (reply-only gateway)",
        )
