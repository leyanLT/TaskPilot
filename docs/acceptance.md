# TaskPilot V1.0 / v1.2 / V1.5 验收报告

- 验收日期：2026-11-03
- 验收环境：Windows、Python 3.13.18、uv 0.13.7、Node 24.18.0、Docker 29.9.2、Docker Compose v5.6.1、Headless Edge
- 数据库：SQLite；测试使用临时隔离数据库，Docker 使用命名卷 `taskpilot-data`

> 本报告只记录实际执行过的检查。自动化测试中的外部模型调用由 Mock/脚本化模型覆盖。2026-11-03 使用真实 DeepSeek 完成了查询、创建草稿、取消、完成确认、流式回复、编辑/删除/批量改期/批量草稿与每日回顾联调；真实模型输出具有非确定性，不能替代回归测试。V1.5 的增量验收记录见文末第 7 节。

## 1. 结论概览

| 类别 | 状态 |
|---|---|
| 手动任务管理（创建/查询/编辑/状态/删除） | ✅ 已实现并通过自动化与实际端到端验证 |
| 前端页面与交互 | ✅ 已实现并通过组件测试、构建和浏览器端到端验证 |
| AI 查询 / 创建草稿 / 完成准备 | ✅ 已实现；通过自动化测试，并完成真实 DeepSeek 联调 |
| AI 持久对话 / 多轮上下文 / SSE 流式 | ✅ 已实现并通过自动化、浏览器和真实 DeepSeek 联调 |
| AI 编辑 / 删除 / 批量创建 / 批量改期 | ✅ 已实现并通过确认、取消、幂等、回滚测试和真实模型联调 |
| AI 人工确认、取消、幂等、过期 | ✅ 已实现并通过 API/服务/真实 HTTP 验证 |
| 模型异常处理与手动模式降级 | ✅ 已实现并通过 Mock 测试 |
| 真实 DeepSeek API 调用 | ✅ 已使用真实 Key 完成查询、流式、编辑/删除/批量/每日回顾联调 |
| SQLite 自动迁移与旧数据保留 | ✅ 已通过迁移测试，并在 Docker 旧数据卷实际升级；升级前备份生成 |
| GitHub Actions 在 GitHub 托管环境执行 | ⚠️ 尚未验证；本地等价命令通过，工作流 YAML 已解析检查 |
| Docker Compose 启动与数据持久化 | ✅ 已实际构建、启动、重启并验证数据保留 |
| 移动端布局 | ✅ 已通过 390px 视口 Emulation 与截图检查，无横向溢出；未测试实体设备 |

计划中的 F01–F06 与 AI 助手 v1.2 扩展均已完成，没有功能阻塞项。尚未验证的仅为 GitHub 托管 CI 和实体移动设备。

## 2. 实际执行的检查与结果

### 2.1 后端

```powershell
cd backend
uv run ruff format --check app tests
uv run ruff check app tests
uv run pytest --cov=app --cov-report=term-missing -q
```

结果：

- Ruff format：**38 files already formatted**
- Ruff lint：`All checks passed!`
- Pytest：**71 passed**
- 覆盖率：**83%**（`app` 整体，1923 statements / 321 missed）

覆盖的功能与异常路径包括：

- 任务创建、字段默认值、标题/描述边界、时区校验、未知字段拒绝。
- 列表、状态筛选、创建时间/截止时间排序、无截止时间置后。
- 编辑、可选字段清空、目标任务不存在。
- 状态双向切换与重复操作。
- 删除成功、二次删除 404。
- 重启应用后 SQLite 数据持久化。
- 数据库提交失败时回滚且错误响应不泄露内部信息。
- 统一错误结构与 404/422 状态码。
- AI 查询工具读取真实数据库。
- AI 创建草稿不写任务、非法草稿不生成动作。
- 完成操作唯一匹配/多匹配、候选选择、不在 Agent 内写入。
- 待确认操作确认、取消、重复确认只写一次、取消无副作用、过期。
- 模型超时、鉴权失败、非法输出、未知异常映射。
- 未配置 API Key 时 AI 返回 503 且手动 CRUD 正常。
- 编辑/删除确认、取消、幂等与歧义保护；批量改期范围、上限、原子回滚；批量草稿原子创建。
- 对话持久化、重启恢复、多轮上下文、历史 action 状态水合和候选消费。
- SSE 事件顺序、只读 token 转发、写操作 token 抑制、安全 error 事件。
- 无真实 action 时模型伪造“待确认”文案会被服务端拦截。
- Alembic 空库、v1.0 旧库 stamp/升级、任务保留、备份与重复启动不重复备份。

