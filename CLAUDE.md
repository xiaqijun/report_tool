# CLAUDE.md

本文件为 Claude Code 在此仓库中工作提供指导。

## 项目概述

内部 Web 工具（报告管理工具 / "Asset Ops"），用于生成服务器资产风险报告。用户上传服务器资产电子表格，系统将其与三个管理员维护的数据集（负责人映射、未配额主机、延迟安装主机）进行交叉比对，生成三类分类结果列表（XLSX + CSV）。

**技术栈：** FastAPI（服务端 Jinja2 模板，无 SPA）、MySQL（PyMySQL）、Tabler CSS、openpyxl。

## 命令

```bash
# 运行应用（从 .env 读取 host/port/reload）
python main.py

# 运行所有测试
uv run pytest
# 或：pytest

# 安装依赖
uv sync
```

未配置 linter/formatter。

## 架构

```
浏览器请求
  → FastAPI + SessionMiddleware（基于 cookie，Starlette）
    → auth router:      /login, /logout, /change-password
    → web router:       /dashboard, /generate, /history, /download/...
    → admin router:     /admin/{owner-mappings,unquota-hosts,deferred-install-hosts}
      → db.py (PyMySQL, `?` 占位符在执行前转换为 `%s`)
      → services/inventory.py（核心生成逻辑）
      → services/spreadsheets.py（XLSX/CSV 读写，via openpyxl）
      → services/system_update.py（git pull + uv sync 自更新）
```

**认证流程：** `app/auth.py` 从 `request.session` 读取 user_id/username/display_name。`require_login()` 返回用户字典或重定向到 `/login`。无 OAuth，无角色 — 启动时创建的单个管理员用户是唯一用户。

**应用工厂：** `app/main.py` → `create_app()` 创建 FastAPI 实例，挂载 SessionMiddleware，注册路由，并在 lifespan 启动时运行 `init_db()` + `ensure_default_admin()`。

## 数据库

通过 `app/db.py` 访问 MySQL：

- **`get_connection()`** — 上下文管理器，返回 `MySQLConnection`。正常退出时自动提交。
- **占位符风格：** 查询使用 `?` 编写，`_normalize_query()` 在执行前将其替换为 `%s`。新代码中始终使用 `?`。
- **表：** `users`、`owner_mappings`、`unquota_hosts`、`deferred_install_hosts`、`import_histories`、`result_histories`
- **Schema 管理：** `init_db()` 使用 `CREATE TABLE IF NOT EXISTS` 加 `_ensure_column()` 进行增量迁移。无迁移框架。

## 核心业务逻辑（services/inventory.py）

`generate_from_asset_file(file_path, operator_name)`：

1. 通过 `read_table_file()` 读取上传的资产电子表格（XLSX/CSV）。
2. 使用别名映射（`ASSET_FIELD_ALIASES` — 中英文字段名映射）标准化列头。
3. 从数据库加载负责人映射和排除匹配键。
4. 对每行服务器评估三类：
   - **在线未防护** — status=运行中, agent=在线, protection=未防护，排除未配额列表中的主机
   - **Agent 缺失** — status=运行中, agent=未安装，排除延迟安装列表中的主机
   - **防护中断** — status=运行中, protection=防护中断（无排除）
5. 将结果写入 `data/exports/` 下带时间戳的批次目录（XLSX + CSV）。
6. 在 `result_histories` 表中记录历史。

**匹配键** 由 `build_match_keys()` 构建，优先级：`id:<server_id>` → `ip:<extracted_ip>` → `name:<server_name>`。IP 地址通过正则 `\b(?:\d{1,3}\.){3}\d{1,3}\b` 从自由文本字段提取。

## 三数据集模式

`admin.py` 路由使用通用 `dataset_key` 参数（`owner-mappings`、`unquota-hosts`、`deferred-install-hosts` 之一）。`db.py` 中的 `DATASET_DEFINITIONS` 将每个键映射到其表名、列列表、搜索字段和导入模板。`db.py` 中的所有 CRUD 操作接受 `dataset_key` 以分派到正确的表。

## 配置

仓库根目录的 `.env` 文件（gitignored，参见 `.env.example` 模板）。所有设置由 `app/config.py` 通过 `python-dotenv` 读取。关键变量：

- `DATABASE_HOST/PORT/USER/PASSWORD/NAME/CHARSET`
- `APP_HOST/PORT/RELOAD`
- `SECRET_KEY`（用于 session 签名）
- `DEFAULT_ADMIN_USERNAME/PASSWORD`（首次启动时自动创建）

## 模板和静态文件

