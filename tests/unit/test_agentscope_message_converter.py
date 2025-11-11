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

    This version checks:
      1. Top-level fields: name, role, invocation_id
      2. All content blocks (deep equality)
      3. Supports both merge=True and merge=False cases
    """
    # Step 1: Convert Agentscope Msg -> Runtime Message
    runtime_messages = agentscope_msg_to_message(msgs)
    assert isinstance(runtime_messages, list)
    assert len(runtime_messages) >= 1

    # Step 2: Convert Runtime Message -> Agentscope Msg
    converted_msgs = message_to_agentscope_msg(runtime_messages, merge=merge)

    # Step 3: Prepare original messages list for comparison
    if isinstance(msgs, Msg):
        original_msgs = [msgs]
    elif isinstance(msgs, list):
        original_msgs = msgs
    else:
        raise TypeError(f"Unsupported msgs type: {type(msgs)}")

    # Step 4: Compare depending on merge flag
    if merge:
        # merge=True returns a single Msg
        assert isinstance(converted_msgs, Msg)

        # Compare top-level fields with the first original Msg
        assert converted_msgs.name == original_msgs[0].name
        assert converted_msgs.role == original_msgs[0].role
        assert converted_msgs.invocation_id == original_msgs[0].invocation_id

        # Compare all content blocks (flatten original content)
        original_blocks = normalize(
            [blk for m in original_msgs for blk in m.content],
        )
        converted_blocks = normalize(converted_msgs.content)
        assert json.dumps(original_blocks, sort_keys=True) == json.dumps(
            converted_blocks,
            sort_keys=True,
        )

    else:
        # merge=False returns a list[Msg]
        assert isinstance(converted_msgs, list)
        assert len(converted_msgs) == len(original_msgs)

        for orig, conv in zip(original_msgs, converted_msgs):
            # Compare top-level fields for each Msg
            assert conv.name == orig.name
            assert conv.role == orig.role
            assert conv.invocation_id == orig.invocation_id

            # Compare content blocks for each Msg
            orig_blocks = normalize(orig.content)
            conv_blocks = normalize(conv.content)
            assert json.dumps(orig_blocks, sort_keys=True) == json.dumps(
                conv_blocks,
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