### 2.2 前端

```powershell
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

结果：

- oxlint：**0 warnings, 0 errors**
- TypeScript：通过
- Vitest + Testing Library：**35 passed**（5 个测试文件）
- Vite 生产构建：成功
- 构建仅出现 Vite 的非阻断提示：单个 JS chunk 约 780 kB（gzip 约 253 kB）。不影响构建与运行。

组件测试覆盖：

- 创建任务表单必填、全空格标题、去空格提交、取消无提交、编辑回填。
- 任务列表状态、截止时间、逾期标识、完成态不误判逾期。
- 状态切换、编辑、删除二次确认与取消确认。
- 任务页真实 API 数据加载、创建后即时显示、删除、筛选、按截止时间排序、加载失败重试。
- API 创建失败时保留表单并展示错误。
- AI 消息发送、历史加载、流式 token、done 替换、错误中止、草稿展示、确认执行、取消不修改任务、歧义候选选择、加载状态。
- 修改/删除/批量改期/批量草稿动作卡片渲染；确认按钮按动作类型变化；已确认修改不重复展示旧值。
- SSE 分片解析与非流式错误响应；历史加载失败重试。

### 2.3 真实 HTTP 确认流程

在运行中的 API 上执行了以下集成检查：

- 通过服务层创建服务端待确认创建操作。
- 调用 `POST /api/assistant/confirm` 确认。
- 再次确认同一操作，返回同一任务 ID，数据库只增加一条任务。
- 取消另一个待确认操作，未创建任务。
- 结果：`first_status=confirmed`、`same_result=true`、`created_task_count=1`、`cancel_status=cancelled`、`cancelled_task_count=0`。

### 2.4 Docker Compose

实际执行：

```powershell
docker compose build
docker compose up -d
docker compose down
docker compose up -d
```

结果：

- 后端镜像与前端镜像构建成功。
- 后端容器健康检查通过，前端容器健康检查通过。
- `GET http://127.0.0.1:3000/api/health` 返回 `{"status":"ok","version":"1.0.0","agent_configured":true}`（配置真实 Key 后的最终状态）。
- Nginx 正确提供 SPA 页面、客户端路由回退、`/api` 反向代理与 `/healthz`。
- 后端进程以非 root 用户运行：`uid=10001(appuser)`。
- SQLite 文件位于 `/data/taskpilot.db`，权限归属 `appuser`。
- 完整执行 `docker compose down` 后再次 `up -d`，此前通过 API 创建的任务仍然存在，验证了命名卷持久化。
- Nginx 返回安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: no-referrer`。
- 镜像大小（本机）：后端约 455 MB，前端约 74.9 MB。

环境网络说明：当前机器的 Docker Hub 直连不可达。为完成实际构建验证，使用了本机可获得的标准官方镜像镜像副本并打回 `node:24-alpine`、`python:3.13-slim`、`nginx:1.27-alpine` 标签；项目 Dockerfile 本身仍引用标准官方镜像名称，不使用任何私有或定制镜像仓库。

### 2.5 浏览器端到端验收（Docker 生产构建）

使用 Headless Edge + Chrome DevTools Protocol，对最终重建后的 Docker 生产页面执行：

1. 读取已有 API 任务并显示。
2. 点击“新建任务”，填写标题和描述，提交。
3. 验证新任务出现在列表。
4. 刷新浏览器，新任务仍存在（真实后端持久化）。
5. 勾选完成，验证状态变化。
6. 打开编辑弹窗，修改标题并保存。
7. 发送 AI 消息；未配置 Key 时界面显示错误，手动任务页面继续工作。
8. 点击删除，二次确认后任务消失。
9. 检查桌面视口无横向溢出。

结果：全部步骤通过；验收完成后已清理测试任务，Docker 卷保留空数据库结构，前后端容器保持健康运行。

另以 CDP 设置 390 × 844 移动视口检查：`innerWidth=390`、`documentScrollWidth=390`，无横向溢出；界面截图已归档到 `docs/assets/`。

### 2.6 真实 DeepSeek 联调

在配置真实 `DEEPSEEK_API_KEY` 后，通过 Docker 生产构建的 Nginx API 入口完成：

1. **查询**：创建真实任务后询问“我还有哪些任务没有完成？请告诉我任务标题。”
   - 模型调用查询工具，返回真实数据库中的任务标题、待完成数量和截止时间，没有待确认操作；测试后清理任务。
2. **创建草稿**：发送“明天下午三点完成实验报告。”
   - 生成待确认操作，标题为“完成实验报告”，截止时间为 `2026-11-04T07:00:00Z`（Asia/Shanghai 2026-11-04 15:00）。
   - 确认前任务数量保持 0；取消操作后仍为 0。
3. **完成操作**：准备一个待完成任务，发送“把任务「…」标记为已完成。”
   - 生成待确认完成操作，确认前任务仍为 pending。
   - 确认后任务状态变为 completed；再次确认同一操作返回同一任务 ID，验证真实链路下的幂等。
   - 测试任务随后清理。

结论：真实 DeepSeek API、工具调用、时区解析、确认边界和幂等链路均已跑通。该结果是一次人工联调，不改变“自动化测试全部使用 Mock、不消耗真实余额”的原则。

### 2.7 Paper Day 视觉重构

界面对齐已选定的 **Paper Day / 纸上小帮手** 方向完成重构，业务 API 与 Agent 确认规则未改动。

- 视觉：暖纸色、手写标题、胶带、手绘边框、原创墨线微工作者、便签式 AI 面板与纸张式弹窗。
- 交互：保留新建、编辑、状态切换、删除二次确认、状态筛选、创建时间/截止时间排序、空状态、加载与错误重试、AI 确认/取消、候选选择。
- 使用 `oil_ui_shoot` 在 1440 × 1100、1024 × 900、390 × 844 三个视口实际截图检查：无控制台错误、无横向溢出，可读性与对比度检查通过。移动端新建弹窗也完成截图检查。
- 在隔离预览数据库上，通过真实浏览器完成“新建任务 → 列表即时更新 → 编辑标题 → 后端持久化”的交互验证；验收临时任务随后删除。
- 真实 DeepSeek 生成的待确认卡片已在重构后的 AI 便签中实际渲染并截图。
- 最终 Docker 前端镜像已重建并重新部署；在 `http://127.0.0.1:3000` 实际加载，无控制台错误、无横向溢出，API 健康检查正常。
- 最新界面截图：`docs/assets/ui-desktop.png`、`docs/assets/ui-mobile.png`。

