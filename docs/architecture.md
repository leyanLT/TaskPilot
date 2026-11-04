# TaskPilot V1.5 架构设计

- 文档版本：1.5
- 更新日期：2026-11-03
- 升级方式：在 V1.0/V1.2 代码上增量扩展，保留原分层、API 路径、确认机制与 SQLite 数据。

## 1. 设计目标

- 任务、项目、子任务、计划、提醒、报告共用一套业务 Service 与事务边界。
- AI 只通过受控工具访问 Service；所有写入先落为服务端待确认操作，确认后在同一事务执行。
- 统计与时间冲突由确定性代码计算；LLM 只负责自然语言理解、拆解、排序建议解释与报告措辞。
- 不引入 Redis、消息队列、多 Agent、RAG、全局状态库或额外前端框架。
- 单进程 Uvicorn + SQLite 可本地运行，也可 Docker Compose 运行。

## 2. 运行时拓扑

```text
Browser
  │  hash 路由（#/dashboard、#/tasks、#/projects、#/today、#/reports …）
  ▼
React 19 + Vite build ── Nginx（Docker）──┐
  │  dev: Vite proxy :5173               │ /api reverse proxy
  ▼                                       ▼
FastAPI :8000
  ├── TaskService / ProjectService / PlanningService
  ├── NotificationService / ReportService / DashboardService
  ├── PriorityService（确定性评分）
  ├── PendingActionService（确认、编辑后确认、幂等）
  │        ▲
  │        │ tools only
  └── LangGraph 单 Agent ── DeepSeek（OpenAI 兼容） / ReportNarrativeWriter
  ▼
SQLite（UTC 存储；Docker 命名卷 taskpilot-data）
```

本地开发时 Vite 代理 `/api`；Docker 中 Nginx 代理到 `backend:8000`，浏览器只访问一个来源。

## 3. 后端分层

```text
app/
├── api/
│   ├── dependencies.py     Session → 各 Service（统一注入 timezone）
│   └── routes/             tasks / projects / plans / notifications /
│                           activities / reports / insights / assistant / health
├── schemas.py              Pydantic 输入输出、草稿、报告、计划、看板模型
├── services/
│   ├── task_service.py     任务、子任务、完成守卫、活动、事务
│   ├── project_service.py  项目 CRUD、归档恢复、进度、详情
│   ├── planning_service.py 计划校验、容量/重叠、确定性时间块建议
│   ├── notification_service.py 派生提醒、去重、已读状态
│   ├── activity_service.py 追加式活动记录（快照）
│   ├── priority_service.py 确定性优先级评分与理由
│   ├── report_service.py   统计事实、Markdown 模板、AI 建议注入
│   ├── dashboard_service.py 看板聚合
│   ├── pending_action_service.py 确认/取消/过期/幂等/编辑后确认
│   └── assistant_service.py AI 编排、历史、SSE、异常映射
├── repositories/           纯数据访问（task/project/activity/plan/notification/report）
├── models.py               SQLAlchemy ORM
├── agent/
│   ├── graph.py            LangGraph 单 Agent 循环与结果解析
│   ├── tools.py            17 个受限工具
│   ├── prompts.py          带时区/版本的系统提示（2026-11-v5）
│   ├── narrative.py        报告建议段落的单次模型调用（无工具）
│   └── llm.py              DeepSeek ChatOpenAI 配置
├── migrations.py           启动迁移、旧库备份
├── database.py             Engine / Session / UTCDateTime
├── exceptions.py           业务异常 + 统一错误响应
└── main.py                 应用工厂、生命周期、CORS、OpenAPI
```

依赖方向：`API → Service → Repository → Model`；`Agent tools → Service`，工具不得访问 Repository/Session/数据库。

## 4. 数据模型

### 4.1 `projects`

`id`、`name`、`description`、`status`（CHECK planning/active/completed/archived）、`start_date`、`due_date`（CHECK due >= start）、`created_at`、`updated_at`。索引：`(status, created_at)`、`due_date`。

### 4.2 `tasks`（增量扩展）

保留原列；新增：

| 列 | 说明 |
|---|---|
| `project_id` | FK `projects.id`，ON DELETE SET NULL |
| `parent_id` | FK `tasks.id`，ON DELETE CASCADE；CHECK 不自引用 |
| `priority` | CHECK high/medium/low，默认 medium |
| `estimated_minutes` | 可空；CHECK 5–1440 |
| `position` | 子任务顺序，默认 0 |
| `completed_at` | 完成时间；完成时写入、重开时清空 |

新增索引：`project_id`、`(parent_id, position)`、`(status, priority)`、`completed_at`。

