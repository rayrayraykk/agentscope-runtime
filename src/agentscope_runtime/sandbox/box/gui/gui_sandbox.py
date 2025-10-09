# -*- coding: utf-8 -*-
from typing import Optional

from ...utils import build_image_uri
from ...registry import SandboxRegistry
from ...enums import SandboxType
from ...box.sandbox import Sandbox


@SandboxRegistry.register(
    build_image_uri("runtime-sandbox-gui"),
    sandbox_type=SandboxType.GUI,
    security_level="high",
    timeout=30,
    description="GUI Sandbox",
)
class GuiSandbox(Sandbox):
    def __init__(
        self,
        sandbox_id: Optional[str] = None,
        timeout: int = 3000,
        base_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ):
        super().__init__(
            sandbox_id,
            timeout,
            base_url,
            bearer_token,
            SandboxType.GUI,
        )

    def run_ipython_cell(self, code: str):
        return self.call_tool("run_ipython_cell", {"code": code})

    def run_shell_command(self, command: str):
        return self.call_tool("run_shell_command", {"command": command})