### 2.8 AI 助手 v1.2 实机验收

- **持久对话**：Vite 预览与 Docker 生产页面均能从 `/api/assistant/history` 恢复历史；刷新/应用重建后仍可恢复。后端测试覆盖两次独立 app 启动读取同一 SQLite。
- **SSE 浏览器链路**：在真实浏览器中通过页面输入发送消息，观察到状态 `正在读取真实任务…`、token 更新和最终消息替换；输入框在流中禁用，完成后恢复。真实 DeepSeek 首个 token 在约 0.9–2.7 秒出现，非一次性整段返回。
- **写操作安全**：真实模型的编辑请求只产生 `update_task`，流式 token 数为 0；没有 action 时模型伪造“请在下方确认后执行”的文案被服务端 guard 拦截。确认前数据库中任务字段不变。
- **真实模型扩展动作**：
  - 修改任务：生成 `update_task`，浏览器点击「确认修改」后截止时间从 18:00 更新到 20:00。
  - 删除任务：明确请求时生成 `delete_task`，取消后任务保留。
  - 批量改期：生成 `batch_reschedule`，浏览器点击「确认改期」后目标任务实际更新。
  - 任务拆解：生成 3 个 `create_tasks` 草稿，浏览器确认后原子创建。
  - 每日计划/回顾：调用 `get_agenda` 使用真实任务，输出无 Markdown 标记。
