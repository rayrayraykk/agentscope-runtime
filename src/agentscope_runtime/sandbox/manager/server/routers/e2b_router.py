# -*- coding: utf-8 -*-
import logging
from datetime import datetime

from fastapi import APIRouter, Request, status

logger = logging.getLogger(__name__)


def get_e2b_router(sandbox_manager):
    router = APIRouter()

    @router.post("/sandboxes", status_code=status.HTTP_201_CREATED)
    async def e2b_create_sandbox(request: Request):
        """
        e2b SDK 新建沙盒接口兼容实现
        返回字段完全匹配 e2b.api.client.models.Sandbox.from_dict 要求
        """
        body = await request.json()
        logger.info(f"[E2B] Create sandbox request body: {body}")

        sandbox_type = body.get("template_id") or "base"
        env_vars = body.get("env_vars") or {}

        # 创建容器
        container_name = sandbox_manager.create(
            sandbox_type=sandbox_type,
            environment=env_vars,
        )
        if not container_name:
            # 返回符合 Error 模型的错误响应
            return {"code": 500, "message": "Failed to create sandbox"}

        info = sandbox_manager.get_info(container_name) or {}
        if not isinstance(info, dict):
            info = {}

        now_iso = datetime.utcnow().isoformat() + "Z"

        return {
            "clientID": "local-client",  # 必填
            "envdVersion": "0.1.0",  # 必填
            "sandboxID": str(container_name),  # 必填
            "templateID": sandbox_type,  # 必填
            "alias": None,
            "domain": str(info.get("base_url") or None),
            "envdAccessToken": str(info.get("runtime_token") or ""),
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "timeout": 3600,
            "state": "RUNNING",
            "metadata": {},
            "allowInternetAccess": True,
        }

    @router.delete("/sandboxes/{sandbox_id}", status_code=status.HTTP_200_OK)
    async def e2b_delete_sandbox(sandbox_id: str):
        """
        e2b SDK 删除沙盒接口兼容实现
        """
        logger.info(f"[E2B] Delete sandbox {sandbox_id}")

        info = sandbox_manager.get_info(sandbox_id)
        if not info:
            # 符合 Error 模型
            return {
                "code": 404,
                "message": f"Sandbox {sandbox_id} not found",
            }

        ok = sandbox_manager.release(sandbox_id)
        if not ok:
            return {
                "code": 500,
                "message": f"Failed to delete sandbox {sandbox_id}",
            }

        # 删除成功时 SDK 不关心返回内容，这里也可以返回简单确认
        return {"code": 200, "message": f"Sandbox {sandbox_id} deleted"}

    return router