层级规则：只有 `parent_id IS NULL` 的任务可拥有子任务；子任务不能再有子任务。子任务项目始终等于父任务项目；父任务项目变化时服务层同步子任务。

### 4.3 `task_activities`

追加式日志：`task_id`/`task_title`、`project_id`/`project_name` 均为快照字符串（不设外键），任务删除后历史仍保留 ID 与标题。`action` 受 CHECK 约束（task_created / task_updated / task_completed / task_reopened / task_deleted / task_project_changed / subtask_created / project_created / project_updated / project_status_changed），并记录 `field`、`old_value`、`new_value`、`summary`、`created_at`。索引：`(project_id, created_at)`、`(task_id, created_at)`、`created_at`。

### 4.4 `daily_plans` / `plan_items`

- `daily_plans`：`plan_date` 唯一，`timezone`、`available_minutes`（CHECK 5–1440）。
- `plan_items`：`plan_id` FK CASCADE、`task_id` FK CASCADE、`start_at`/`end_at`（UTC，CHECK end > start）、`position`、`note`。索引：`(plan_id, position)`、`task_id`。

保存计划采用“删除旧计划 + 新建计划与条目”的替换语义，单事务完成。

### 4.5 `notifications`

`type`（today_todo/due_soon/overdue，CHECK）、`task_id` FK CASCADE、`task_title`、`message`、`due_at`、`dedupe_key`（唯一）、`created_at`、`read_at`。派生数据不进入活动日志。

### 4.6 `reports`

`report_type`（daily/weekly/project，CHECK）、`title`、`period_start`/`period_end`（UTC）、`project_id`（SET NULL）/`project_name` 快照、`content_md`、`facts`（JSON）、`ai_used`、`created_at`、`updated_at`。索引：`(report_type, created_at)`、`project_id`。

### 4.7 `pending_actions`（约束扩展）

`action_type` 扩展为：create_task、create_tasks、complete_task、update_task、delete_task、batch_reschedule、create_task_breakdown、save_daily_plan、save_report。状态机与 v1.0 相同。`result_task_id` 在 v1.5 也用于保存报告结果 ID（通用结果引用），计划结果通过载荷中的 `plan_date` 返回。

## 5. 事务、确认与幂等

### 5.1 任务与项目写入

- Service 默认提交；跨多个写入时使用 `commit=False`，由上层统一提交或回滚。
- 活动记录与业务写入在同一 Session 中 flush；事务回滚不会留下成功记录。
- 子任务完成守卫、项目归档限制、层级校验在 Service 内统一抛出领域异常，映射为 409/422。

### 5.2 AI 确认

```text
BEGIN
  UPDATE pending_actions SET status='processing'
    WHERE id=? AND status='pending' AND expires_at>now
  -- rowcount=0 → 幂等重放 / 冲突 / 过期
  [可选] 校验并替换为编辑后的载荷
  通过 Service 执行业务写入（commit=False）
  UPDATE pending_actions SET status='confirmed', result_task_id=?, resolved_at=?
  COMMIT
```

- 抢占失败时读取当前状态：已确认 → 返回保存结果；已取消 → 409；已过期 → 410。
- 编辑后确认仅允许拆解/计划/报告三类；载荷经 Pydantic 校验，失败返回 409 且不消耗操作（事务回滚恢复 pending）。
- 拆解与计划在一次事务中写入全部父子任务/全部时间块；报告保存与其事实 JSON 同一事务。
- 重复确认拆解：返回已创建任务列表；计划：返回 `plan_date`；报告：返回 `report_id`；不会重复写入。

### 5.3 迁移事务

Alembic 在 SQLite 上使用 batch 模式；迁移连接在 DDL 前关闭外键约束、结束后提交并恢复。旧库升级前复制 `*.db.bak-<timestamp>`。

## 6. Agent 架构

### 6.1 单 Agent

`START → agent →（tool_calls）→ tools → agent → … → END`。模型每轮重新绑定 17 个工具；图有递归上限。模型可注入，测试使用脚本化模型。

### 6.2 工具清单

读工具：`query_tasks`、`query_projects`、`get_task_subtasks`、`get_agenda`、`get_priority_suggestions`、`get_planning_context`、`get_activity_log`、`get_report_facts`。

写工具（只创建待确认操作）：`prepare_create_task`、`prepare_create_tasks`、`prepare_task_breakdown`、`prepare_save_daily_plan`、`prepare_save_report`、`prepare_complete_task`、`prepare_update_task`、`prepare_delete_task`、`prepare_batch_reschedule`。

限制：