- **生产 Nginx SSE**：通过 `http://127.0.0.1:3000/api/assistant/messages/stream` 实测，`started` 在 21ms 到达，首 token 2730ms，`done` 2816ms；共接收 84 个 token 事件。证明 Nginx 未把响应缓冲到结束。测试只读消息随后按 ID 从 `assistant_messages` 清理，任务数据未改。
- **Docker 迁移**：旧数据卷启动时打印 Alembic stamp/upgrade 日志；原有 3 个任务全部保留。升级前备份由服务端自动写入 `/data`。工作区后续存在 `0003_v1_5` 迁移（并行变更），本次实际迁移到当前 head，本报告不把这部分视为本次 AI 功能验收。
- **最终前端检查**：1440×1100 与 390×656 截图；`scrollWidth == innerWidth`，无横向溢出；修改卡片展示旧/新截止时间，移动端完整显示确认卡片。
- 最新截图：`docs/assets/ui-desktop.png`、`docs/assets/ui-mobile.png`。

## 3. 已实现但尚未验证

### 3.1 GitHub Actions 托管执行

- `.github/workflows/ci.yml` 已编写，并用 YAML 解析器检查语法。
- 本地执行的 Ruff、Pytest、oxlint、TypeScript、Vitest、Vite build 全部通过，与 CI 命令一致。
- 由于当前没有 GitHub 仓库/runner 执行环境，**未实际触发 Actions**。首次推送后需以 GitHub 运行结果为准。

### 3.2 移动端实体设备

- 390px 与桌面视口通过无头浏览器布局检查。
- 未在真实 iOS/Android 设备上做触控和浏览器差异测试。

## 4. 未完成或阻塞

当前 V1.0 范围内没有未完成的功能项。

- GitHub Actions 远程运行需要 GitHub 托管环境。
- 本机 Docker 构建需要可访问镜像仓库；本次通过本地镜像副本完成验证。

## 5. 安全与配置核查

- `.env`、`.env.*`（保留 `.env.example`）、`*.db`、SQLite WAL、`.venv`、`node_modules`、`dist`、`.tools` 均被 Git 忽略。
- 真实 API Key 仅保存在被忽略的 `.env`；`.env.example` 保持空占位符，并被扫描确认不含密钥。
- 测试响应中未出现 API Key、SQL 明细、异常堆栈；模型错误响应使用统一错误结构。
- 未在代码或配置中硬编码真实密钥；仓库非忽略文本文件中未扫描到密钥格式。
- Docker 端口仅绑定 `127.0.0.1:8000` 和 `127.0.0.1:3000`。
- 未执行自动 Git 提交或推送；代码仍在工作区等待用户审查。

## 6. 已知限制

- 无认证与多租户，禁止直接公网部署。
- 仅维护一个持久对话，不提供多会话或云同步。
- 不实现语义长期记忆、RAG、多 Agent；任务历史上下文最近 12 条。
- 不建立父子子任务；任务拆解生成独立任务草稿。
- 写操作轮次不逐 token 输出模型正文；只有只读回复进行 token 流式输出。
- 批量改期上限 20 条、批量草稿上限 5 条。
- 前端未做路由级拆包，构建存在非阻断的 chunk 体积提示。
- 无后台清理过期 pending action 的任务，过期在读取历史或确认时标记。
- 真实模型输出受模型非确定性影响；真实 GitHub CI 状态需在托管环境补验。
- 当前配置的真实 API Key 已在配置过程中出现在用户提供的截图中，建议立即在 DeepSeek 控制台轮换；轮换后同步更新 `.env` 并重建后端容器。

