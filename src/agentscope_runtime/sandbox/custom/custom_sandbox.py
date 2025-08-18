# -*- coding: utf-8 -*-
import os

from typing import Optional

from ..constant import IMAGE_TAG
from ..registry import SandboxRegistry
from ..enums import SandboxType
from ..box.sandbox import Sandbox

SANDBOXTYPE = "custom_sandbox"


@SandboxRegistry.register(
    f"agentscope/runtime-sandbox-{SANDBOXTYPE}:{IMAGE_TAG}",
    sandbox_type=SANDBOXTYPE,
    security_level="medium",
    timeout=60,
    description="my sandbox",
    environment={
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", ""),
        "AMAP_MAPS_API_KEY": os.getenv("AMAP_MAPS_API_KEY", ""),
    },
)
class CustomSandbox(Sandbox):
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
            SandboxType(SANDBOXTYPE),
        )
