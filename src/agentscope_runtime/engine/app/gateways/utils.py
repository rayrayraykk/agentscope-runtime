# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import AsyncIterator, Callable, Any

from ...schemas.agent_schemas import AgentRequest
from ....adapters.agentscope.message import message_to_agentscope_msg


def make_gateway_handler(
    runner: Any,
    query_func,
) -> Callable[[Any], AsyncIterator[str]]:
    """
    Build a gateway handler that adapts:
      - gateway incoming message object -> AgentRequest -> msgs
      - then calls `query_func(runner, msgs, request=...)`
        which is an async generator yielding (msg, last)

    The returned handler is an async generator:
      handler(incoming) -> AsyncIterator[str]
    Each yielded string is a chunk to be sent by the gateway.
    """

    async def handler(incoming: Any) -> AsyncIterator[str]:
        # Build a stable session/user identity from the incoming envelope.
        session_id = (
            f"{getattr(incoming, 'channel', 'unknown')}"
            f":{getattr(incoming, 'sender', 'unknown')}"
        )
        user_id = getattr(incoming, "sender", "unknown")

        # Construct an AgentRequest in the engine's expected "input" schema.
        request = AgentRequest(
            session_id=session_id,
            user_id=user_id,
            input=[
                {
                    "role": "user",
                    "type": "message",
                    "content": [
                        {
                            "type": "text",
                            "text": getattr(incoming, "text", ""),
                        },
                    ],
                },
            ],
        )

        # Convert engine message schema to AgentScope msgs.
        msgs = message_to_agentscope_msg(request.input)

        # Call your existing query function and adapt its streaming output
        # to plain text chunks.
        async for msg, last in query_func(
            runner,
            msgs,
            request=request,
        ):
            # In your current logic, only emit the final message content.
            if last:
                yield str(getattr(msg, "content", msg))

    return handler
