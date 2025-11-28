---
jupytext:
  formats: md:myst
  text_representation:
    extension: .md
    format_name: myst
    format_version: 0.13
    jupytext_version: 1.11.5
kernelspec:
  display_name: Python 3.10
  language: python
  name: python3
---

# 会话历史服务

会话历史服务管理用户的对话会话，提供处理对话历史和消息存储的结构化方式。每个会话包含一个对话的历史记录，并通过其ID唯一标识。

### 会话对象结构

每个会话由具有以下结构的`Session` 对象表示：

```{code-cell}
from agentscope_runtime.engine.schemas.session import Session
from agentscope_runtime.engine.schemas.agent_schemas import Message, TextContent, Role

# 会话对象结构
session_obj = Session(
    id="session_123",
    user_id="user_456",
    messages=[
        Message(role=Role.USER, content=[TextContent(type="text", text="Hello")]),
        Message(role=Role.ASSISTANT, content=[TextContent(type="text", text="Hi there!")]),
    ],
)

print(f"Session ID: {session_obj.id}")
print(f"User ID: {session_obj.user_id}")
print(f"Message count: {len(session_obj.messages)}")
```

### 核心功能

#### 创建会话

 `create_session` 方法为用户创建新的对话会话：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.session_history import InMemorySessionHistoryService

async def main():
    # 创建并启动会话历史服务
    session_history_service = InMemorySessionHistoryService()
    await session_history_service.start()

    # 创建带自动生成ID的会话
    user_id = "test_user"
    session = await session_history_service.create_session(user_id)
    print(f"Created session: {session.id}")
    print(f"User ID: {session.user_id}")
    print(f"Messages count: {len(session.messages)}")

    # 创建带自定义ID的会话
    custom_session = await session_history_service.create_session(
        user_id,
        session_id="my_custom_session_id",
    )
    print(f"Custom session ID: {custom_session.id}")

    await session_history_service.stop()

await main()
```

#### 检索会话

`get_session`方法通过用户ID和会话ID检索特定会话：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.session_history import InMemorySessionHistoryService

async def main():
    session_history_service = InMemorySessionHistoryService()
    await session_history_service.start()

    user_id = "u1"
    # 检索现有会话（在内存实现中如果不存在会自动创建）
    retrieved_session = await session_history_service.get_session(user_id, "s1")
    assert retrieved_session is not None

    await session_history_service.stop()

await main()
```

#### 列出会话

`list_sessions` 方法提供用户的所有会话列表：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.session_history import InMemorySessionHistoryService

async def main():
    session_history_service = InMemorySessionHistoryService()
    await session_history_service.start()

    user_id = "u_list"
    # 创建多个会话
    session1 = await session_history_service.create_session(user_id)
    session2 = await session_history_service.create_session(user_id)

    # 列出所有会话（为了效率不包含消息历史）
    listed_sessions = await session_history_service.list_sessions(user_id)
    assert len(listed_sessions) >= 2

    # 返回的会话不包含消息历史
    for s in listed_sessions:
        assert s.messages == [], "History should be empty in list view"

    await session_history_service.stop()

await main()
```

#### 添加消息

`append_message` 方法向会话历史添加消息，支持多种消息格式：

##### 使用字典格式

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.session_history import InMemorySessionHistoryService
from agentscope_runtime.engine.schemas.agent_schemas import Message, TextContent

async def main():
    session_history_service = InMemorySessionHistoryService()
    await session_history_service.start()

    user_id = "u_append"
    # 创建会话并添加消息（也接受字典格式）
    session = await session_history_service.create_session(user_id)

    # 添加单个消息（Message对象）
    message1 = Message(role="user", content=[TextContent(type="text", text="Hello, world!")])
    await session_history_service.append_message(session, message1)

    # 验证消息已添加
    assert len(session.messages) == 1

    # 一次添加多个消息（混合格式）
    messages3 = [
        {"role": "user", "content": [{"type": "text", "text": "How are you?"}]},
        Message(role="assistant", content=[TextContent(type="text", text="I am fine, thank you.")]),
    ]
    await session_history_service.append_message(session, messages3)

    # Verify all messages were added
    assert len(session.messages) == 3

    await session_history_service.stop()

await main()
```

#### 删除会话

`delete_session`方法删除特定会话：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.session_history import InMemorySessionHistoryService

async def main():
    session_history_service = InMemorySessionHistoryService()
    await session_history_service.start()

    user_id = "test_user"
    # 创建然后删除会话
    session_to_delete = await session_history_service.create_session(user_id)
    session_id = session_to_delete.id

    # 验证会话存在
    assert await session_history_service.get_session(user_id, session_id) is not None

    # 删除会话
    await session_history_service.delete_session(user_id, session_id)

    # 验证会话已删除
    assert await session_history_service.get_session(user_id, session_id) is None

    # 删除不存在的会话不会引发错误
    await session_history_service.delete_session(user_id, "non_existent_id")

    await session_history_service.stop()

await main()
```

### 服务生命周期

会话服务遵循简单的生命周期模式：

```{code-cell}
# 启动服务（对于InMemorySessionHistoryService是可选的）
await session_history_service.start()

# 检查服务健康状态
is_healthy = await session_history_service.health()

# 停止服务（对于InMemorySessionHistoryService是可选的）
await session_history_service.stop()
```

### 实现细节

`InMemorySessionHistoryService` 将数据存储在嵌套字典结构中：

+ 顶层: `{user_id: {session_id: Session}}`
+ 每个Session对象包含id、user_id和messages列表
+ 如果未提供会话ID，会使用UUID自动生成
+ 空的或仅包含空格的会话ID会被替换为自动生成的ID

`TablestoreSessionHistoryService`将数据存储在阿里云表格存储，使用示例：

```python
from agentscope_runtime.engine.services.session_history import TablestoreSessionHistoryService
from agentscope_runtime.engine.services.utils.tablestore_service_utils import create_tablestore_client

tablestore_session_history_service = TablestoreSessionHistoryService(
    tablestore_client=create_tablestore_client(
        end_point="your_endpoint",
        instance_name="your_instance_name",
        access_key_id="your_access_key_id",
        access_key_secret="your_access_key_secret",
    ),
)
```

```{note}
对于生产使用，请考虑通过扩展`SessionHistoryService`抽象基类来实现持久化存储，以支持数据库或文件系统。
```
