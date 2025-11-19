# -*- coding: utf-8 -*-
import os

import pytest

from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeChatFormatter
from agentscope.tool import Toolkit, execute_python_code
from agentscope.pipeline import stream_printing_messages
from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    MessageType,
    RunStatus,
)
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.adapters.agentscope.memory import (
    AgentScopeSessionHistoryMemory,
)
from agentscope_runtime.engine.services.agent_state import (
    InMemoryStateService,
)
from agentscope_runtime.engine.services.session_history import (
    InMemorySessionHistoryService,
)


class MyRunner(Runner):
    def __init__(self) -> None:
        super().__init__()
        self._framework_type_value = "agentscope"

    async def query_handler(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Handle agent query.
        """
        session_id = request.session_id
        user_id = request.user_id
        state = await self.state_service.export_state(
            session_id=session_id,
            user_id=user_id,
        )
        toolkit = Toolkit()
        toolkit.register_tool_function(execute_python_code)

        # Modify agent according to the config
        agent = ReActAgent(
            name="Friday",
            model=DashScopeChatModel(
                "qwen-turbo",
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                enable_thinking=True,
                stream=True,
            ),
            sys_prompt="You're a helpful assistant named Friday.",
            toolkit=toolkit,
            memory=AgentScopeSessionHistoryMemory(
                service=self.session_service,
                session_id=session_id,
                user_id=user_id,
            ),
            formatter=DashScopeChatFormatter(),
        )
        if state:
            agent.load_state_dict(state)
        async for msg, last in stream_printing_messages(
            agents=[agent],
            coroutine_task=agent(msgs),
        ):
            yield msg, last
        state = agent.state_dict()
        await self.state_service.save_state(
            user_id=user_id,
            session_id=session_id,
            state=state,
        )

    async def init_handler(self, *args, **kwargs):
        """
        Init handler.
        """
        self.state_service = InMemoryStateService()
        self.session_service = InMemorySessionHistoryService()
        await self.state_service.start()
        await self.session_service.start()

    async def shutdown_handler(self, *args, **kwargs):
        """
        Shutdown handler.
        """
        await self.state_service.stop()
        await self.session_service.stop()


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
                if MessageType.FUNCTION_CALL == message.type:
                    if RunStatus.Completed == message.status:
                        res = message.content
                        print(res)

        print("\n")
