# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import shutil
import traceback
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MCPSessionHandler:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name: str = name
        self.config: dict[str, Any] = config
        self.stdio_context: Any | None = None
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self._exit_stack: AsyncExitStack = AsyncExitStack()

    async def initialize(self) -> None:
        """Initialize the server connection."""
        command = (
            shutil.which("npx")
            if self.config.get("command") == "npx"
            else self.config.get("command")
        )

        try:
            if command:
                server_params = StdioServerParameters(
                    command=command,
                    args=self.config.get("args", []),
                    env={**os.environ, **self.config.get("env", {})},
                    # cwd=self.config.get("cwd"),  # Disabled
                    encoding=self.config.get("encoding", "utf-8"),
                )

                streams = await self._exit_stack.enter_async_context(
                    stdio_client(server_params),
                )
            else:
                if self.config.get("type") in [
                    "streamable_http",
                    "streamableHttp",
                ]:
                    streams = await self._exit_stack.enter_async_context(
                        streamablehttp_client(
                            url=self.config["url"],
                            headers=self.config.get("headers"),
                            timeout=self.config.get("timeout", 30),
                            sse_read_timeout=self.config.get(
                                "sse_read_timeout",
                                60 * 5,
                            ),
                        ),
                    )
                    streams = (streams[0], streams[1])
                else:
                    streams = await self._exit_stack.enter_async_context(
                        sse_client(
                            url=self.config["url"],
                            headers=self.config.get("headers"),
                            timeout=self.config.get("timeout", 30),
                            sse_read_timeout=self.config.get(
                                "sse_read_timeout",
                                60 * 5,
                            ),
                        ),
                    )
            session = await self._exit_stack.enter_async_context(
                ClientSession(*streams),
            )
            await session.initialize()
            self.session = session
        except Exception as e:
            logging.error(f"Error initializing server {self.name}: {e}")
            await self.cleanup()
            raise

    async def list_tools(self) -> list[Any]:
        """List available tools from the server.

        Returns:
            A list of available tools.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        tools_response = await self.session.list_tools()
        tools = [
            tool
            for item in tools_response
            if isinstance(item, tuple) and item[0] == "tools"
            for tool in item[1]
        ]

        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
    ) -> Any:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        attempt = 0

        while attempt < retries:
            try:
                logging.info(f"Executing {tool_name}...")
                result = await self.session.call_tool(tool_name, arguments)
                return result

            except Exception as e:
                attempt += 1
                logging.warning(
                    f"Error executing tool: {e} {traceback.format_exc()}."
                    f" Attempt {attempt} of {retries}.",
                )
                if attempt >= retries:
                    logging.error("Max retries reached. Failing.")
                    raise
                logging.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
        return None

    async def cleanup(self) -> None:
        """Clean up server resources."""
        async with self._cleanup_lock:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                if (
                    "Attempted to exit cancel scope in a different task"
                    in str(e)
                ):
                    pass
            finally:
                self.session = None
                self.stdio_context = None
