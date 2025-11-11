# -*- coding: utf-8 -*-
import json
import pytest

from agentscope.message import (
    Msg,
    TextBlock,
    ImageBlock,
    AudioBlock,
    URLSource,
    Base64Source,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
)

from agentscope_runtime.adapters.agentscope.message import (
    agentscope_msg_to_message,
    message_to_agentscope_msg,
)


def normalize(obj):
    """
    Recursively converts an object into a standard comparable structure.

    - If the object has a `model_dump()` method (Pydantic v2 models),
      it uses that method for conversion.
    - Lists and tuples are normalized element-wise.
    - Dictionaries are normalized value-wise.
    - All other types are returned as-is.
    """
    if hasattr(obj, "model_dump"):  # Handles Pydantic v2 objects
        return obj.model_dump()
    elif isinstance(obj, (list, tuple)):
        return [normalize(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    else:
        return obj


def _check_round_trip(msgs, merge: bool):
    """
    Performs a round-trip conversion check:
    Agentscope `Msg` -> Runtime Message -> Agentscope `Msg`.

    Steps:
    1. Convert Agentscope `Msg` objects to runtime messages.
    2. Convert back runtime messages into Agentscope `Msg` objects.
    3. Compare original and re-converted message blocks for equality.
    """
    # Step 1: Convert Agentscope Msg -> Runtime Message
    runtime_messages = agentscope_msg_to_message(msgs)
    assert isinstance(runtime_messages, list)
    assert len(runtime_messages) >= 1

    # Step 2: Convert Runtime Message -> Agentscope Msg
    converted_msgs = message_to_agentscope_msg(runtime_messages, merge=merge)

    # Extract original blocks for comparison
    if isinstance(msgs, Msg):
        original_blocks = normalize(msgs.content)
    elif isinstance(msgs, list):
        # Flatten message contents
        original_blocks = normalize([blk for m in msgs for blk in m.content])
    else:
        raise TypeError(f"Unsupported msgs type: {type(msgs)}")

    # Extract converted blocks depending on merge mode
    if merge:
        # merge=True returns a single Msg
        assert isinstance(converted_msgs, Msg)
        converted_blocks = normalize(converted_msgs.content)
    else:
        # merge=False returns list[Msg]
        assert isinstance(converted_msgs, list)
        converted_blocks = normalize(
            [blk for m in converted_msgs for blk in m.content],
        )

    # Compare serialized representations for equality
    assert json.dumps(original_blocks, sort_keys=True) == json.dumps(
        converted_blocks,
        sort_keys=True,
    )


@pytest.mark.parametrize(
    "msgs",
    [
        # Single Msg containing text, images, audio, thinking, tool usage,
        # and tool results
        Msg(
            name="assistant",
            role="assistant",
            invocation_id="12345",
            content=[
                TextBlock(type="text", text="hello world"),
                ImageBlock(
                    type="image",
                    source=URLSource(
                        type="url",
                        url="http://example.com/image.jpg",
                    ),
                ),
                ImageBlock(
                    type="image",
                    source=Base64Source(
                        type="base64",
                        media_type="image/gif",
                        data=(
                            "UklGRgAAAABXQVZFZm10IBAAAAABAAEA"
                            "ESsAACJWAAACABAAZGF0YQAAAAA="
                        ),
                    ),
                ),
                AudioBlock(
                    type="audio",
                    source=URLSource(
                        type="url",
                        url="http://example.com/audio.wav",
                    ),
                ),
                AudioBlock(
                    type="audio",
                    source=Base64Source(
                        type="base64",
                        media_type="audio/wav",
                        data=(
                            "UklGRgAAAABXQVZFZm10IBAAAAABAAEA"
                            "ESsAACJWAAACABAAZGF0YQAAAAA="
                        ),
                    ),
                ),
                ThinkingBlock(type="thinking", thinking="Reasoning..."),
                ToolUseBlock(
                    type="tool_use",
                    id="tool1",
                    name="search_tool",
                    input={"query": "test"},
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="tool1",
                    name="assistant",
                    output=[TextBlock(type="text", text="Tool results.")],
                ),
            ],
        ),
        # Multiple Msgs example
        [
            Msg(
                name="assistant",
                role="assistant",
                invocation_id="id1",
                content=[
                    TextBlock(type="text", text="message one text"),
                    ThinkingBlock(type="thinking", thinking="Reasoning one"),
                ],
            ),
            Msg(
                name="assistant",
                role="assistant",
                invocation_id="id2",
                content=[
                    ImageBlock(
                        type="image",
                        source=URLSource(
                            type="url",
                            url="http://example.com/img2.jpg",
                        ),
                    ),
                    ToolUseBlock(
                        type="tool_use",
                        id="tool2",
                        name="search_tool_2",
                        input={"query": "second message"},
                    ),
                ],
            ),
        ],
    ],
)
@pytest.mark.parametrize("merge", [False, True])
def test_round_trip_messages(msgs, merge):
    """
    Tests that both single and multiple `Msg` objects can be
    converted to runtime messages and back, with `merge` set to
    True and False, while preserving all content blocks.
    """
    _check_round_trip(msgs, merge)