## 7. V1.5 增量验收（2026-11-03）

### 7.1 结论概览

| 类别 | 状态 |
|---|---|
| F01 项目管理（CRUD/归档恢复/进度/详情/活动） | ✅ 已实现；后端与前端自动化测试覆盖 |
| F02 子任务（两级、项目继承、完成守卫、级联删除、排序） | ✅ 已实现；覆盖冲突与确认路径 |
| F03 AI 任务拆解（草稿、可编辑、确认后事务创建、幂等） | ✅ 已实现；脚本化模型与 API 覆盖 |
| F04 优先级建议与每日计划（确定性评分、容量/重叠校验） | ✅ 已实现；服务与接口测试覆盖 |
| F05 应用内提醒（去重、已读、完成清理、持久化） | ✅ 已实现；服务与接口测试覆盖 |
| F06 活动记录（真实写入、快照、项目活动） | ✅ 已实现；失败写入不产生记录有回归测试 |
| F07 日报/周报/项目报告（后端统计、AI 建议、导出） | ✅ 已实现；统计范围与 AI 降级有测试 |
| 数据库迁移 0003（旧任务保留、完成时间回填、备份） | ✅ 已通过迁移测试，并在 Docker 旧数据卷实际升级 |
| 前端页面（看板/任务/项目/今日/报告/助手/提醒） | ✅ 已实现；组件测试、构建与无头浏览器截图检查 |
| 真实 DeepSeek 验证 V1.5 新工具 | ✅ 已执行：拆解、每日计划、优先级建议、报告四类场景通过 |
| Docker 重建与 V1.5 部署（127.0.0.1:3000） | ✅ 已构建、启动并验证 3000/8000 健康检查 |
| Docker 旧数据卷从 0002 升级到 0003 | ✅ 已用真实 v1.2 数据库卷验证：任务保留、完成时间回填、自动备份 |
| GitHub Actions 托管执行 | ⚠️ 仍未在 GitHub 托管环境验证 |
| 实体移动设备 | ⚠️ 仅无头浏览器 390px 视口检查，未测实体设备 |

### 7.2 后端

实际执行：

```powershell
cd backend
uv run ruff format --check app tests
uv run ruff check app tests
uv run pytest -q
```

结果：

- Ruff format：**64 files already formatted**
- Ruff lint：`All checks passed!`
- Pytest：**122 passed**
- 覆盖率：**82%**（`app` 整体，4527 statements / 806 missed，`pytest-cov` term-missing 报告）。

新增/更新的自动化覆盖包括：

- 项目 CRUD、日期校验、归档/恢复、归档项目禁止新增任务、项目进度（叶子任务）、项目详情任务与活动。
- 子任务项目继承、两级限制、父任务完成守卫、重开清空 `completed_at`、父任务删除确认与级联删除、子任务排序、父项目变更同步子任务。
- 活动记录：创建/修改/完成/重开/删除/项目变更、失败写入不产生成功记录、删除后保留快照、项目最近活动。
- 计划：保存/替换/读取/取消、重叠检测、超出容量、已完成任务拒绝、未知任务、日期不一致、确定性建议的时间块不重叠且不安排容器/已完成任务。
- 提醒：逾期/即将截止/今日待办生成、重复同步去重、已读持久化、完成任务清理提醒、接口已读/全部已读/未读数。
- 报告：按 `completed_at` 限定的完成统计、过去时间范围不误算当前完成、周报项目与后续计划、项目报告必填项目、生成不自动保存、保存/编辑/删除/Markdown 导出、AI 建议注入与失败降级、空数据不编造。
- Agent：17 个工具注册、拆解草稿确认后父子任务事务创建、重复确认不重复、编辑后确认、无效编辑不消耗操作、计划草稿与超容量拒绝、报告保存与幂等、优先级理由、报告事实工具、活动工具。
- 迁移：v1.2 → v1.5 旧任务保留、完成时间回填、旧 pending action 保留、新 action 类型可写入、外键级联与 SET NULL、升级备份存在、重复启动不重复备份。

