# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""QQ Gateway.

QQ uses WebSocket for incoming events and HTTP API for replies.
No request-reply coupling: handler enqueues Incoming, consumer processes
and sends reply via send_c2c_message / send_channel_message /
send_group_message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

import aiohttp

from .schema import Incoming
from .base import BaseGateway, OutgoingContentPart, ProcessHandler

logger = logging.getLogger(__name__)

# QQ Bot WebSocket op codes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Intents
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_GUILD_MEMBERS = 1 << 1

RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
RATE_LIMIT_DELAY = 60
MAX_RECONNECT_ATTEMPTS = 100
QUICK_DISCONNECT_THRESHOLD = 5
MAX_QUICK_DISCONNECT_COUNT = 3

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

_token_cache: Optional[Dict[str, Any]] = None
_token_lock = threading.Lock()


def _get_access_token_sync(app_id: str, client_secret: str) -> str:
    """Sync get access_token for use in WebSocket thread.
    Cached with 5min margin.
    """
    global _token_cache
    with _token_lock:
        if _token_cache and time.time() < _token_cache["expires_at"] - 300:
            return _token_cache["token"]
    try:
        import urllib.request

        req = urllib.request.Request(
            TOKEN_URL,
            data=json.dumps(
                {"appId": app_id, "clientSecret": client_secret},
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"Failed to get access_token: {e}") from e
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {data}")
    expires_in = data.get("expires_in", 7200)
    with _token_lock:
        _token_cache = {
            "token": token,
            "expires_at": time.time() + expires_in,
        }
    return token


def clear_token_cache() -> None:
    global _token_cache
    with _token_lock:
        _token_cache = None


def _get_gateway_url_sync(access_token: str) -> str:
    try:
        import urllib.request

        url = f"{API_BASE}/gateway"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"QQBot {access_token}",
                "Content-Type": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"Failed to get gateway url: {e}") from e
    gateway_url = data.get("url")
    if not gateway_url:
        raise RuntimeError(f"No url in gateway response: {data}")
    return gateway_url


def _api_request_sync(
    access_token: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    import urllib.request

    url = f"{API_BASE}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


_msg_seq: Dict[str, int] = {}
_msg_seq_lock = threading.Lock()


def _get_next_msg_seq(msg_id: str) -> int:
    with _msg_seq_lock:
        n = _msg_seq.get(msg_id, 0) + 1
        _msg_seq[msg_id] = n
        if len(_msg_seq) > 1000:
            for k in list(_msg_seq.keys())[:500]:
                del _msg_seq[k]
        return n


async def _get_access_token_async(app_id: str, client_secret: str) -> str:
    """Async get token for send_content_parts. Uses aiohttp."""
    global _token_cache
    with _token_lock:
        if _token_cache and time.time() < _token_cache["expires_at"] - 300:
            return _token_cache["token"]
    async with aiohttp.ClientSession() as session:
        async with session.post(
            TOKEN_URL,
            json={"appId": app_id, "clientSecret": client_secret},
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"Token request failed {resp.status}: {text}",
                )
            data = await resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token: {data}")
    expires_in = data.get("expires_in", 7200)
    with _token_lock:
        _token_cache = {
            "token": token,
            "expires_at": time.time() + expires_in,
        }
    return token


async def _api_request_async(
    access_token: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    async with aiohttp.ClientSession() as session:
        kwargs = {
            "headers": {
                "Authorization": f"QQBot {access_token}",
                "Content-Type": "application/json",
            },
        }
        if body is not None:
            kwargs["json"] = body
        async with session.request(method, url, **kwargs) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"API {path} {resp.status}: {data}")
            return data


async def _send_c2c_message_async(
    access_token: str,
    openid: str,
    content: str,
    msg_id: Optional[str] = None,
) -> None:
    msg_seq = _get_next_msg_seq(msg_id or "c2c")
    body = {"content": content, "msg_type": 0, "msg_seq": msg_seq}
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        access_token,
        "POST",
        f"/v2/users/{openid}/messages",
        body,
    )


async def _send_channel_message_async(
    access_token: str,
    channel_id: str,
    content: str,
    msg_id: Optional[str] = None,
) -> None:
    body = {"content": content}
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        access_token,
        "POST",
        f"/channels/{channel_id}/messages",
        body,
    )


async def _send_group_message_async(
    access_token: str,
    group_openid: str,
    content: str,
    msg_id: Optional[str] = None,
) -> None:
    msg_seq = _get_next_msg_seq(msg_id or "group")
    body = {"content": content, "msg_type": 0, "msg_seq": msg_seq}
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        access_token,
        "POST",
        f"/v2/groups/{group_openid}/messages",
        body,
    )


