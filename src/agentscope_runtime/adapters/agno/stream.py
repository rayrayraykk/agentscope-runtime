# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks,too-many-branches,too-many-statements
import json

from typing import AsyncIterator

from agno.run.agent import (
    BaseAgentRunEvent,
    RunContentEvent,
    RunCompletedEvent,
    RunContentCompletedEvent,
    RunStartedEvent,
    # ReasoningStartedEvent,
    # ReasoningStepEvent,
    # ReasoningCompletedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
)


from ...engine.schemas.agent_schemas import (
    Message,
    TextContent,
    DataContent,
    # McpCall,
    # McpCallOutput,
    FunctionCall,
    FunctionCallOutput,
    MessageType,
)


def _update_obj_attrs(obj, **attrs):
    for key, value in attrs.items():
        if hasattr(obj, key):
            setattr(obj, key, value)
    return obj


async def adapt_agno_message_stream(
    source_stream: AsyncIterator[BaseAgentRunEvent],
) -> AsyncIterator[Message]:
    text_message = Message(
        type=MessageType.MESSAGE,
        role="assistant",
    )

    text_delta_content = TextContent(delta=True)

    async for event in source_stream:
        if isinstance(event, RunStartedEvent):
            # Placeholder
            pass
        elif isinstance(event, RunCompletedEvent):
            # Placeholder
            return
        elif isinstance(event, RunContentEvent):
            text_delta_content.text = event.content
            text_delta_content = text_message.add_delta_content(
                new_content=text_delta_content,
            )
            yield text_delta_content
        elif isinstance(event, RunContentCompletedEvent):
            yield text_message.content_completed(text_delta_content.index)
            yield text_message.completed()
        elif isinstance(event, ToolCallStartedEvent):
            json_str = json.dumps(event.tool.tool_args, ensure_ascii=False)
            data = DataContent(
                data=FunctionCall(
                    call_id=event.tool.tool_call_id,
                    name=event.tool.tool_name,
                    arguments=json_str,
                ).model_dump(),
            )
            message = Message(
                type=MessageType.PLUGIN_CALL,
                role="assistant",
                content=[data],
            )
            # No stream tool call
            yield message.completed()
        elif isinstance(event, ToolCallCompletedEvent):
            try:
                json_str = json.dumps(event.tool.result, ensure_ascii=False)
            except Exception:
                json_str = str(event.tool.result)

            data = DataContent(
                data=FunctionCallOutput(
                    name=event.tool.tool_name,
                    call_id=event.tool.tool_call_id,
                    output=json_str,
                ).model_dump(),
            )
            message = Message(
                type=MessageType.PLUGIN_CALL_OUTPUT,
                role="tool",
                content=[data],
            )
            yield message.completed()
