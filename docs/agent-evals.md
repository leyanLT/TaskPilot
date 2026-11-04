# TaskPilot Agent 测试集与提示词版本

本文记录 AI 助手的提示词版本、自动化回归场景与人工真实模型验收。真实模型结果只代表一次样本，不等同于可重复的自动化测试。

## 1. 当前提示词版本

- 版本常量：`PROMPT_VERSION = "2026-11-v5"`
- 定义位置：`backend/app/agent/prompts.py`
- 持久化：每条 assistant 消息将版本写入 `assistant_messages.prompt_version`，历史接口返回。
- 行为变化记录：
  - `v2`：引入持久历史、编辑/删除/批量任务/每日议程工具。
  - `v3`：要求纯文本输出、每日回顾不重复列同一任务。
  - `v4`：没有真实 PendingAction 时禁止声称“请在下方确认后执行”。
  - `v5`：新增项目、子任务、任务拆解、优先级建议、每日规划、活动与报告工具；要求使用后端冲突提示、不得虚构任务/统计，并区分客观事实与 AI 建议。

## 2. 工具目录（17 个）

读工具：`query_tasks`、`query_projects`、`get_task_subtasks`、`get_agenda`、`get_priority_suggestions`、`get_planning_context`、`get_activity_log`、`get_report_facts`。

写工具（只创建待确认操作）：`prepare_create_task`、`prepare_create_tasks`、`prepare_task_breakdown`、`prepare_save_daily_plan`、`prepare_save_report`、`prepare_complete_task`、`prepare_update_task`、`prepare_delete_task`、`prepare_batch_reschedule`。

所有工具只调用 Service，不访问 Repository/Session/数据库；不注册代码、Shell、文件或任意 HTTP 工具。

## 3. 自动化测试集

| 场景 | 期望 | 覆盖位置 |
|---|---|---|
| 查询真实任务/项目/子任务 | 调用读工具，不产生动作；事实来自数据库 | `test_agent.py`、`test_agent_v15.py` |
| AI 创建单任务 | 仅生成 `create_task` 待确认操作 | `test_agent.py`、`test_agent_actions.py` |
| AI 完成单任务 | 唯一匹配才生成 `complete_task`；多个匹配返回候选；未完成子任务时拒绝 | `test_agent.py`、`test_agent_extended.py` |
| AI 修改任务 | 唯一匹配才生成 `update_task`；支持标题/描述/截止时间/优先级/耗时/项目 | `test_agent_extended.py`、`test_agent_v15.py` |
| AI 删除任务 | 确认前不删除；父任务提示子任务数量；重复确认幂等 | `test_agent_extended.py` |
| 批量改期 | 预览目标、上限 20、确认前不改、确认后全部更新、取消无副作用 | `test_agent_extended.py`、`test_agent_actions.py` |
| 批量草稿 | 最多 5 个独立草稿；原子创建；重复确认不重复 | `test_agent_extended.py` |
| AI 任务拆解 | 草稿不写库；含优先级/耗时/截止时间/子任务；确认后父子任务同事务创建；编辑后确认；重复确认不重复 | `test_agent_v15.py` |
| 拆解时间冲突 | 项目已过期、条目晚于项目截止、总耗时超粗略容量时返回 warnings | `test_agent_v15.py` |
| 优先级建议 | 后端确定性评分；理由来自真实因素；不自动改任务 | `test_agent_v15.py` |
| 每日计划 | 读取真实候选；超容量/已完成/重叠被拒绝；确认后保存；重复确认幂等 | `test_agent_v15.py` |
| 报告事实与保存 | 统计由后端计算；确认前不保存；保存后幂等 | `test_agent_v15.py` |
| 每日计划/回顾 | 使用 `get_agenda` 真实数据，不虚构任务 | `test_agent_extended.py`、`test_agent_golden.py` |
| 聊天持久化 / 多轮上下文 | user/assistant 消息、动作状态、prompt_version 刷新/重启后恢复 | `test_agent_extended.py` |
| 歧义选择 | 候选按钮携带 `source_message_id`；使用后清除候选 | `test_agent_extended.py`、前端组件测试 |
| 无卡片确认声明 | 模型没有生成 PendingAction 时，服务端拒绝伪装确认 | `test_agent.py` |
| SSE 只读流式 | 事件顺序 `started → status/token → done`，历史落库 | `test_agent_streaming.py` |
| SSE 写操作安全 | 不输出模型正文 token；只返回确定性 action message | `test_agent_streaming.py` |
| SSE 错误 | 安全 `error` 事件，不泄露堆栈/密钥 | `test_agent_streaming.py` |
| 迁移 | v1.0/v1.2 数据库保留任务，新增表/列，扩展动作约束，完成时间回填 | `test_migrations.py` |

### 运行

```powershell
cd backend
uv run pytest -q

cd ..\frontend
npm run typecheck
npm run lint
npm test
```

当前自动化基线（2026-11-03）：后端 **122 passed**，前端 **54 passed**（10 个测试文件）。

## 4. 真实模型人工冒烟（历史，v4 及更早）

2026-11-03 使用本地隔离数据库和真实 `DEEPSEEK_API_KEY` 实际执行：

1. **流式每日计划**：发送“帮我安排今天，只列三项”，通过 SSE 收到 `status` 和逐 token `token`，最终给出真实逾期/今日任务；没有 Markdown 标记。
2. **修改任务**：生成 `update_task` 待确认操作；写入前任务截止时间不变，浏览器点击「确认修改」后更新。
3. **批量改期**：生成 `batch_reschedule`；确认前未改期，确认后实际更新。
4. **任务拆解（v4 行为）**：生成 3 个 `create_tasks` 独立草稿；确认后创建 3 个任务。
5. **删除**：明确要求时生成 `delete_task`；取消后任务未被删除。
6. **可靠性观察**：一次隐晦的删除请求，模型只说了“请确认”，却没有调用工具。服务端未显示操作按钮、数据未改变；该案例促成“无真实 action 时禁止伪装确认”的 guard。

### V1.5 真实模型状态

2026-11-03 使用真实 `DEEPSEEK_API_KEY`，在隔离 Docker 容器与临时数据库上执行 [`scripts/real_agent_smoke.py`](../scripts/real_agent_smoke.py)：

- **拆解**：`prepare_task_breakdown` → 确认创建 20 个父子任务 → 重复确认不重复。
- **每日计划**：明天 3 小时 → 4 个时间块、180/180 分钟 → 确认保存 → 重复确认不重复。当天 23:47 请求“今天”时，系统按剩余时间正确拒绝，模型如实说明。
- **优先级**：只读回答，引用后端得分与理由，未产生待确认操作。
- **报告**：`prepare_save_report` → 确认保存 1 份日报 → 重复确认同一 `report_id`，正文含统计范围。

真实联调同时暴露并修复了一个缺陷：模型用同一天的 `YYYY-MM-DD` 作为起止日期时，报告工具旧解析报 `end <= start`。`_report_request` 现在会把“同一天/单端日期”归一化为一整天，并有回归测试。该轮结果是一次样本，不替代 Mock 回归；CI 仍不调用真实模型。

## 5. 明确不覆盖的内容

- 不把真实模型调用放入 CI；CI 不依赖 API Key、余额或外网。
- 不评估模型回答质量的主观好坏，只验证工具边界、数据事实、确认边界、流式协议和错误安全。
- 不覆盖多会话、多用户、RAG 或跨设备同步。
- 不覆盖无限层级子任务、跨天自动重排、邮件/短信/系统级推送。
