# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""
Base gateway: bound to AgentRequest/AgentResponse, unified by process.
"""
from __future__ import annotations

import logging
from abc import ABC
from typing import (
    Optional,
    Dict,
    Any,
    List,
    AsyncIterator,
    Callable,
    TYPE_CHECKING,
)

from .schema import Incoming, ChannelType

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ...schemas.agent_schemas import AgentRequest, AgentResponse, Event

# process: accepts AgentRequest, streams Event
# (including message events with status completed)
ProcessHandler = Callable[[Any], AsyncIterator["Event"]]

# One content part to send
# (aligned with agent_schemas ContentType and content classes)
OutgoingContentPart = Dict[str, Any]


class BaseGateway(ABC):
    channel: ChannelType

    def __init__(self, process: ProcessHandler):
        self._process = process

    @classmethod
    def from_env(cls, process: ProcessHandler) -> "BaseGateway":
        raise NotImplementedError

    def to_agent_request(self, incoming: Incoming) -> "AgentRequest":
        """
        Convert this channel's Incoming to AgentRequest.
        Subclasses may override to support image, video, etc.
        (from get_content_list() or meta).
        """
        from ...schemas.agent_schemas import (
            AgentRequest,
            Message,
            TextContent,
            ContentType,
            MessageType,
            Role,
            ImageContent,
            VideoContent,
            AudioContent,
            FileContent,
        )

        content_list = incoming.get_content_list()
        contents = []
        for item in content_list:
            if item.type == "text" and item.text:
                contents.append(
                    TextContent(type=ContentType.TEXT, text=item.text),
                )
            elif item.type == "image" and item.image_url:
                contents.append(
                    ImageContent(
                        type=ContentType.IMAGE,
                        image_url=item.image_url,
                    ),
                )
            elif item.type == "video" and item.video_url:
                contents.append(
                    VideoContent(
                        type=ContentType.VIDEO,
                        video_url=item.video_url,
                    ),
                )
            elif item.type == "audio" and (item.audio_url or item.text):
                contents.append(
                    AudioContent(
                        type=ContentType.AUDIO,
                        data=item.audio_url or item.text,
                    ),
                )
            elif item.type == "file" and (item.file_url or item.file_id):
                contents.append(
                    FileContent(
                        type=ContentType.FILE,
                        file_url=item.file_url,
                        file_id=item.file_id,
                        filename=item.filename,
                    ),
                )
        if not contents:
            contents = [
                TextContent(type=ContentType.TEXT, text=incoming.text or ""),
            ]

        session_id = f"{incoming.channel}:{incoming.sender}"
        user_id = incoming.sender
        msg = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=contents,
        )
        return AgentRequest(
            session_id=session_id,
            user_id=user_id,
            input=[msg],
        )

    async def send_response(
        self,
        to_handle: str,
        response: "AgentResponse",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Convert AgentResponse to this channel's reply and send.
        Default: take last message text from output and call
        send(to_handle, text, meta).
        Subclasses may override to support image, video attachments.
        """
        text = self._response_to_text(response)
        await self.send(to_handle, text or "", meta)

    def _message_to_content_parts(
        self,
        message: Any,
    ) -> List[OutgoingContentPart]:
        """
        Convert a Message (object=='message') into a list of sendable
        content parts.
        Supports: MESSAGE (text, image, video, audio, file, refusal, data),
        FUNCTION_CALL / PLUGIN_CALL (show tool name + arguments),
        FUNCTION_CALL_OUTPUT / PLUGIN_CALL_OUTPUT (show result).
        """
        from ...schemas.agent_schemas import MessageType, ContentType

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        logger.debug(
            "gateway _message_to_content_parts: msg_type=%s content_len=%s",
            msg_type,
            len(content),
        )

        def _parts_for_tool_call(
            content_list: list,
        ) -> List[OutgoingContentPart]:
            parts: List[OutgoingContentPart] = []
            for c in content_list:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None) or {}
                name = data.get("name") or "tool"
                args = data.get("arguments") or "{}"
                args_preview = args[:200] + "..." if len(args) > 200 else args
                parts.append(
                    {
                        "type": "text",
                        "text": f"Calling: **{name}**\n```\
                        n{args_preview}\n```",
                    },
                )
            return parts

        def _parts_for_tool_output(
            content_list: list,
        ) -> List[OutgoingContentPart]:
            parts = []
            for c in content_list:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None) or {}
                name = data.get("name") or "tool"
                output = data.get("output") or ""
                output_preview = (
                    output[:500] + "..." if len(output) > 500 else output
                )
                parts.append(
                    {
                        "type": "text",
                        "text": f"Result of **{name}**:"
                        f"\n```\n{output_preview}\n```",
                    },
                )
            return parts

        if msg_type in (MessageType.FUNCTION_CALL, MessageType.PLUGIN_CALL):
            parts = _parts_for_tool_call(content)
            if not parts:
                parts = [{"type": "text", "text": f"[{msg_type}]"}]
            logger.info(
                "gateway %s -> %d part(s)",
                msg_type,
                len(parts),
            )
            return parts

        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
        ):
            parts = _parts_for_tool_output(content)
            if not parts:
                parts = [{"type": "text", "text": f"[{msg_type}]"}]
            logger.info(
                "gateway %s -> %d part(s)",
                msg_type,
                len(parts),
            )
            return parts

        # All other message types
        # (MESSAGE, component_call, mcp_call, reasoning, etc.):
        # render from content so every object=message gets sent
        parts = []
        for c in content:
            ctype = getattr(c, "type", None)
            if ctype == ContentType.TEXT and getattr(c, "text", None):
                parts.append({"type": "text", "text": c.text})
            elif ctype == ContentType.REFUSAL and getattr(c, "refusal", None):
                parts.append({"type": "refusal", "refusal": c.refusal})
            elif ctype == ContentType.IMAGE and getattr(c, "image_url", None):
                parts.append({"type": "image", "image_url": c.image_url})
            elif ctype == ContentType.VIDEO and getattr(c, "video_url", None):
                parts.append({"type": "video", "video_url": c.video_url})
            elif ctype == ContentType.AUDIO:
                data = getattr(c, "data", None)
                fmt = getattr(c, "format", None)
                if data:
                    parts.append(
                        {"type": "audio", "data": data, "format": fmt},
                    )
            elif ctype == ContentType.FILE:
                parts.append(
                    {
                        "type": "file",
                        "file_url": getattr(c, "file_url", None),
                        "file_id": getattr(c, "file_id", None),
                        "filename": getattr(c, "filename", None),
                        "file_data": getattr(c, "file_data", None),
                    },
                )
            elif ctype == ContentType.DATA and getattr(c, "data", None):
                data = c.data
                if isinstance(data, dict):
                    name = data.get("name")
                    output = data.get("output")
                    args = data.get("arguments")
                    if name is not None and (
                        output is not None or args is not None
                    ):
                        if output is not None:
                            preview = str(output)[:500] + (
                                "..." if len(str(output)) > 500 else ""
                            )
                            parts.append(
                                {
                                    "type": "text",
                                    "text": f"**{name}**:\n```\n"
                                    f"{preview}\n```",
                                },
                            )
                        else:
                            preview = str(args)[:200] + (
                                "..." if len(str(args)) > 200 else ""
                            )
                            parts.append(
                                {
                                    "type": "text",
                                    "text": f"**{name}**:"
                                    f"\n```\n{preview}\n```",
                                },
                            )
                    else:
                        parts.append({"type": "data", "data": data})
                else:
                    parts.append({"type": "data", "data": data})
        if not parts and msg_type:
            parts = [{"type": "text", "text": f"[Message type: {msg_type}]"}]
        return parts

    async def send_message_content(
        self,
        to_handle: str,
        message: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send all content of a Message
        (text, image, video, audio, file, refusal).
        Subclasses may override send_content_parts for channel-specific
        multi-part sending.
        """
        parts = self._message_to_content_parts(message)
        if not parts:
            logger.debug(
                "gateway send_message_content: no parts for to_handle=%s, "
                "skip send",
                to_handle,
            )
            return
        logger.debug(
            "gateway send_message_content: to_handle=%s parts_count=%s "
            "part_types=%s",
            to_handle,
            len(parts),
            [p.get("type") for p in parts],
        )
        await self.send_content_parts(to_handle, parts, meta)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a list of content parts.
        Default: merge text/refusal into one text, append media URLs as
        fallback, send one message; optionally call send_media for each
        media part if overridden.
        """
        text_parts: List[str] = []
        media_parts: List[OutgoingContentPart] = []
        for p in parts:
            t = p.get("type")
            if t == "text" and p.get("text"):
                text_parts.append(p["text"])
            elif t == "refusal" and p.get("refusal"):
                text_parts.append(p["refusal"])
            elif t in ("image", "video", "audio", "file", "data"):
                media_parts.append(p)
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", "") or ""
        if prefix and body:
            body = prefix + body
        for m in media_parts:
            t = m.get("type")
            if t == "image" and m.get("image_url"):
                body += f"\n[Image: {m['image_url']}]"
            elif t == "video" and m.get("video_url"):
                body += f"\n[Video: {m['video_url']}]"
            elif t == "file" and (m.get("file_url") or m.get("file_id")):
                body += f"\n[File: {m.get('file_url') or m.get('file_id')}]"
            elif t == "audio" and m.get("data"):
                body += "\n[Audio]"
            elif t == "data":
                body += "\n[Data]"
        if body.strip():
            logger.debug(
                "gateway send_content_parts: to_handle=%s body_len=%s "
                "preview=%r",
                to_handle,
                len(body),
                body[:120] + "..." if len(body) > 120 else body,
            )
            await self.send(to_handle, body.strip(), meta)
        for m in media_parts:
            await self.send_media(to_handle, m, meta)

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a single media part (image, video, audio, file).
        Default: no-op (already appended to text in send_content_parts).
        Subclasses override to send real attachments.
        """

    def _response_to_text(self, response: "AgentResponse") -> str:
        """Extract reply text from AgentResponse (last message in output)."""
        from ...schemas.agent_schemas import MessageType, ContentType

        if not response.output:
            return ""
        last_msg = response.output[-1]
        if last_msg.type != MessageType.MESSAGE or not last_msg.content:
            return ""
        parts = []
        for c in last_msg.content:
            if getattr(c, "type", None) == ContentType.TEXT and getattr(
                c,
                "text",
                None,
            ):
                parts.append(c.text)
            elif getattr(c, "type", None) == ContentType.REFUSAL and getattr(
                c,
                "refusal",
                None,
            ):
                parts.append(c.refusal)
        return "".join(parts)

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
        """Subclass implements: send one text
        (and optional attachments) to to_handle.
        """
        raise NotImplementedError