### 7.3 前端

在项目真实 `frontend/` 目录执行：

```powershell
cd frontend
npm test -- --run
npm run lint
npm run typecheck
npm run build
```

结果：

- Vitest：**54 passed**（10 个测试文件）
- oxlint：**0 warnings, 0 errors**
- `tsc -b`：通过
- Vite 生产构建：成功；单个 JS chunk 972.52 kB（gzip 308.70 kB），仅非阻断体积提示。

新增/更新的组件与页面测试覆盖：

- 项目列表、创建校验、归档、详情跳转。
- 任务页项目/优先级筛选、优先级建议采用、子任务添加/排序相关交互（组件级）。
- 今日计划：空状态、建议生成、采用建议写入、计划任务完成、移除时间块。
- 报告：生成草稿预览、确认后保存并跳转、已保存列表、页面空状态。
- 提醒：点击提醒标记已读并打开对应任务、全部已读、未读筛选空状态。
- 拆解编辑器：编辑标题/子任务、新增父任务与子任务、空标题禁用确认。
- 既有 V1.0/V1.2 任务、表单、AI 面板与 SSE 测试继续通过。

### 7.4 迁移与数据保留

使用临时数据库执行：

- 空库 → `0003_v1_5`：新表与 `tasks` 新列全部存在，revision 为 head。
- v1.2 库（含任务与 pending action）→ 升级：任务数量与内容保留；`priority=medium`、`position=0`、旧完成任务的 `completed_at = updated_at`；旧操作保留；新类型操作可插入。
- 升级前生成 `*.db.bak-<timestamp>`；第二次启动不重复备份。
- 外键行为：删除父任务级联删除子任务与提醒；删除项目将任务 `project_id` 置空。
- 详细备份/恢复步骤见 [migration-v1.5.md](migration-v1.5.md)。

### 7.5 运行时冒烟与界面截图

在隔离临时数据库上启动 V1.5 后端（`/api/health` 返回 `version: 1.5.0`）与前端开发服务器，用 httpx 写入项目、任务、子任务、计划与一份已保存日报，然后使用无头浏览器截取：

- Dashboard、My Tasks、Projects、Project Detail、Today、Reports（列表与详情）、AI Assistant、Notification Center。
- 截图过程报告：**没有控制台错误、横向溢出或加载失败的图片**。
- 观察并修正了：卡片默认最小高度造成的空白、建议/报告按钮被拉伸为整行、后台控件样式与纸张风格不一致、Drawer `width` 弃用警告。
- 截图保存在 `docs/assets/`，用于 README 预览；截图使用隔离数据，不影响本地开发库。

### 7.6 本次仍未验证

- **GitHub Actions 托管运行**：工作流命令已本地等价执行（Ruff、Pytest、oxlint、tsc、Vitest、Vite build），但未触发远程 runner。
- **实体移动设备**：仅桌面视口与无头浏览器 390×844 视口检查，未做实体设备触控测试。
- **真实模型稳定性**：真实 DeepSeek 只完成一轮冒烟样本，不能取代重复回归；模型输出具有非确定性。

### 7.7 V1.5 带来的已知限制更新

- 子任务仅两级；父任务完成前必须完成全部子任务。
- 项目进度按叶子任务统计；父任务作为容器不重复计数，因此“任务总数”在不同页面可能有不同口径。
- 提醒是应用内派生数据：读取时同步生成/清理，不提供后台推送。
- 每日计划仅单日，不自动跨天重排。
- 报告为 Markdown 文本，不含 PDF/Word 排版。
- 活动日志使用快照字符串保存任务/项目 ID，不设外键，以保证删除后历史可追溯。

### 7.8 真实 DeepSeek V1.5 工具联调

