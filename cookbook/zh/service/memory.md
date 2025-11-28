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

# 记忆服务

记忆服务设计用于从数据库或内存存储中存储和检索长期记忆。 记忆在顶层按用户ID组织，消息列表作为存储在不同位置的基本值。此外，消息可以按会话ID分组。

### 核心功能

#### 添加记忆

 `add_memory` 方法允许您为特定用户存储消息，可选择性地提供会话ID：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.memory import InMemoryMemoryService
from agentscope_runtime.engine.schemas.agent_schemas import Message, TextContent

async def main():
    # 创建并启动记忆服务
    memory_service = InMemoryMemoryService()
    await memory_service.start()

    # 不带会话ID添加记忆
    user_id = "user1"
    messages = [
        Message(
            role="user",
            content=[TextContent(type="text", text="hello world")]
        )
    ]
    await memory_service.add_memory(user_id, messages)

    await memory_service.stop()

await main()
```

#### 搜索记忆

`search_memory`方法基于内容关键词搜索消息：

在内存记忆服务中，实现了一个简单的关键词搜索算法， 基于查询从历史消息中搜索相关内容。 其他复杂的搜索算法可以通过实现或重写类来替换简单方法。

用户可以使用消息作为查询来搜索相关内容。

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.memory import InMemoryMemoryService
from agentscope_runtime.engine.schemas.agent_schemas import Message, TextContent

async def main():
    memory_service = InMemoryMemoryService()
    await memory_service.start()

    user_id = "user1"
    # 先添加一些记忆
    messages = [
        Message(
            role="user",
            content=[TextContent(type="text", text="hello world")]
        )
    ]
    await memory_service.add_memory(user_id, messages)

    # 搜索记忆
    search_query = [
        Message(
            role="user",
            content=[TextContent(type="text", text="hello")]
        )
    ]
    retrieved = await memory_service.search_memory(user_id, search_query)

    await memory_service.stop()

await main()
```

#### 列出记忆

`list_memory`方法提供了一个分页接口来列出记忆，如下所示：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.memory import InMemoryMemoryService
from agentscope_runtime.engine.schemas.agent_schemas import Message, TextContent

async def main():
    memory_service = InMemoryMemoryService()
    await memory_service.start()

    user_id = "user1"
    # 先添加一些记忆
    messages = [
        Message(
            role="user",
            content=[TextContent(type="text", text="hello world")]
        )
    ]
    await memory_service.add_memory(user_id, messages)

    # List memory with pagination
    memory_list = await memory_service.list_memory(
        user_id,
        filters={"page_size": 10, "page_num": 1}
    )

    await memory_service.stop()

await main()
```

#### 删除记忆

用户可以删除特定会话或整个用户的记忆：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.memory import InMemoryMemoryService
from agentscope_runtime.engine.schemas.agent_schemas import Message, TextContent

async def main():
    memory_service = InMemoryMemoryService()
    await memory_service.start()

    user_id = "user1"
    session_id = "session1"

    # 先添加一些记忆
    messages = [
        Message(
            role="user",
            content=[TextContent(type="text", text="hello world")]
        )
    ]
    await memory_service.add_memory(user_id, messages, session_id=session_id)

    # 删除特定会话的记忆
    await memory_service.delete_memory(user_id, session_id)

    # 删除用户的所有记忆
    await memory_service.delete_memory(user_id)

    await memory_service.stop()

await main()
```

### 服务生命周期

#### 服务生命周期管理

记忆服务遵循标准的生命周期模式，可以通过`start()`、`stop()`、`health()` 管理：

```{code-cell}
import asyncio
from agentscope_runtime.engine.services.memory import InMemoryMemoryService

async def main():
    # 创建记忆服务
    memory_service = InMemoryMemoryService()

    # 启动服务
    await memory_service.start()

    # 检查服务健康状态
    is_healthy = await memory_service.health()
    print(f"Service health status: {is_healthy}")

    # 停止服务
    await memory_service.stop()

await main()
```

#### 实现细节

`InMemoryMemoryService` 将数据存储在字典结构中：

+ 顶层：`{user_id: {session_id: [messages]}}`
+ 未指定会话时使用默认会话ID
+ 基于关键词的搜索不区分大小写
+ 消息在每个会话中按时间顺序存储