- 每轮最多一个待确认操作；出现歧义后禁止自行选择。
- 所有参数经 Pydantic 校验；工具失败返回结构化错误，不泄露堆栈。
- 不注册代码、Shell、文件、任意 HTTP 工具。
- 拆解工具在服务端计算时间冲突 warnings，并由响应返回给模型展示。
- 报告工具在服务端生成完整报告（含确定性统计与 AI 建议），确认前只保存为载荷。

### 6.3 提示词版本

`PROMPT_VERSION = "2026-11-v5"`。新增规则覆盖项目查询、拆解、规划、优先级、活动、报告、冲突提示与“无真实操作不得声称已生成”的守卫。assistant 消息持久化版本号。

### 6.4 报告措辞

`ReportNarrativeWriter` 单独一次模型调用，无工具、无数据库访问。提示词要求只使用后端事实 JSON、不得修改数字；输出“存在的问题/后续建议”两节。异常或未配置时报告仍生成，AI 建议区写明未生成。

## 7. 前端架构

```text
App
├── ConfigProvider / AntApp
└── AppShell（hash 路由、全局新建任务、任务详情抽屉、未读轮询）
    ├── AppHeader
    ├── DashboardPage
    ├── TasksPage（子任务、项目/优先级筛选、建议）
    ├── ProjectsPage / ProjectDetailPage
    ├── AssistantPage → AssistantPanel / ActionDrafts
    ├── TodayPage（PlanTimeline、建议与手动编辑）
    ├── ReportsPage（生成/预览/保存/编辑/导出 + 详情）
    └── NotificationsPage
```

- Pages 组合页面与数据加载；Components 负责展示与交互；Hooks 管理页面级数据操作；Services 负责 DTO ↔ 领域模型映射；不使用全局状态库。
- 路由使用 `window.location.hash`，避免新增路由依赖；导航、通知跳转与报告链接统一通过 hash。
- 所有写操作等待服务端响应后再更新界面；错误显示在表单、卡片或页面错误区。
- 加载、空状态、错误重试在每个页面可用；桌面与 ≤1100px 单列、≤767px 移动布局。
- 视觉延续 Paper Day；新增类集中在 `styles-v15.css`，入口仍为 `index.css`。

## 8. 时间与日期

- 数据库与 API 时间统一 UTC；`UTCDateTime` 在读写边界转换。
- 计划日期、项目开始/截止日期是本地日历日期（DATE），按 `APP_TIMEZONE` 解释。
- 报告统计范围按配置时区计算当天/当周边界，正文展示本地时间范围。
- 优先级建议、通知同步、看板聚合均使用同一时区。
- Web 传输的截止时间/时间块必须带时区，naive datetime 被 Schema 拒绝。

## 9. 迁移与备份

Alembic 版本链：`0001_v1_0` → `0002_ai_upgrade` → `0003_v1_5`。

`prepare_database`：

1. 无版本标记的旧 v1.0 库 → 备份、stamp 基线、升级到 head。
2. 有 `alembic_version` → 备份、升级到 head。
3. 无法识别结构 → 拒绝自动修改。
4. 无表的新库 → 直接升级（不产生空库备份）。

恢复：停止应用后把备份文件覆盖回数据库路径。详见 `docs/migration-v1.5.md`。

## 10. 测试策略

- 后端使用临时 SQLite + TestClient，覆盖任务/项目/子任务/计划/提醒/活动/报告/看板/优先级、确认幂等、编辑后确认、失败回滚、迁移数据保留、Agent 工具与 SSE。
- 前端使用 Vitest + Testing Library + Mock Service，覆盖表单校验、页面加载/空/错误、任务与子任务、项目、计划、报告、提醒、拆解编辑与确认。
- 真实模型调用不进入测试；Agent 行为由脚本化模型覆盖；报告措辞由注入函数 Mock。
- 迁移测试断言列、外键、数据保留、完成时间回填与备份存在。

## 11. 关键取舍与已知限制

1. **SQLite 单文件**：满足单用户零运维；不适合水平扩展。
2. **叶子任务统计**：避免父任务与子任务重复计数；代价是“任务总数”在不同页面口径不同，需在界面与文档说明。
3. **派生提醒即时同步**：读取提醒时生成/清理，不需要调度器；应用关闭时没有后台通知。
4. **服务端确认 + 同事务**：保持 V1.0 安全边界；不引入分布式锁。
5. **单 Agent 无长期记忆**：最近 12 条上下文；不做 RAG、多 Agent。
6. **Markdown 报告**：文本编辑 + 导出；不做富文本/PDF。
7. **无认证**：仅本机单用户。
8. **Hash 路由**：避免新增依赖；不提供服务端 SEO 路由。
