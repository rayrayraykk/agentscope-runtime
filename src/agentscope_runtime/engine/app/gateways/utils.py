# -*- coding: utf-8 -*-
"""
Bridge between gateways and AgentApp process: factory to build
ProcessHandler from runner.
"""
from __future__ import annotations

from typing import Any


def make_process_from_runner(runner: Any):
    """
    Use runner.stream_query as the gateway's process.

    Each gateway does: Incoming -> to_agent_request()
        -> process(request) -> send on each completed message.
    process is runner.stream_query, same as AgentApp's /process endpoint.

    Usage::
        process = make_process_from_runner(runner)
        manager = GatewayManager.from_env(process)
    """
    return runner.stream_query
