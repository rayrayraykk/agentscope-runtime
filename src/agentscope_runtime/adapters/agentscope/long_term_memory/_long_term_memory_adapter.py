# -*- coding: utf-8 -*-
# pylint:disable=protected-access,unused-argument
"""AgentScope Long Memory implementation based on MemoryService."""
from typing import Any

from agentscope.memory import LongTermMemoryBase
from agentscope.message import Msg, TextBlock, ThinkingBlock
from agentscope.tool import ToolResponse

from ..message import agentscope_msg_to_message
from ....engine.services.memory_service import MemoryService


class AgentScopeLongTermMemory(LongTermMemoryBase):
    """
    AgentScope Long Memory subclass based on LongTermMemoryBase.

    This class stores messages in an underlying MemoryService instance.

    Args:
        service (MemoryService): The backend memory service.
        user_id (str): The user ID linked to this memory.
        session_id (str): The session ID linked to this memory.
    """

    def __init__(
        self,
        service: MemoryService,
        user_id: str,
        session_id: str,
    ):
        super().__init__()
        self._service = service
        self.user_id = user_id
        self.session_id = session_id

    async def record(
        self,
        msgs: list[Msg | None],
        **kwargs: Any,
    ) -> None:
        """
        Record a list of messages into the memory service.

        Args:
            msgs (list[Msg | None]):
                A list of AgentScope `Msg` objects to store. `None` entries
                in the list will be ignored. If the list is empty, nothing
                will be recorded.
            **kwargs (Any):
                Additional keyword arguments, currently unused but kept for
                compatibility/future extensions.

        Returns:
            None
        """
        if not msgs:
            return

        messages = agentscope_msg_to_message(msgs)
        await self._service.add_memory(
            user_id=self.user_id,
            session_id=self.session_id,
            messages=messages,
        )

    async def retrieve(
        self,
        msg: Msg | list[Msg] | None,
        **kwargs: Any,
    ) -> str:
        """
        Retrieve related memories from the memory service based on a query
        message.

        Args:
            msg (Msg | list[Msg] | None):
                A single message or list of messages representing the
                search query. If `None`, an empty assistant message will
                be used as the query.
            **kwargs (Any):
                Optional search parameters:
                - limit (int): If provided, limits the number of returned
                  results (`top_k` search).

        Returns:
            str:
                A string representation of the retrieved search results.
        """

        if not msg:
            # Build a none message
            msg = [
                Msg(
                    name="assistant",
                    content=[
                        TextBlock(
                            type="text",
                            text="",
                        ),
                    ],
                    role="assistant",
                ),
            ]

        messages = agentscope_msg_to_message(msg)

        search_params = {
            "user_id": self.user_id,
            "messages": messages,
        }

        if "limit" in kwargs:
            search_params["filters"] = {"top_k": kwargs["limit"]}

        results = await self._service.search_memory(**search_params)

        # Convert results to string
        return str(results)

    async def record_to_memory(
        self,
        thinking: str,
        content: list[str],
        **kwargs: Any,
    ) -> ToolResponse:
        """Use this function to record important information that you may
        need later. The target content should be specific and concise, e.g.
        who, when, where, do what, why, how, etc.

        Args:
            thinking (`str`):
                Your thinking and reasoning about what to record
            content (`list[str]`):
                The content to remember, which is a list of strings.
        """
        # Building agentscope msgs
        try:
            thinking_blocks = [
                ThinkingBlock(
                    type="thinking",
                    thinking=thinking,
                ),
            ]

            text_blocks = [
                TextBlock(
                    type="text",
                    text=cnt,
                )
                for cnt in content
            ]

            msgs = [
                Msg(
                    name="assistant",
                    content=thinking_blocks + text_blocks,
                    role="assistant",
                ),
            ]

            await self.record(msgs)

            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Successfully recorded content to memory",
                    ),
                ],
            )
        except Exception as e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error recording content to memory: {str(e)}",
                    ),
                ],
            )

    async def retrieve_from_memory(
        self,
        keywords: list[str],
        **kwargs: Any,
    ) -> ToolResponse:
        """Retrieve the memory based on the given keywords.

        Args:
            keywords (`list[str]`):
                The keywords to search for in the memory, which should be
                specific and concise, e.g. the person's name, the date, the
                location, etc.

        Returns:
            `list[Msg]`:
                A list of messages that match the keywords.
        """
        keyword = "\n".join(keywords)

        try:
            text_blocks = [
                TextBlock(
                    type="text",
                    text=keyword,
                ),
            ]

            msgs = [
                Msg(
                    name="assistant",
                    content=text_blocks,
                    role="assistant",
                ),
            ]

            result = await self.retrieve(
                msgs,
                **kwargs,
            )

            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=result,
                    ),
                ],
            )

        except Exception as e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error retrieving memory: {str(e)}",
                    ),
                ],
            )