class QQGateway(BaseGateway):
    """QQ Gateway:
    WebSocket events -> Incoming -> process -> HTTP API reply.
    """

    channel = "qq"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        app_id: str,
        client_secret: str,
        bot_prefix: str = "",
    ):
        super().__init__(process)
        self.enabled = enabled
        self.app_id = app_id
        self.client_secret = client_secret
        self.bot_prefix = bot_prefix

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[Incoming]] = None
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._account_id = "default"

    @classmethod
    def from_env(cls, process: ProcessHandler) -> "QQGateway":
        return cls(
            process=process,
            enabled=os.getenv("QQ_GATEWAY_ENABLED", "1") == "1",
            app_id=os.getenv("QQ_APP_ID", ""),
            client_secret=os.getenv("QQ_CLIENT_SECRET", ""),
            bot_prefix=os.getenv("QQ_BOT_PREFIX", ""),
        )

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send one text via QQ HTTP API.
        Routes by meta or to_handle (group:/channel:/openid).
        """
        if not self.enabled or not text.strip():
            return
        meta = meta or {}
        message_type = meta.get("message_type")
        msg_id = meta.get("message_id")
        sender_id = meta.get("sender_id") or to_handle
        channel_id = meta.get("channel_id")
        group_openid = meta.get("group_openid")
        if message_type is None:
            if to_handle.startswith("group:"):
                message_type = "group"
                group_openid = to_handle[6:]
            elif to_handle.startswith("channel:"):
                message_type = "guild"
                channel_id = to_handle[8:]
            else:
                message_type = "c2c"
        try:
            token = await _get_access_token_async(
                self.app_id,
                self.client_secret,
            )
        except Exception:
            logger.exception("get access_token failed")
            return
        try:
            if message_type == "c2c":
                await _send_c2c_message_async(
                    token,
                    sender_id,
                    text.strip(),
                    msg_id,
                )
            elif message_type == "group" and group_openid:
                await _send_group_message_async(
                    token,
                    group_openid,
                    text.strip(),
                    msg_id,
                )
            elif channel_id:
                await _send_channel_message_async(
                    token,
                    channel_id,
                    text.strip(),
                    msg_id,
                )
            else:
                await _send_c2c_message_async(
                    token,
                    sender_id,
                    text.strip(),
                    msg_id,
                )
        except Exception:
            logger.exception("send failed")

    async def _consume_loop(self) -> None:
        from ...schemas.agent_schemas import RunStatus

        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            try:
                request = self.to_agent_request(msg)
                last_response = None
                accumulated_parts: List[OutgoingContentPart] = []
                event_count = 0
                send_meta = {**(msg.meta or {}), "bot_prefix": self.bot_prefix}

                async for event in self._process(request):
                    event_count += 1
                    obj = getattr(event, "object", None)
                    status = getattr(event, "status", None)
                    ev_type = getattr(event, "type", None)
                    logger.debug(
                        "qq event #%s: object=%s status=%s type=%s",
                        event_count,
                        obj,
                        status,
                        ev_type,
                    )
                    if obj == "message" and status == RunStatus.Completed:
                        parts = self._message_to_content_parts(event)
                        logger.info(
                            "qq completed message: type=%s parts_count=%s",
                            ev_type,
                            len(parts),
                        )
                        accumulated_parts.extend(parts)
                    elif obj == "response":
                        last_response = event

                if last_response and getattr(last_response, "error", None):
                    err = getattr(
                        last_response.error,
                        "message",
                        str(last_response.error),
                    )
                    err_text = self.bot_prefix + f"Error: {err}"
                    await self.send_content_parts(
                        msg.sender,
                        [{"type": "text", "text": err_text}],
                        send_meta,
                    )
                elif accumulated_parts:
                    await self.send_content_parts(
                        msg.sender,
                        accumulated_parts,
                        send_meta,
                    )
                elif last_response is None:
                    await self.send_content_parts(
                        msg.sender,
                        [
                            {
                                "type": "text",
                                "text": self.bot_prefix
                                + "An error occurred while processing your "
                                "request.",
                            },
                        ],
                        send_meta,
                    )
            except Exception:
                logger.exception("qq process/reply failed")
                try:
                    await self.send_content_parts(
                        msg.sender,
                        [
                            {
                                "type": "text",
                                "text": "An error occurred while processing "
                                "your request.",
                            },
                        ],
                        msg.meta or {},
                    )
                except Exception:
                    logger.exception("send error message failed")

    def _run_ws_forever(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.error(
                "websocket-client not installed. pip install websocket-client",
            )
            return
        reconnect_attempts = 0
        last_connect_time = 0.0
        quick_disconnect_count = 0
        session_id: Optional[str] = None
        last_seq: Optional[int] = None
        identify_fail_count = 0
        should_refresh_token = False

        def connect() -> bool:
            nonlocal session_id, last_seq, reconnect_attempts, last_connect_time, quick_disconnect_count, should_refresh_token, identify_fail_count  # pylint: disable=line-too-long # noqa: E501
            if self._stop_event.is_set():
                return False
            if should_refresh_token:
                clear_token_cache()
                should_refresh_token = False
            try:
                token = _get_access_token_sync(self.app_id, self.client_secret)
                url = _get_gateway_url_sync(token)
            except Exception as e:
                logger.warning("qq get token/gateway failed: %s", e)
                return True
            logger.info("qq connecting to %s", url)
            try:
                ws = websocket.create_connection(url)
            except Exception as e:
                logger.warning("qq ws connect failed: %s", e)
                return True
            current_ws = ws
            heartbeat_interval: Optional[float] = None
            heartbeat_timer: Optional[threading.Timer] = None

            def stop_heartbeat() -> None:
                if heartbeat_timer:
                    heartbeat_timer.cancel()

            def schedule_heartbeat() -> None:
                nonlocal heartbeat_timer
                if heartbeat_interval is None or self._stop_event.is_set():
                    return

                def send_ping() -> None:
                    if self._stop_event.is_set():
                        return
                    try:
                        if current_ws.connected:
                            current_ws.send(
                                json.dumps(
                                    {"op": OP_HEARTBEAT, "d": last_seq},
                                ),
                            )
                            logger.debug("qq heartbeat sent")
                    except Exception:
                        pass
                    schedule_heartbeat()

                heartbeat_timer = threading.Timer(
                    heartbeat_interval / 1000.0,
                    send_ping,
                )
                heartbeat_timer.daemon = True
                heartbeat_timer.start()

            try:
                while not self._stop_event.is_set():
                    raw = current_ws.recv()
                    if not raw:
                        break
                    payload = json.loads(raw)
                    op = payload.get("op")
                    d = payload.get("d")
                    s = payload.get("s")
                    t = payload.get("t")
                    if s is not None:
                        last_seq = s

                    if op == OP_HELLO:
                        hi = d or {}
                        heartbeat_interval = hi.get(
                            "heartbeat_interval",
                            45000,
                        )
                        if session_id and last_seq is not None:
                            current_ws.send(
                                json.dumps(
                                    {
                                        "op": OP_RESUME,
                                        "d": {
                                            "token": f"QQBot {token}",
                                            "session_id": session_id,
                                            "seq": last_seq,
                                        },
                                    },
                                ),
                            )
                        else:
                            intents = (
                                INTENT_PUBLIC_GUILD_MESSAGES
                                | INTENT_GUILD_MEMBERS
                            )
                            if identify_fail_count < 3:
                                intents |= (
                                    INTENT_DIRECT_MESSAGE
                                    | INTENT_GROUP_AND_C2C
                                )
                            current_ws.send(
                                json.dumps(
                                    {
                                        "op": OP_IDENTIFY,
                                        "d": {
                                            "token": f"QQBot {token}",
                                            "intents": intents,
                                            "shard": [0, 1],
                                        },
                                    },
                                ),
                            )
                        schedule_heartbeat()
                    elif op == OP_DISPATCH:
                        if t == "READY":
                            session_id = (d or {}).get("session_id")
                            identify_fail_count = 0
                            reconnect_attempts = 0
                            last_connect_time = time.time()
                            logger.info("qq ready session_id=%s", session_id)
                        elif t == "RESUMED":
                            logger.info("qq session resumed")
                        elif t == "C2C_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("user_openid")
                                or author.get("id")
                                or ""
                            )
                            if not sender:
                                continue
                            msg_id = (d or {}).get("id", "")
                            # ts = (d or {}).get("timestamp", "")
                            att = (d or {}).get("attachments") or []
                            incoming = Incoming(
                                channel="qq",
                                sender=sender,
                                text=text,
                                meta={
                                    "message_type": "c2c",
                                    "message_id": msg_id,
                                    "sender_id": sender,
                                    "incoming_raw": d,
                                    "attachments": att,
                                },
                            )
                            if self._loop and self._queue:
                                self._loop.call_soon_threadsafe(
                                    self._queue.put_nowait,
                                    incoming,
                                )
                            logger.info(
                                "qq recv c2c from=%s text=%r",
                                sender,
                                text[:100],
                            )
                        elif t == "AT_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("id")
                                or author.get("username")
                                or ""
                            )
                            if not sender:
                                continue
                            channel_id = (d or {}).get("channel_id", "")
                            guild_id = (d or {}).get("guild_id", "")
                            msg_id = (d or {}).get("id", "")
                            # ts = (d or {}).get("timestamp", "")
                            att = (d or {}).get("attachments") or []
                            incoming = Incoming(
                                channel="qq",
                                sender=sender,
                                text=text,
                                meta={
                                    "message_type": "guild",
                                    "message_id": msg_id,
                                    "sender_id": sender,
                                    "channel_id": channel_id,
                                    "guild_id": guild_id,
                                    "incoming_raw": d,
                                    "attachments": att,
                                },
                            )
                            if self._loop and self._queue:
                                self._loop.call_soon_threadsafe(
                                    self._queue.put_nowait,
                                    incoming,
                                )
                            logger.info(
                                "qq recv guild from=%s channel=%s text=%r",
                                sender,
                                channel_id,
                                text[:100],
                            )
                        elif t == "DIRECT_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("id")
                                or author.get("username")
                                or ""
                            )
                            if not sender:
                                continue
                            channel_id = (d or {}).get("channel_id", "")
                            guild_id = (d or {}).get("guild_id", "")
                            msg_id = (d or {}).get("id", "")
                            att = (d or {}).get("attachments") or []
                            incoming = Incoming(
                                channel="qq",
                                sender=sender,
                                text=text,
                                meta={
                                    "message_type": "dm",
                                    "message_id": msg_id,
                                    "sender_id": sender,
                                    "channel_id": channel_id,
                                    "guild_id": guild_id,
                                    "incoming_raw": d,
                                    "attachments": att,
                                },
                            )
                            if self._loop and self._queue:
                                self._loop.call_soon_threadsafe(
                                    self._queue.put_nowait,
                                    incoming,
                                )
                            logger.info(
                                "qq recv dm from=%s text=%r",
                                sender,
                                text[:100],
                            )
                        elif t == "GROUP_AT_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("member_openid")
                                or author.get("id")
                                or ""
                            )
                            if not sender:
                                continue
                            group_openid = (d or {}).get("group_openid", "")
                            msg_id = (d or {}).get("id", "")
                            att = (d or {}).get("attachments") or []
                            incoming = Incoming(
                                channel="qq",
                                sender=sender,
                                text=text,
                                meta={
                                    "message_type": "group",
                                    "message_id": msg_id,
                                    "sender_id": sender,
                                    "group_openid": group_openid,
                                    "incoming_raw": d,
                                    "attachments": att,
                                },
                            )
                            if self._loop and self._queue:
                                self._loop.call_soon_threadsafe(
                                    self._queue.put_nowait,
                                    incoming,
                                )
                            logger.info(
                                "qq recv group from=%s group=%s text=%r",
                                sender,
                                group_openid,
                                text[:100],
                            )
                    elif op == OP_HEARTBEAT_ACK:
                        logger.debug("qq heartbeat ack")
                    elif op == OP_RECONNECT:
                        logger.info("qq server requested reconnect")
                        break
                    elif op == OP_INVALID_SESSION:
                        can_resume = d
                        logger.error(
                            "qq invalid session can_resume=%s",
                            can_resume,
                        )
                        if not can_resume:
                            session_id = None
                            last_seq = None
                            identify_fail_count += 1
                            should_refresh_token = True
                        break
            except websocket.WebSocketConnectionClosedException:
                pass
            except Exception as e:
                logger.exception("qq ws loop: %s", e)
            finally:
                stop_heartbeat()
                try:
                    current_ws.close()
                except Exception:
                    pass
            last_connect_time_val = last_connect_time
            if (
                last_connect_time_val
                and (time.time() - last_connect_time_val)
                < QUICK_DISCONNECT_THRESHOLD
            ):
                quick_disconnect_count += 1
                if quick_disconnect_count >= MAX_QUICK_DISCONNECT_COUNT:
                    session_id = None
                    last_seq = None
                    should_refresh_token = True
                    quick_disconnect_count = 0
                    reconnect_attempts = min(
                        reconnect_attempts,
                        len(RECONNECT_DELAYS) - 1,
                    )
                    delay = RATE_LIMIT_DELAY
                else:
                    delay = RECONNECT_DELAYS[
                        min(reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                    ]
            else:
                quick_disconnect_count = 0
                delay = RECONNECT_DELAYS[
                    min(reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                ]
            reconnect_attempts += 1
            if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                logger.error("qq max reconnect attempts reached")
                return False
            logger.info(
                "qq reconnecting in %ss (attempt %s)",
                delay,
                reconnect_attempts,
            )
            self._stop_event.wait(timeout=delay)
            return not self._stop_event.is_set()

        while connect():
            pass
        self._stop_event.set()
        logger.info("qq ws thread stopped")

    async def start(self) -> None:
        if not self.enabled:
            logger.info("qq gateway disabled by QQ_GATEWAY_ENABLED=0")
            return
        if not self.app_id or not self.client_secret:
            raise RuntimeError(
                "QQ_APP_ID and QQ_CLIENT_SECRET are required when "
                "gateway is enabled.",
            )
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=1000)
        self._consumer_task = asyncio.create_task(
            self._consume_loop(),
            name="qq_gateway_consumer",
        )
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
        )
        self._ws_thread.start()

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._ws_thread:
            self._ws_thread.join(timeout=8)
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
