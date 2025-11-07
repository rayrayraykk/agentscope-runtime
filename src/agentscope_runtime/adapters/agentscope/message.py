# -*- coding: utf-8 -*-
# pylint:disable=too-many-branches,too-many-statements
# TODO: support file block
import json

from typing import Union, List
from urllib.parse import urlparse

from agentscope.message import (
    Msg,
    ToolUseBlock,
    ToolResultBlock,
    TextBlock,
    ThinkingBlock,
    ImageBlock,
    AudioBlock,
    URLSource,
    Base64Source,
)

from ...engine.schemas.agent_schemas import (
    Message,
    FunctionCall,
    FunctionCallOutput,
    MessageType,
)
from ...engine.helpers.agent_api_builder import ResponseBuilder


def agentscope_msg_to_message(
    messages: Union[Msg, List[Msg]],
) -> List[Message]:
    """
    Convert AgentScope Msg(s) into one or more runtime Message objects

    Args:
        messages: AgentScope message(s) from streaming.

    Returns:
        List[Message]: One or more constructed runtime Message objects.
    """
    if isinstance(messages, Msg):
        msgs = [messages]
    elif isinstance(messages, list):
        msgs = messages
    else:
        raise TypeError(f"Expected Msg or list[Msg], got {type(messages)}")

    results: List[Message] = []

    for msg in msgs:
        role = msg.role or "assistant"

        if isinstance(msg.content, str):
            # Only text
            rb = ResponseBuilder()
            mb = rb.create_message_builder(
                role=role,
                message_type=MessageType.MESSAGE,
            )
            cb = mb.create_content_builder(content_type="text")
            cb.set_text(msg.content)
            cb.complete()
            mb.complete()
            results.append(mb.get_message_data())
            continue

        # msg.content is a list of blocks
        # We group blocks by high-level message type
        current_mb = None
        current_type = None

        for block in msg.content:
            if isinstance(block, dict):
                btype = block.get("type", "text")
            else:
                continue

            if btype == "text":
                # Create/continue MESSAGE type
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(block.get("text", ""))
                cb.complete()

            elif btype == "thinking":
                # Create/continue REASONING type
                if current_type != MessageType.REASONING:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.REASONING,
                    )
                    current_type = MessageType.REASONING
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(block.get("thinking", ""))
                cb.complete()

            elif btype == "tool_use":
                # Always start a new PLUGIN_CALL message
                if current_mb:
                    current_mb.complete()
                    results.append(current_mb.get_message_data())
                rb = ResponseBuilder()
                current_mb = rb.create_message_builder(
                    role=role,
                    message_type=MessageType.PLUGIN_CALL,
                )
                current_type = MessageType.PLUGIN_CALL
                cb = current_mb.create_content_builder(content_type="data")
                call_data = FunctionCall(
                    call_id=block.get("id"),
                    name=block.get("name"),
                    arguments=json.dumps(block.get("input")),
                ).model_dump()
                cb.set_data(call_data)
                cb.complete()

            elif btype == "tool_result":
                # Always start a new PLUGIN_CALL_OUTPUT message
                if current_mb:
                    current_mb.complete()
                    results.append(current_mb.get_message_data())
                rb = ResponseBuilder()
                current_mb = rb.create_message_builder(
                    role=role,
                    message_type=MessageType.PLUGIN_CALL_OUTPUT,
                )
                current_type = MessageType.PLUGIN_CALL_OUTPUT
                cb = current_mb.create_content_builder(content_type="data")
                output_data = FunctionCallOutput(
                    call_id=block.get("id"),
                    output=json.dumps(block.get("output")),
                ).model_dump()
                cb.set_data(output_data)
                cb.complete()

            elif btype == "image":
                # Create/continue MESSAGE type with image
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="image")

                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get("type") == "url"
                ):
                    cb.set_image_url(block.get("source", {}).get("url"))

                cb.complete()

            elif btype == "audio":
                # Create/continue MESSAGE type with audio
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="audio")
                # URLSource runtime check (dict with type == "url")
                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get(
                        "type",
                    )
                    == "url"
                ):
                    cb.content.data = block.get("source", {}).get("url")

                # Base64Source runtime check (dict with type == "base64")
                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get(
                        "type",
                    )
                    == "base64"
                ):
                    cb.content.data = block.get("source", {}).get("data")
                cb.complete()

            else:
                # Fallback to MESSAGE type
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(str(block))
                cb.complete()

        # finalize last open message builder
        if current_mb:
            current_mb.complete()
            results.append(current_mb.get_message_data())

    return results