- Jinja2 模板在 `app/templates/` — base.html → app_shell.html → 各页面。`asset_version` 全局变量通过文件 mtime 破坏 CSS 缓存。
- 自定义 CSS 在 `app/static/app.css`，供应商 CSS/图标在 `app/static/vendor/tabler/` 和 `tabler-icons/`。
- 各数据集的 Excel 导入模板在 `app/static/import-templates/`。

---

## GitNexus — 代码智能

此项目由 GitNexus 索引为 **report_tool**（910 个符号，2535 个关系，79 个执行流程）。使用 GitNexus MCP 工具来理解代码、评估影响和安全导航。

> 如果任何 GitNexus 工具警告索引过期，先在终端运行 `npx gitnexus analyze`。

## 必须做

- **修改任何符号前必须运行影响分析。** 修改函数、类或方法前，运行 `gitnexus_impact({target: "symbolName", direction: "upstream"})` 并向用户报告影响半径（直接调用者、受影响流程、风险等级）。
- **提交前必须运行 `gitnexus_detect_changes()`** 验证更改只影响预期的符号和执行流程。
- **影响分析返回 HIGH 或 CRITICAL 风险时必须警告用户** 才能继续编辑。
- 探索不熟悉的代码时，使用 `gitnexus_query({query: "概念"})` 代替 grep 查找执行流程 — 返回按流程分组、按相关性排序的结果。
- 需要符号的完整上下文（调用者、被调用者、参与的执行流程）时，使用 `gitnexus_context({name: "symbolName"})`。

## 禁止做

- 禁止在未先运行 `gitnexus_impact` 的情况下编辑函数、类或方法。
- 禁止忽略影响分析的 HIGH 或 CRITICAL 风险警告。
- 禁止用查找替换重命名符号 — 使用理解调用图的 `gitnexus_rename`。
- 禁止在未运行 `gitnexus_detect_changes()` 检查影响范围的情况下提交更改。

## 技能文件

| 任务 | 技能文件 |
| --- | --- |
| 理解架构 / "X 怎么工作？" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| 影响半径 / "改 X 会破坏什么？" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| 追踪 bug / "为什么 X 失败？" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| 重命名 / 提取 / 拆分 / 重构 | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| 工具、资源、schema 参考 | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| 索引、状态、清理、wiki CLI 命令 | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

## MCP 资源

| 资源 | 用途 |
| --- | --- |
| `gitnexus://repo/report_tool/context` | 代码库概览，检查索引新鲜度 |
| `gitnexus://repo/report_tool/clusters` | 所有功能区域 |
| `gitnexus://repo/report_tool/processes` | 所有执行流程 |
| `gitnexus://repo/report_tool/process/{name}` | 分步执行追踪 |
| `gitnexus://repo/report_tool/schema` | Cypher 查询的图 schema |

## MCP 工具

| 工具 | 功能 |
| --- | --- |
| `query` | 按流程分组的代码智能 — 与概念相关的执行流程 |
| `context` | 360 度符号视图 — 分类引用、参与的流程 |
| `impact` | 符号影响半径 — 深度 1/2/3 的破坏风险及置信度 |
| `detect_changes` | Git diff 影响分析 — 当前更改影响了什么 |
| `rename` | 多文件协调重命名，带置信度标签 |
| `cypher` | 原始图查询（先读 `gitnexus://repo/report_tool/schema`） |
| `list_repos` | 发现已索引的仓库 |

## CLI 命令

```bash
# 构建或刷新索引
npx gitnexus analyze

# 检查索引新鲜度
npx gitnexus status

# 删除索引
npx gitnexus clean

# 从图生成文档
npx gitnexus wiki

# 列出所有已索引仓库
npx gitnexus list
```

## 风险等级参考

| 深度 | 风险 | 含义 |
| --- | --- | --- |
| d=1 | **会破坏** | 直接调用者/导入者 |
| d=2 | 可能影响 | 间接依赖 |
| d=3 | 需要测试 | 传递效果 |

| 受影响范围 | 风险等级 |
| --- | --- |
| <5 个符号，少量流程 | LOW |
| 5-15 个符号，2-5 个流程 | MEDIUM |
| >15 个符号或多个流程 | HIGH |
| 关键路径（认证、支付） | CRITICAL |

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **report_tool** (1004 symbols, 2662 relationships, 88 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/report_tool/context` | Codebase overview, check index freshness |
| `gitnexus://repo/report_tool/clusters` | All functional areas |
| `gitnexus://repo/report_tool/processes` | All execution flows |
| `gitnexus://repo/report_tool/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
