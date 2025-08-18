# -*- coding: utf-8 -*-
from typing import Optional

from ..constant import IMAGE_TAG
from ..registry import SandboxRegistry
from ..enums import SandboxType
from ..box.sandbox import Sandbox

SANDBOX_TYPE = "example"


@SandboxRegistry.register(
    f"agentscope/runtime-sandbox-{SANDBOX_TYPE}:{IMAGE_TAG}",
    sandbox_type=SANDBOX_TYPE,
    security_level="medium",
    timeout=60,
    description="Example sandbox",
)
class ExampleSandbox(Sandbox):
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
            SandboxType(SANDBOX_TYPE),
        )
        raise NotImplementedError(
            "This sandbox is just a template and not implemented yet.",
        )
