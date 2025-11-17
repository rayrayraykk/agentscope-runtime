# -*- coding: utf-8 -*-
import asyncio
import logging
import inspect
import uuid
from contextlib import AsyncExitStack
from typing import Optional, List, AsyncGenerator, Any, Union, Dict

from agentscope_runtime.engine.deployers.utils.service_utils import (
    ServicesConfig,
)
from .deployers import (
    DeployManager,
    LocalDeployManager,
)
from .deployers.adapter.protocol_adapter import ProtocolAdapter
from .schemas.agent_schemas import (
    Event,
    AgentRequest,
    RunStatus,
    AgentResponse,
    SequenceNumberGenerator,
)
from .tracing import TraceType
from .tracing.wrapper import trace
from .tracing.message_util import (
    merge_agent_response,
    get_agent_response_finish_reason,
)


logger = logging.getLogger(__name__)


class Runner:
    def __init__(
        self,
        query_handler,
        init_handler=None,
        shutdown_handler=None,
        framework_type=None,
    ) -> None:
        """
        Initializes a runner as core function.
        """
        self._query_handler = query_handler
        self._init_handler = init_handler
        self._shutdown_handler = shutdown_handler
        self._framework_type = framework_type

        self._deploy_managers = {}
        self._exit_stack = AsyncExitStack()

    async def __aenter__(self) -> "Runner":
        """
        Initializes the runner
        """
        if self._init_handler:
            if inspect.iscoroutinefunction(self._init_handler):
                await self._init_handler(self)
            else:
                self._init_handler(self)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._shutdown_handler:
            try:
                if inspect.iscoroutinefunction(self._shutdown_handler):
                    await self._shutdown_handler(self)
                else:
                    self._shutdown_handler(self)
            except Exception as e:
                # Log and suppress exceptions during shutdown
                logger.error(f"[Runner] Exception in shutdown handler: {e}")

        try:
            await self._exit_stack.aclose()
        except Exception:
            pass

    async def deploy(
        self,
        deploy_manager: DeployManager = LocalDeployManager(),
        endpoint_path: str = "/process",
        stream: bool = True,
        protocol_adapters: Optional[list[ProtocolAdapter]] = None,
        requirements: Optional[Union[str, List[str]]] = None,
        extra_packages: Optional[List[str]] = None,
        base_image: str = "python:3.9-slim",
        environment: Optional[Dict[str, str]] = None,
        runtime_config: Optional[Dict] = None,
        services_config: Optional[Union[ServicesConfig, dict]] = None,
        **kwargs,
    ):
        """
        Deploys the agent as a service.

        Args:
            deploy_manager: Deployment manager to handle service deployment
            endpoint_path: API endpoint path for the processing function
            stream: If start a streaming service
            protocol_adapters: protocol adapters
            requirements: PyPI dependencies
            extra_packages: User code directory/file path
            base_image: Docker base image (for containerized deployment)
            environment: Environment variables dict
            runtime_config: Runtime configuration dict
            services_config: Services configuration dict
            **kwargs: Additional arguments passed to deployment manager
        Returns:
            URL of the deployed service

        Raises:
            RuntimeError: If deployment fails
        """
        deploy_result = await deploy_manager.deploy(
            runner=self,
            endpoint_path=endpoint_path,
            stream=stream,
            protocol_adapters=protocol_adapters,
            requirements=requirements,
            extra_packages=extra_packages,
            base_image=base_image,
            environment=environment,
            runtime_config=runtime_config,
            services_config=services_config,
            **kwargs,
        )

        # TODO: add redis or other persistant method
        self._deploy_managers[deploy_manager.deploy_id] = deploy_result
        return deploy_result

    async def _call_handler_streaming(self, handler, *args, **kwargs):
        """
        Call handler and yield results in streaming fashion, async or sync.
        """
        if asyncio.iscoroutinefunction(handler):
            if inspect.isasyncgenfunction(handler):
                async for item in handler(*args, **kwargs):
                    yield item
            else:
                res = await handler(*args, **kwargs)
                yield res
        else:
            if inspect.isgeneratorfunction(handler):
                for item in handler(*args, **kwargs):
                    yield item
            else:
                res = handler(*args, **kwargs)
                yield res

    @trace(
        TraceType.AGENT_STEP,
        trace_name="agent_step",
        merge_output_func=merge_agent_response,
        get_finish_reason_func=get_agent_response_finish_reason,
    )
    async def stream_query(  # pylint:disable=unused-argument
        self,
        request: Union[AgentRequest, dict],
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Event, None]:
        """
        Streams the agent.
        """
        if isinstance(request, dict):
            request = AgentRequest(**request)

        seq_gen = SequenceNumberGenerator()

        # Initial response
        response = AgentResponse()
        yield seq_gen.yield_with_sequence(response)

        # Set to in-progress status
        response.in_progress()
        yield seq_gen.yield_with_sequence(response)

        # Assign session ID
        request.session_id = request.session_id or str(uuid.uuid4())

        # Assign user ID
        if user_id is None:
            if getattr(request, "user_id", None):
                user_id = request.user_id
            else:
                user_id = ""
        request.user_id = user_id

        async for event in self._call_handler_streaming(
            self._query_handler,
            self,
            request,
        ):
            if (
                event.status == RunStatus.Completed
                and event.object == "message"
            ):
                response.add_new_message(event)
            yield seq_gen.yield_with_sequence(event)

        yield seq_gen.yield_with_sequence(response.completed())

    #  TODO: will be added before 2025/11/30
    # @trace(TraceType.AGENT_STEP)
    # async def query(  # pylint:disable=unused-argument
    #     self,
    #     message: List[dict],
    #     session_id: Optional[str] = None,
    #     **kwargs: Any,
    # ) -> ChatCompletion:
    #     """
    #     Streams the agent.
    #     """
    #     return ...

    async def stop(
        self,
        deploy_id: str,
    ) -> None:
        """
        Stops the agent service.

        Args:
            deploy_id: Optional deploy ID (not used for service shutdown)

        Raises:
            RuntimeError: If stopping fails
        """
        if hasattr(self, "_deploy_manager") and self._deploy_manager:
            await self._deploy_manager[deploy_id].stop()
        else:
            # No deploy manager found, nothing to stop
            pass
