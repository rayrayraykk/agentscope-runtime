# -*- coding: utf-8 -*-
import pytest

from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    MessageType,
    RunStatus,
)
from agentscope_runtime.engine.runner import Runner


class MyRunner(Runner):
    def __init__(self) -> None:
        super().__init__()
        self.framework_type = "text"

    async def query_handler(
        self,
        request: AgentRequest = None,
        **kwargs,
    ):
        print(request)
        yield "Hi"
        yield "! My name is Friday"
        yield "."


@pytest.mark.asyncio
async def test_runner():
    from dotenv import load_dotenv

    load_dotenv("../../.env")

    request = AgentRequest.model_validate(
        {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "杭州的天气怎么样？",
                        },
                    ],
                },
                {
                    "type": "function_call",
                    "content": [
                        {
                            "type": "data",
                            "data": {
                                "call_id": "call_eb113ba709d54ab6a4dcbf",
                                "name": "get_current_weather",
                                "arguments": '{"location": "杭州"}',
                            },
                        },
                    ],
                },
                {
                    "type": "function_call_output",
                    "content": [
                        {
                            "type": "data",
                            "data": {
                                "call_id": "call_eb113ba709d54ab6a4dcbf",
                                "output": '{"temperature": 25, "unit": '
                                '"Celsius"}',
                            },
                        },
                    ],
                },
            ],
            "stream": True,
            "session_id": "Test Session",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_weather",
                        "description": "Get the current weather in a "
                        "given "
                        "location",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "The city and state, "
                                    "e.g. San Francisco, CA",
                                },
                            },
                        },
                    },
                },
            ],
        },
    )

    print("\n")
    final_text = ""
    async with MyRunner() as runner:
        async for message in runner.stream_query(
            request=request,
        ):
            print(message.model_dump_json())
            if message.object == "message":
                if MessageType.MESSAGE == message.type:
                    if RunStatus.Completed == message.status:
                        res = message.content
                        print(res)
                        if res and len(res) > 0:
                            final_text = res[0].text
                            print(final_text)
                if MessageType.FUNCTION_CALL == message.type:
                    if RunStatus.Completed == message.status:
                        res = message.content
                        print(res)

        print("\n")
    assert final_text == "Hi! My name is Friday."