## 可用的记忆服务

|          记忆类型          | 导入语句                                                     |                             说明                             |
| :------------------------: | ------------------------------------------------------------ | :----------------------------------------------------------: |
|   InMemoryMemoryService    | `from agentscope_runtime.engine.services.memory import InMemoryMemoryService` |                                                              |
|     RedisMemoryService     | `from agentscope_runtime.engine.services.memory import RedisMemoryService` |                                                              |
| ReMe.PersonalMemoryService | `from reme_ai.service.personal_memory_service import PersonalMemoryService` |        [用户指南](https://github.com/modelscope/ReMe)        |
|   ReMe.TaskMemoryService   | `from reme_ai.service.task_memory_service import TaskMemoryService` |        [用户指南](https://github.com/modelscope/ReMe)        |
|     Mem0MemoryService      | `from agentscope_runtime.engine.services.memory import Mem0MemoryService` |                                                              |
|  TablestoreMemoryService   | `from agentscope_runtime.engine.services.memory import TablestoreMemoryService` | 通过[tablestore-for-agent-memory](https://github.com/aliyun/alibabacloud-tablestore-for-agent-memory/blob/main/python/docs/knowledge_store_tutorial.ipynb)开发实现 |

### 描述
- **InMemoryMemoryService**: 一种内存内记忆服务，无持久化存储。
- **RedisMemoryService**: 利用 Redis 实现持久化存储的记忆服务。
- **ReMe.PersonalMemoryService**: ReMe 的个性化记忆服务（原名 MemoryScope），支持生成、检索和共享定制化记忆。依托LLM、VectorStore，构建具备智能、上下文感知与时序感知的完整记忆系统，可无缝配置与部署强大的 AI 智能体。
- **ReMe.TaskMemoryService**: ReMe 的任务导向型记忆服务，帮助您高效管理与调度任务相关记忆，提升任务执行的准确性与效率。依托LLM，支持在多样化任务场景中灵活创建、检索、更新与删除记忆，助您轻松构建并扩展强大的基于智能体的任务系统。
- **Mem0MemoryService**: 基于 mem0 平台的智能记忆服务，提供长期记忆存储与管理功能。支持异步操作，可自动提取、存储和检索对话中的关键信息，为 AI 智能体提供上下文感知的记忆能力。适用于需要持久化记忆的复杂对话场景和智能体应用。(具体可参考 [mem0 平台文档](https://docs.mem0.ai/platform/quickstart))
- **TablestoreMemoryService**: 基于阿里云表格存储的记忆服务（Tablestore 为海量结构化数据提供 Serverless 表存储服务，并为物联网（IoT）场景深度优化提供一站式 IoTstore 解决方案。它适用于海量账单、即时消息（IM）、物联网（IoT）、车联网、风控和推荐等场景中的结构化数据存储，提供海量数据的低成本存储、毫秒级在线数据查询检索和灵活的数据分析能力）, 通过[tablestore-for-agent-memory](https://github.com/aliyun/alibabacloud-tablestore-for-agent-memory/blob/main/python/docs/knowledge_store_tutorial.ipynb)开发实现。使用示例：
```python
from agentscope_runtime.engine.services.memory import TablestoreMemoryService
from agentscope_runtime.engine.services.utils.tablestore_service_utils import create_tablestore_client
from agentscope_runtime.engine.services.memory.tablestore_memory_service import SearchStrategy

# 创建表格存储记忆服务，默认使用全文检索
tablestore_memory_service = TablestoreMemoryService(
    tablestore_client=create_tablestore_client(
        end_point="your_endpoint",
        instance_name="your_instance_name",
        access_key_id="your_access_key_id",
        access_key_secret="your_access_key_secret",
    ),
)

# 创建基于向量检索的表格存储记忆服务，编码模型默认使用DashScopeEmbeddings()
tablestore_memory_service = TablestoreMemoryService(
    tablestore_client=create_tablestore_client(
        end_point="your_endpoint",
        instance_name="your_instance_name",
        access_key_id="your_access_key_id",
        access_key_secret="your_access_key_secret",
    ),
    search_strategy=SearchStrategy.VECTOR,
)
```

```{note}
对于更高级的记忆实现，请考虑扩展 `MemoryService` 抽象基类以支持持久化存储或向量数据库。
```