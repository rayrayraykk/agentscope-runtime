# -*- coding: utf-8 -*-
"""
Gateway message schema: per-channel incoming message and unified conversion
protocol.

Each gateway implements:
- to_agent_request(incoming) -> AgentRequest:
    convert channel incoming to engine AgentRequest
- send_response(to_handle, response, meta):
    convert AgentResponse to channel reply and send
"""
from __future__ import annotations

from typing import (
    Literal,
    Optional,
    List,
    Any,
    Protocol,
    runtime_checkable,
)

from pydantic import BaseModel, Field

ChannelType = Literal["imessage", "discord", "dingtalk", "qq"]


# -------- Incoming content item: text, image, video, audio, file --------
class IncomingContentItem(BaseModel):
    """Single incoming content item, aligned with
    AgentRequest.input[].content[].
    """

    type: Literal["text", "image", "video", "audio", "file"] = "text"
    text: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    file_url: Optional[str] = None
    file_id: Optional[str] = None
    filename: Optional[str] = None
    # Extension; gateways may put native payload here
    meta: dict = Field(default_factory=dict)


class Incoming(BaseModel):
    """
    Unified envelope for per-gateway incoming messages.

    - Use text for plain text; use content for multimodal.
    - When content is empty and text is set, conversion treats it as one
        text content.
    """

    channel: ChannelType
    sender: str
    text: str = ""
    content: Optional[List[IncomingContentItem]] = None
    meta: dict = Field(default_factory=dict)

    def get_content_list(self) -> List[IncomingContentItem]:
        """Return content list for building AgentRequest
        (backward compat: text-only as single item).
        """
        if self.content:
            return self.content
        if self.text:
            return [IncomingContentItem(type="text", text=self.text)]
        return []


# -------- Conversion protocol: gateway message <->
# AgentRequest/AgentResponse --------
@runtime_checkable
class GatewayMessageConverter(Protocol):
    """
    Each gateway implements: channel message <-> AgentRequest/AgentResponse.
    Protocol aligns text, image, video where possible; rest in meta or
    documented by gateway.
    """

    def to_agent_request(self, incoming: Incoming) -> Any:
        """
        Convert this channel's Incoming to AgentRequest
        (input as List[Message]).
        """

    async def send_response(
        self,
        to_handle: str,
        response: Any,
        meta: Optional[dict] = None,
    ) -> None:
        """
        Convert AgentResponse (or stream aggregate) to channel reply and send.
        """
