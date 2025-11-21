# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks,too-many-branches,too-many-statements
import copy
import json

from typing import AsyncIterator, Tuple, List

from agentscope.message import Msg

from ...engine.schemas.agent_schemas import (
    Message,
    TextContent,
    DataContent,
    FunctionCall,
    FunctionCallOutput,
    MessageType,
    RunStatus,
)


def _update_obj_attrs(obj, **attrs):
    for key, value in attrs.items():
        if hasattr(obj, key):
            setattr(obj, key, value)
    return obj


async def adapt_agentscope_message_stream(
    source_stream: AsyncIterator[Tuple[Msg, bool]],
) -> AsyncIterator[Message]:
    local_truncate_memory = ""
    local_truncate_reasoning_memory = ""

    # Yield new Msg instances as they are logged
    last_content = ""

    message = Message(type=MessageType.MESSAGE, role="assistant")
    reasoning_message = Message(
        type=MessageType.REASONING,
        role="assistant",
    )

    should_start_message = True
    should_start_reasoning_message = True

    index = None

    # Run agent
    async for msg, last in source_stream:
        # deepcopy required to avoid modifying the original message object
        # which may be used elsewhere in the streaming pipeline
        msg = copy.deepcopy(msg)

        # Filter out unfinished tool_use messages
        if not last:
            new_blocks = []
            if isinstance(msg.content, List):
                for block in msg.content:
                    if block.get("type", "") != "tool_use":
                        new_blocks.append(block)
                msg.content = new_blocks

        if not msg.content:
            continue

        # msg content
        content = msg.content

        # msg usage
        usage = getattr(msg, "usage", None)

        # msg metadata
        metadata = msg.metadata

        if isinstance(content, str):
            last_content = content
        else:
            for element in content:
                if isinstance(element, str) and element:
                    if should_start_message:
                        index = None
                        message = _update_obj_attrs(
                            message,
                            metadata=metadata,
                            usage=usage,
                        )
                        yield message.in_progress()
                        should_start_message = False
                    text_delta_content = TextContent(
                        delta=True,
                        index=index,
                        text=element,
                    )
                    text_delta_content = message.add_delta_content(
                        new_content=text_delta_content,
                    )
                    index = text_delta_content.index
                    yield text_delta_content
                elif isinstance(element, dict):
                    if element.get("type") == "text":
                        text = element.get(
                            "text",
                            "",
                        )
                        if text:
                            if should_start_message:
                                index = None
                                message = _update_obj_attrs(
                                    message,
                                    metadata=metadata,
                                    usage=usage,
                                )
                                yield message.in_progress()
                                should_start_message = False

                            text_delta_content = TextContent(
                                delta=True,
                                index=index,
                                text=text.removeprefix(
                                    local_truncate_memory,
                                ),
                            )
                            local_truncate_memory = element.get(
                                "text",
                                "",
                            )
                            text_delta_content = message.add_delta_content(
                                new_content=text_delta_content,
                            )
                            index = text_delta_content.index

                            # Only yield valid text
                            if text_delta_content.text:
                                yield text_delta_content

                            if last:
                                completed_content = message.content[index]
                                if completed_content.text:
                                    yield completed_content.completed()

                                message = _update_obj_attrs(
                                    message,
                                    metadata=metadata,
                                    usage=usage,
                                )
                                yield message.completed()
                                message = Message(
                                    type=MessageType.MESSAGE,
                                    role="assistant",
                                )
                                index = None
                                should_start_message = True

                    elif element.get("type") == "tool_use":
                        if reasoning_message.status == RunStatus.InProgress:
                            reasoning_message = _update_obj_attrs(
                                reasoning_message,
                                metadata=metadata,
                                usage=usage,
                            )
                            yield reasoning_message.completed()
                            reasoning_message = Message(
                                type=MessageType.REASONING,
                                role="assistant",
                            )
                            index = None

                        json_str = json.dumps(element.get("input"))
                        data_delta_content = DataContent(
                            index=index,
                            data=FunctionCall(
                                call_id=element.get("id"),
                                name=element.get("name"),
                                arguments=json_str,
                            ).model_dump(),
                        )
                        plugin_call_message = Message(
                            type=MessageType.PLUGIN_CALL,
                            role="assistant",
                            content=[data_delta_content],
                        )
                        plugin_call_message = _update_obj_attrs(
                            plugin_call_message,
                            metadata=metadata,
                            usage=usage,
                        )
                        yield plugin_call_message.completed()
                        index = None

                    elif element.get("type") == "tool_result":
                        json_str = json.dumps(
                            element.get("output"),
                            ensure_ascii=False,
                        )
                        data_delta_content = DataContent(
                            index=index,
                            data=FunctionCallOutput(
                                call_id=element.get("id"),
                                name=element.get("name"),
                                output=json_str,
                            ).model_dump(),
                        )
                        plugin_output_message = Message(
                            type=MessageType.PLUGIN_CALL_OUTPUT,
                            role="tool",
                            content=[data_delta_content],
                        )
                        plugin_output_message = _update_obj_attrs(
                            plugin_output_message,
                            metadata=metadata,
                            usage=usage,
                        )
                        yield plugin_output_message.completed()
                        message = Message(
                            type=MessageType.MESSAGE,
                            role="assistant",
                        )
                        should_start_message = True
                        index = None

                    elif element.get("type") == "thinking":
                        reasoning = element.get(
                            "thinking",
                            "",
                        )
                        if reasoning:
                            if should_start_reasoning_message:
                                index = None
                                reasoning_message = _update_obj_attrs(
                                    reasoning_message,
                                    metadata=metadata,
                                    usage=usage,
                                )
                                yield reasoning_message.in_progress()
                                should_start_reasoning_message = False
                            text_delta_content = TextContent(
                                delta=True,
                                index=index,
                                text=reasoning.removeprefix(
                                    local_truncate_reasoning_memory,
                                ),
                            )
                            local_truncate_reasoning_memory = element.get(
                                "thinking",
                                "",
                            )
                            text_delta_content = (
                                reasoning_message.add_delta_content(
                                    new_content=text_delta_content,
                                )
                            )
                            index = text_delta_content.index

                            # Only yield valid text
                            if text_delta_content.text:
                                yield text_delta_content

                            # The last won't happen in the thinking message
                            if last:
                                completed_content = reasoning_message.content[
                                    index
                                ]
                                if completed_content.text:
                                    yield completed_content.completed()

                                reasoning_message = _update_obj_attrs(
                                    reasoning_message,
                                    metadata=metadata,
                                    usage=usage,
                                )
                                yield reasoning_message.completed()
                                reasoning_message = Message(
                                    type=MessageType.REASONING,
                                    role="assistant",
                                )
                                index = None
                    else:
                        if should_start_message:
                            index = None
                            message = _update_obj_attrs(
                                message,
                                metadata=metadata,
                                usage=usage,
                            )
                            yield message.in_progress()
                            should_start_message = False

                        text_delta_content = TextContent(
                            delta=True,
                            index=index,
                            text=f"{element}",
                        )
                        text_delta_content = message.add_delta_content(
                            new_content=text_delta_content,
                        )
                        index = text_delta_content.index
                        yield text_delta_content

    if last_content:
        if should_start_message:
            index = None
            message = _update_obj_attrs(
                message,
                metadata=metadata,
                usage=usage,
            )
            yield message.in_progress()
        text_delta_content = TextContent(
            delta=True,
            index=index,
            text=last_content,
        )
        text_delta_content = message.add_delta_content(
            new_content=text_delta_content,
        )
        yield text_delta_content
        message = _update_obj_attrs(
            message,
            metadata=metadata,
            usage=usage,
        )
        yield message.completed()
