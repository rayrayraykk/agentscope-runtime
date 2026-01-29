# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import os
import time
import sqlite3
import subprocess
import threading
import shutil
import asyncio
from typing import Optional, Dict, Any

from .schema import Incoming
from .base import BaseGateway, AsyncGenHandler

logger = logging.getLogger(__name__)


class IMessageGateway(BaseGateway):
    channel = "imessage"

    def __init__(
        self,
        handler: AsyncGenHandler,
        enabled: bool,
        db_path: str,
        poll_sec: float,
        bot_prefix: str,
    ):
        super().__init__(handler)
        self.enabled = enabled
        self.db_path = os.path.expanduser(db_path)
        self.poll_sec = poll_sec
        self.bot_prefix = bot_prefix

        self._imsg_path: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[Incoming]] = None
        self._consumer_task: Optional[asyncio.Task] = None

    @classmethod
    def from_env(cls, handler: AsyncGenHandler) -> "IMessageGateway":
        return cls(
            handler=handler,
            enabled=os.getenv("IMESSAGE_ENABLED", "1") == "1",
            db_path=os.getenv(
                "IMESSAGE_DB_PATH",
                "~/Library/Messages/chat.db",
            ),
            poll_sec=float(os.getenv("IMESSAGE_POLL_SEC", "1.0")),
            bot_prefix=os.getenv("IMESSAGE_BOT_PREFIX", "[BOT] "),
        )

    def _ensure_imsg(self) -> str:
        path = shutil.which("imsg")
        if not path:
            raise RuntimeError(
                "Cannot find executable: imsg. Install it with:\n"
                "  brew install steipete/tap/imsg\n"
                "Then verify:\n"
                "  which imsg\n",
            )
        return path

    def _send_sync(self, to_handle: str, text: str) -> None:
        if not self._imsg_path:
            raise RuntimeError(
                "iMessage gateway not initialized (imsg path missing).",
            )
        subprocess.run(
            [self._imsg_path, "send", "--to", to_handle, "--text", text],
            check=True,
        )

    def _emit_incoming_threadsafe(self, msg: Incoming) -> None:
        if not self._loop or not self._queue:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)

    def _watcher_loop(self) -> None:
        logger.info(
            "watcher thread started (poll=%.2fs, db=%s)",
            self.poll_sec,
            self.db_path,
        )

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_rowid = conn.execute(
            "SELECT IFNULL(MAX(ROWID),0) FROM message",
        ).fetchone()[0]

        try:
            while not self._stop_event.is_set():
                try:
                    rows = conn.execute(
                        """
SELECT m.ROWID, m.text, m.is_from_me, c.ROWID as chat_rowid, h.id as sender
FROM message m
JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
JOIN chat c ON c.ROWID = cmj.chat_id
LEFT JOIN handle h ON h.ROWID = m.handle_id
WHERE m.ROWID > ?
ORDER BY m.ROWID ASC
""",
                        (last_rowid,),
                    ).fetchall()

                    for r in rows:
                        last_rowid = r["ROWID"]
                        if r["is_from_me"] == 1:
                            continue
                        text = r["text"]
                        if not text or str(text).startswith(self.bot_prefix):
                            continue
                        sender = (r["sender"] or "").strip()
                        if not sender:
                            continue

                        msg = Incoming(
                            channel="imessage",
                            sender=sender,
                            text=text,
                            meta={
                                "chat_rowid": str(r["chat_rowid"]),
                                "rowid": int(r["ROWID"]),
                            },
                        )
                        logger.info(
                            "recv from=%s rowid=%s text=%r",
                            sender,
                            r["ROWID"],
                            text,
                        )
                        self._emit_incoming_threadsafe(msg)

                except Exception:
                    logger.exception("poll iteration failed")

                time.sleep(self.poll_sec)
        finally:
            conn.close()
            logger.info("watcher thread stopped")

    async def _consume_loop(self) -> None:
        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            try:
                async for chunk in self._handler(msg):
                    if not chunk:
                        continue
                    out = self.bot_prefix + chunk
                    await asyncio.to_thread(self._send_sync, msg.sender, out)
                    logger.info("sent to=%s text=%r", msg.sender, out)
            except Exception:
                logger.exception("handler/send failed")

    async def start(self) -> None:
        if not self.enabled:
            logger.info("disabled by env IMESSAGE_ENABLED=0")
            return

        self._imsg_path = self._ensure_imsg()
        logger.info("imsg binary: %s", self._imsg_path)

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=1000)
        self._consumer_task = asyncio.create_task(
            self._consume_loop(),
            name="imessage_consumer",
        )

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watcher_loop, daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        if not self.enabled:
            return

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except Exception:
                pass

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        await asyncio.to_thread(self._send_sync, to_handle, text)
