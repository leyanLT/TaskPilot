# AGENTS.md — TaskPilot 开发规范

本文件面向后续参与 TaskPilot 开发的 AI Agent 与工程师。除非任务明确要求，否则保持现有技术选型与分层。

## 1. 项目定位

TaskPilot V1.0 是单用户、本地优先的 AI 任务管理应用。任务管理不依赖大模型可用性；AI 写操作必须经过服务端待确认操作与用户显式确认。默认不面向公网部署。

当前视觉方向为 **Paper Day / 纸上小帮手**：暖纸底、手写标题、胶带与手绘批注、原创墨线小工人和黄色便签式 AI 面板。样式入口是 `frontend/src/index.css`；新增界面时沿用这套手绘纸张语言，不引入官方品牌标识或另起一套视觉系统。

## 2. 技术栈

- 后端：Python 3.13、uv、FastAPI、SQLAlchemy 2、SQLite、Pydantic、Alembic、LangGraph、LangChain/DeepSeek（OpenAI 兼容接口）、Pytest、Ruff。
- 前端：React 19、TypeScript、Vite、Ant Design 6、Day.js、Vitest、Testing Library、oxlint；SSE 使用原生 fetch/ReadableStream。
- 交付：Git、Docker Compose、GitHub Actions、Markdown 文档。

不要引入 Redis、Celery、消息队列、微服务、RAG、多 Agent、React 全局状态库等非必要组件。

## 3. 目录

```text
backend/app/api/            HTTP 路由与依赖装配
backend/app/schemas.py      Pydantic 请求/响应模型
backend/app/services/       业务规则与事务边界
backend/app/repositories/   数据库访问
backend/app/models.py       SQLAlchemy 模型
backend/app/agent/          LangGraph 工作流、工具、DeepSeek 接入
backend/app/migrations.py   启动迁移与旧库备份
backend/migrations/         Alembic 版本脚本
backend/tests/              后端自动化测试
frontend/src/components/    展示组件
frontend/src/pages/         页面组合
frontend/src/hooks/         客户端状态与数据操作
frontend/src/services/      HTTP/API 映射
frontend/src/types/         TypeScript 领域类型
frontend/src/utils/         时间等纯函数
frontend/src/test/          测试工具
docs/                       需求、架构与交付说明
```

## 4. 常用命令

```powershell
# 后端（在 backend/ 下）
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
uv run alembic current   # 启动后查看 schema 版本

# 前端（在 frontend/ 下）
npm ci
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
```

环境变量统一从仓库根目录 `.env` 加载。不要把真实密钥写入代码、测试、文档或日志。

## 5. 分层与业务约束

1. API 路由只负责 HTTP 协议、输入模型和调用 Service；不在路由中写数据库查询或复杂业务规则。
2. 所有任务写操作必须经过 `TaskService`；Agent 工具只能调用 Service，不能访问 Repository、Session 或数据库。
3. Repository 只做持久化访问，不承载业务规则。
4. 事务边界在 Service。跨多个写操作时使用 `commit=False` 并由上层统一提交或回滚。
5. AI 创建、编辑、删除、完成和批量操作必须先写入服务端 `PendingAction`，确认端点保持幂等；不得直接调用 TaskService 的写方法。
6. 对话历史持久化仅用于短期上下文（最近 12 条），不实现语义长期记忆；assistant 消息必须记录 `prompt_version`。
7. SSE 只允许只读回复转发模型 token；本轮出现 `prepare_*` 后必须抑制模型正文，只返回确定性确认卡片。
8. 时区规则：数据库与 API 时间统一为 UTC；Agent 按 `APP_TIMEZONE` 解释用户相对日期。Web 传输的截止时间必须带时区（API 拒绝 naive datetime）。
9. 错误响应统一为 `{"error": {"code", "message", "details?"}}`；不得向客户端泄露异常栈、SQL、密钥或上游内部响应。
10. 手动任务管理与 AI 必须解耦。无 API Key、模型超时或 Agent 异常时，任务 CRUD 仍需正常工作。
11. Schema 变更必须通过 Alembic；旧 SQLite 自动升级前必须保留备份，不可直接删除用户数据库。

## 6. 测试规范

- 外部 DeepSeek 调用必须 Mock；测试不得依赖真实 API Key 或余额。
- 测试使用临时 SQLite 数据库，测试之间隔离。
- 新增或修改业务规则时同步补充/更新回归测试，不得删除测试来掩盖失败。
- 不得虚报测试结果。Mock 测试不等于真实模型验证；无法执行的检查须明确说明。
- 前端核心交互使用 Testing Library 做行为断言，不依赖实现细节或真实网络。
- 提交前至少执行：后端 pytest、Ruff check；前端 test、lint、typecheck、build。

## 7. Git 与文件安全

- 开始前检查 `git status`，保留用户已有修改，不修改无关文件。
- 不自动提交、推送、改写历史或执行破坏性 Git 操作；需要时先征得同意。
- 不删除用户数据或数据库文件；本地 `data/`、`.env`、密钥文件均不可提交。
- 依赖使用 `uv add/remove` 与 `npm install/uninstall` 管理；不要手动编辑 `uv.lock` 或 `package-lock.json`。
- 不在日志或响应中输出密钥。Docker/CI 配置不得硬编码密钥。

## 8. 交付检查清单

- [ ] 后端 CRUD、验证、事务回滚与持久化正常
- [ ] Agent 查询真实数据，写操作需确认且幂等
- [ ] AI 故障时手动模式正常
- [ ] 后端与前端测试通过，静态检查通过，前端可构建
- [ ] Docker Compose 可启动，SQLite 数据卷持久化
- [ ] README 的启动、配置与测试命令与实际一致
- [ ] 未提交 `.env`、`.db` 或密钥
