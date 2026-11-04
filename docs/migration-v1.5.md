# TaskPilot V1.5 数据库迁移与恢复

- 适用版本：V1.0 / V1.2 → V1.5
- 数据库：SQLite（`DATABASE_URL` 默认 `sqlite:///./data/taskpilot.db`）
- 迁移工具：Alembic，版本链 `0001_v1_0 → 0002_ai_upgrade → 0003_v1_5`

> 迁移不删除、不重建数据库。升级前会复制一份备份；如升级失败或结果异常，停止应用后用备份覆盖数据库文件即可恢复。

## 1. 结构变化

`0003_v1_5` 新增：

- `projects`
- `task_activities`（追加式活动日志，任务/项目 ID 为快照字符串，不设外键）
- `daily_plans`
- `plan_items`
- `notifications`
- `reports`

`tasks` 增量增加：

| 列 | 说明 |
|---|---|
| `project_id` | 所属项目，可空；项目删除时置空 |
| `parent_id` | 父任务，可空；父任务删除时级联删除子任务 |
| `priority` | `high` / `medium` / `low`，默认 `medium` |
| `estimated_minutes` | 5–1440 或空 |
| `position` | 子任务顺序，默认 0 |
| `completed_at` | 完成时间；旧已完成任务回填为原 `updated_at` |

`pending_actions` 重建以允许新的 action 类型（任务拆解、保存计划、保存报告）；所有历史操作原样保留。

## 2. 自动迁移（推荐）

应用启动时 `prepare_database` 会：

1. 检查 `alembic_version` 与现有表。
2. 需要升级时先把 SQLite 文件复制为 `taskpilot.db.bak-<UTC 时间戳>`（同目录）。
3. 执行 `alembic upgrade head`。
4. 如果数据库结构既无版本标记、又不匹配 v1.0 基线，则拒绝自动修改并报错，避免破坏未知数据。

日志示例：

```text
INFO  [alembic.runtime.migration] Running upgrade 0002_ai_upgrade -> 0003_v1_5, TaskPilot v1.5 ...
INFO  taskpilot.migrations        Created pre-migration SQLite backup at ...\taskpilot.db.bak-20261103231000
```

### 升级前手动备份（建议）

```powershell
# 停止后端后执行；把 <时间戳> 换成实际值
Copy-Item backend\data\taskpilot.db backend\data\taskpilot.db.manual-backup-<时间戳>
```

Docker：

```powershell
docker compose stop backend
docker compose run --rm backend sh -c "cp /data/taskpilot.db /data/taskpilot.db.manual-backup-<时间戳>"
docker compose up -d backend
```

## 3. 升级后核对

```powershell
cd backend
uv run alembic current
```

应输出 `0003_v1_5 (head)`。

其他检查：

```powershell
# 任务数量与升级前一致（通过 API 或 sqlite3）
uv run python -c "import sqlite3,os; p='data/taskpilot.db'; c=sqlite3.connect(p); print(c.execute('select count(*) from tasks').fetchone()[0])"
```

- `/api/health` 返回 `version: 1.5.0`。
- 任务、项目、子任务、计划、提醒、报告页面能正常读取。
- 数据目录出现 `taskpilot.db.bak-*` 备份文件。

## 4. 恢复备份

停止应用，防止 WAL 写入冲突：

```powershell
# 1) 停止后端（本地 Ctrl+C；Docker: docker compose stop backend）
# 2) 保留当前库再覆盖（可选）
Move-Item backend\data\taskpilot.db backend\data\taskpilot.db.failed
# 3) 用备份恢复
Copy-Item backend\data\taskpilot.db.bak-20261103231000 backend\data\taskpilot.db
# 4) 启动后端
```

Docker 命名卷：

```powershell
docker compose stop backend
docker compose run --rm backend sh -c "cp /data/taskpilot.db.bak-<时间戳> /data/taskpilot.db"
docker compose up -d backend
```

备份是普通 SQLite 文件，可用 `sqlite3`、DB Browser 等工具直接打开核对。

## 5. 手动迁移（特殊场景）

```powershell
cd backend
uv run alembic current
uv run alembic upgrade head
```

Alembic 配置从根目录 `.env` 或 `backend/.env` 读取 `DATABASE_URL`。

## 6. 降级说明

`0003_v1_5.downgrade()` 会删除新增表与新增列，并且只保留 v1.0/v1.2 支持的 action 类型；这会**丢失**项目、子任务、计划、提醒、报告与新类型待确认操作。

因此：

- 生产/真实数据场景请使用**备份恢复**，不要执行 downgrade。
- 仅在没有真实数据的开发临时库上使用 `alembic downgrade 0002_ai_upgrade` 验证迁移脚本。

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动报 “Database schema has no alembic_version …” | 数据库结构无法识别 | 停止应用，恢复备份；或设置 `DATABASE_AUTO_MIGRATE=false` 后人工检查 |
| 迁移后任务数量变化 | 不应发生 | 立即停止应用并恢复 `.bak-*` 备份，保留现场用于排查 |
| 权限错误/只读 | 数据目录不可写 | 确认运行用户对 `backend/data` 或 `/data` 有写权限 |
| 报告/统计缺少历史完成时间 | V1.0 只有 `updated_at` | 迁移已用 `updated_at` 回填；无法还原更精确的历史完成时间 |
| Docker 升级后看不到新表 | 使用了不同数据卷 | 确认 `docker-compose.yml` 卷映射与容器内 `DATABASE_URL` 一致 |
