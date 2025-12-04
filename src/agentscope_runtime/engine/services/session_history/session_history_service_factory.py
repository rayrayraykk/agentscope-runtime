# -*- coding: utf-8 -*-

from typing import Callable, Dict

from ..service_factory import ServiceFactory
from .session_history_service import (
    SessionHistoryService,
    InMemorySessionHistoryService,
)
from .redis_session_history_service import RedisSessionHistoryService

try:
    from .tablestore_session_history_service import (
        TablestoreSessionHistoryService,
    )

    TABLESTORE_AVAILABLE = True
except ImportError:
    TABLESTORE_AVAILABLE = False


class SessionHistoryServiceFactory(ServiceFactory[SessionHistoryService]):
    """
    Factory for SessionHistoryService, supporting both environment variables
    and keyword arguments.

    Usage examples:
        1. Start with only environment variables:
            export SESSION_HISTORY_BACKEND=redis
            export SESSION_HISTORY_REDIS_URL="redis://localhost:6379/5"
            service = await SessionHistoryServiceFactory.create()

        2. Override environment variables with arguments:
            export SESSION_HISTORY_BACKEND=redis
            export SESSION_HISTORY_REDIS_URL="redis://localhost:6379/5"
            service = await SessionHistoryServiceFactory.create(
                redis_url="redis://otherhost:6379/1"
            )

        3. Register a custom backend:
            from my_backend import PostgresSessionHistoryService
            SessionHistoryServiceFactory.register_backend(
                "postgres",
                lambda **kwargs: PostgresSessionHistoryService(
                    dsn=kwargs.get("dsn"),
                    pool_size=int(kwargs.get("pool_size", 10))
                )
            )
            export SESSION_HISTORY_BACKEND=postgres
            export SESSION_HISTORY_POSTGRES_DSN="postgresql://user:pass
                @localhost/db"
            export SESSION_HISTORY_POSTGRES_POOL_SIZE="20"
            service = await SessionHistoryServiceFactory.create()
    """

    _registry: Dict[str, Callable[..., SessionHistoryService]] = {}
    _env_prefix = "SESSION_HISTORY_"
    _default_backend = "in_memory"


# === Default built-in backend registration ===

SessionHistoryServiceFactory.register_backend(
    "in_memory",
    lambda **kwargs: InMemorySessionHistoryService(),
)

SessionHistoryServiceFactory.register_backend(
    "redis",
    lambda **kwargs: RedisSessionHistoryService(
        redis_url=kwargs.get("redis_url", "redis://localhost:6379/0"),
        redis_client=kwargs.get("redis_client"),
    ),
)

if TABLESTORE_AVAILABLE:
    SessionHistoryServiceFactory.register_backend(
        "tablestore",
        lambda **kwargs: TablestoreSessionHistoryService(
            tablestore_client=kwargs["tablestore_client"],  # Must be provided
            session_table_name=kwargs.get(
                "session_table_name",
                "agentscope_runtime_session",
            ),
            message_table_name=kwargs.get(
                "message_table_name",
                "agentscope_runtime_message",
            ),
            session_secondary_index_meta=kwargs.get(
                "session_secondary_index_meta",
            ),
            session_search_index_schema=kwargs.get(
                "session_search_index_schema",
            ),
            message_search_index_schema=kwargs.get(
                "message_search_index_schema",
            ),
            **{
                k: v
                for k, v in kwargs.items()
                if k
                not in [
                    "tablestore_client",
                    "session_table_name",
                    "message_table_name",
                    "session_secondary_index_meta",
                    "session_search_index_schema",
                    "message_search_index_schema",
                ]
            },
        ),
    )