- 环境：Docker 隔离容器（`taskpilot-real-smoke`），临时数据库 `/tmp/smoke.db`，真实 `DEEPSEEK_API_KEY`，模型 `deepseek-flash`；不接触正式数据卷。
- 脚本：[`scripts/real_agent_smoke.py`](../scripts/real_agent_smoke.py)，可重复执行并输出 `RESULT <场景> <状态>`。
- 首轮曾因容器 `--env-file` 把 `.env` 中 Key 的引号一起传入而得到 `AI_AUTH_ERROR`；用正确解析的环境变量重启隔离容器后重跑。正式 Compose 部署的 Key 解析正确（长度/前缀/后缀核对通过）。
- 结果：
  1. **任务拆解 PASS**：真实模型调用 `prepare_task_breakdown`，确认后创建 20 个父子任务，重复确认数量不变（幂等）。
  2. **每日计划 PASS**：为明天 3 小时生成 4 个时间块（180/180 分钟），确认后保存，重复确认不重复。首轮在当天 23:47 请求“今天”时，系统按剩余时间正确给出无法安排，模型如实说明，没有虚构任务。
  3. **优先级建议 PASS**：只读回答，给出多条任务的后端得分与理由（逾期、24 小时内到期、预计耗时、项目状态），未产生待确认操作、未修改任务。
  4. **报告 PASS**：真实模型调用 `prepare_save_report`，确认后保存 1 份日报，重复确认返回同一 `report_id`，正文包含明确统计范围。
- **真实联调发现并修复的缺陷**：模型把报告时间范围传成同一天的 `YYYY-MM-DD` 两个日期，旧解析产生 `end <= start` 校验失败，报告工具返回“获取报告数据失败”。已在 `backend/app/agent/tools.py` 的 `_report_request` 中把“同一天”“只给一端”的日期归一化为一整天，并新增回归测试 `test_report_tool_normalizes_same_day_and_one_sided_periods`；修复后重新构建镜像并通过上述报告场景。
- 上述结果是一轮真实模型样本；自动化测试仍全部使用 Mock/脚本化模型，不把真实调用放入 CI。

### 7.9 Docker 部署与旧数据卷升级

- 构建：`docker compose build` 成功构建 `taskpilot-backend:latest` 与 `taskpilot-frontend:latest`（Vite 构建只有非阻断 chunk 体积提示）。
- 部署：`docker compose up -d` 重建前后端容器；`http://127.0.0.1:8000/api/health` 与 `http://127.0.0.1:3000/api/health` 均返回 `version: 1.5.0`，两个容器 healthy；`http://127.0.0.1:3000/` 正常返回页面。
- 正式数据卷 `taskpilot_taskpilot-data`：升级前在容器内生成 `taskpilot.db.pre-v15-20261103234425`，并额外复制到宿主机临时目录；升级后原有 **4 个任务全部保留**。该卷在此前一次镜像构建中已迁到 0003，本次重启未再触发结构升级。
- 为完整验证 Docker 启动迁移，另行创建了一个真实的 v1.2 数据库（2 个任务 + 1 个 pending action）与独立测试卷，用 V1.5 镜像启动：
  - 日志显示 `Running upgrade 0002_ai_upgrade -> 0003_v1_5`；
  - 自动生成 `taskpilot.db.bak-20261103155336`；
  - 升级后 revision 为 `0003_v1_5`，两个任务内容保留，已完成任务的 `completed_at` 回填为原 `updated_at`；
  - 旧 `update_task` pending action 保留；`projects`、`reports` 等新表存在。
- 测试卷与临时容器已清理；正式堆栈保持运行，地址 <http://127.0.0.1:3000/>。
- 生产构建页面在 <http://127.0.0.1:3000/#/dashboard> 实际渲染检查通过：读取到原有 4 个任务，无控制台错误、无横向溢出。
- 版本与锁文件：`backend/pyproject.toml`、`frontend/package.json` 均为 `1.5.0`；已用 uv 重新生成 `backend/uv.lock`（`taskpilot-backend 1.5.0`，`uv lock --check` 通过），并用 npm 更新 `frontend/package-lock.json` 根版本。
- 旧任务在 V1.5 之前没有活动记录，因此升级后看板“最近活动”对历史任务是空的；这是“不伪造历史”的预期行为，首次编辑/完成后开始产生记录。