def message_to_agentscope_msg(
    messages: Union[Message, List[Message]],
    merge: bool = False,
) -> Union[Msg, List[Msg]]:
    """
    Convert AgentScope runtime Message(s) to AgentScope Msg(s).

    Args:
        messages: A single AgentScope runtime Message or list of Messages.
        merge: If True and messages is a list, merge all contents into one Msg.

    Returns:
        A single Msg object or a list of Msg objects.
    """

    def _convert_one(message: Message) -> Msg:
        # Normalize role
        if message.role == "tool":
            role_label = "system"  # AgentScope do not support tool as role
        else:
            role_label = message.role

        result = {
            "name": getattr(message, "name", message.role),
            "role": role_label,
            "invocation_id": getattr(message, "id", None),
        }

        if message.type in (
            MessageType.PLUGIN_CALL,
            MessageType.FUNCTION_CALL,
        ):
            # convert PLUGIN_CALL, FUNCTION_CALL to ToolUseBlock
            result["content"] = [
                ToolUseBlock(
                    type="tool_use",
                    id=message.content[0].data["call_id"],
                    name=message.content[0].data["name"],
                    input=json.loads(message.content[0].data["arguments"]),
                ),
            ]
        elif message.type in (
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.FUNCTION_CALL_OUTPUT,
        ):
            # convert PLUGIN_CALL_OUTPUT, FUNCTION_CALL_OUTPUT to
            # ToolResultBlock
            result["content"] = [
                ToolResultBlock(
                    type="tool_result",
                    id=message.content[0].data["call_id"],
                    name=message.role,  # TODO: match id of ToolUseBlock
                    output=json.loads(message.content[0].data["output"]),
                ),
            ]
        elif message.type in (MessageType.REASONING,):
            result["content"] = [
                ThinkingBlock(
                    type="thinking",
                    thinking=message.content[0].text,
                ),
            ]
        else:
            type_mapping = {
                "text": (TextBlock, "text", None),
                "image": (ImageBlock, "image_url", True),
                "audio": (AudioBlock, "data", None),
                # "video": (VideoBlock, "video_url", True),
                # TODO: support video
            }

            msg_content = []
            for cnt in message.content:
                cnt_type = cnt.type or "text"

                if cnt_type not in type_mapping:
                    raise ValueError(f"Unsupported message type: {cnt_type}")

                block_cls, attr_name, is_url = type_mapping[cnt_type]
                value = getattr(cnt, attr_name)

                if cnt_type == "audio":
                    parsed_url = urlparse(value)
                    is_url = all([parsed_url.scheme, parsed_url.netloc])

                if is_url:
                    url_source = URLSource(type="url", url=value)
                    msg_content.append(
                        block_cls(type=cnt_type, source=url_source),
                    )
                else:
                    if cnt_type == "audio":
                        audio_format = getattr(cnt, "format")
                        base64_source = Base64Source(
                            type="base64",
                            media_type=audio_format,
                            data=value,
                        )
                        msg_content.append(
                            block_cls(type=cnt_type, source=base64_source),
                        )
                    else:
                        msg_content.append(
                            block_cls(type=cnt_type, text=value),
                        )

            result["content"] = msg_content

        return Msg(**result)

    # Handle single or list input
    if isinstance(messages, Message):
        return _convert_one(messages)
    elif isinstance(messages, list):
        converted_list = [_convert_one(m) for m in messages]
        if merge:
            merged_content = []
            name = None
            role = None
            invocation_id = None

            for i, msg in enumerate(converted_list):
                if i == 0:
                    name = msg.name
                    role = msg.role
                    invocation_id = msg.invocation_id
                merged_content.extend(msg.content)

            return Msg(
                name=name,
                role=role,
                invocation_id=invocation_id,
                content=merged_content,
            )
        return converted_list
    else:
        raise TypeError(
            f"Expected Message or list[Message], got {type(messages)}",
        )
