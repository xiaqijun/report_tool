# CLAUDE.md

本文件为 Claude Code 在此仓库中工作提供指导。

## 项目概述

内部 Web 工具（报告管理工具 / "Asset Ops"），用于生成服务器资产风险报告。用户上传服务器资产电子表格，系统将其与管理员维护的数据集（负责人映射、未配额主机、延迟安装主机、责任人邮箱）进行交叉比对，生成三类分类结果列表（XLSX + CSV）。

**前端：** React SPA（`app/static/react/`） + 部分 Jinja2 模板页面（安全日报等）。
**后端：** FastAPI JSON API（`app/routers/api.py`）为主，SessionMiddleware（基于 cookie）。
**技术栈：** FastAPI、MySQL（PyMySQL）、React、Tabler CSS、openpyxl。

## 命令

```bash
# 运行应用（从 .env 读取 host/port/reload）
python main.py

# 运行所有测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_inventory_generation.py

# 安装依赖
uv sync

# 刷新 GitNexus 索引
npx gitnexus analyze
```

未配置 linter/formatter。

## 架构

```
浏览器 → React SPA (app/static/react/)
  → FastAPI JSON API (app/routers/api.py, 前缀 /api)
    → app/db.py (PyMySQL, `?` 占位符 → `%s`)
    → app/services/inventory.py（资产报告生成）
    → app/services/email_service.py（邮件发送）
    → app/services/daily_report_ai.py（LLM 文本生成）
    → app/services/docx_generator.py（日报 DOCX 导出）
    → app/services/ip_query.py（IP 批量查询）
    → app/services/spreadsheets.py（XLSX/CSV 读写）
```

**当前活跃路由（`app/main.py` → `create_app()`）：**
- `api_router` (`/api/*`) — 所有 JSON API，供 React 前端调用
- `/download/{batch_code}/{result_key}` — 文件下载（兼容旧版）
- React SPA catch-all — 非 API 路径返回 `app/static/react/index.html`

**已注释的路由（Jinja2 SSR，代码保留未删除）：**
- `auth_router` — `/login`, `/logout`, `/change-password`
- `web_router` — `/dashboard`, `/generate`, `/history`
- `admin_router` — `/admin/{dataset_key}`
- `daily_report_router` — `/daily-report/*`（日报表单、预览、操作人员管理等 Jinja2 页面）

**认证流程：** `app/auth.py` 从 `request.session` 读取 user_id/username/display_name。`require_login()` 返回用户字典或 401（API）/ 302 重定向。单用户模式 — 启动时自动创建管理员账号。

## 数据库

通过 `app/db.py` 访问 MySQL：

- **`get_connection()`** — 上下文管理器，正常退出时自动提交。
- **占位符风格：** 查询使用 `?` 编写，`_normalize_query()` 在执行前替换为 `%s`。
- **Schema 管理：** `init_db()` 使用 `CREATE TABLE IF NOT EXISTS` + `_ensure_column()` 增量迁移。无迁移框架。

**表：**

| 表 | 用途 |
|---|---|
| `users` | 用户（单管理员） |
| `owner_mappings` | 企业项目 → 负责人映射 |
| `owner_emails` | 责任人 → 邮箱映射 |
| `unquota_hosts` | 未配额主机（排除列表） |
| `deferred_install_hosts` | 暂不安装主机（排除列表） |
| `import_histories` | 导入历史 |
| `result_histories` | 报告生成历史 |
| `daily_security_reports` | 每日安全日报数据 |
| `ops_personnel` | 运营人员 |
| `app_settings` | 键值存储（LLM 配置、邮件配置等） |

## 核心业务逻辑

### 资产报告生成（`services/inventory.py`）

`generate_from_asset_file(file_path, operator_name)`：
1. `read_table_file()` 读取上传的资产电子表格（XLSX/CSV）。
2. `ASSET_FIELD_ALIASES` 中英文字段名映射标准化列头。
3. 加载负责人映射和排除匹配键。
4. 逐行评估三类：
   - **在线未防护** — status=运行中, agent=在线, protection=未防护，排除未配额主机
   - **Agent 缺失** — status=运行中, agent=未安装，排除暂不安装主机
   - **防护中断** — status=运行中, protection=防护中断（无排除）
5. 写入 `data/exports/{batch_code}/`（XLSX 含汇总 sheet + CSV）。
6. 记录到 `result_histories`。

**匹配键** 由 `build_match_keys()` 构建，优先级：`id:{server_id}` → `ip:{extracted_ip}` → `name:{server_name}`。IP 通过 `\b(?:\d{1,3}\.){3}\d{1,3}\b` 从自由文本提取。

### 安全日报（`services/daily_report_ai.py` + `docx_generator.py`）

日报包含 WAF/CFW/HSS/DDoS/SecMaster 多产品告警数据，支持：
- LLM 生成顶部三段文案（业务运行情况、趋势对比、总体评估），失败时回退本地兜底文案
- DOCX 模板渲染导出
- 截图粘贴上传
- DOCX 导入解析（`scripts/import_docx_report.py`）

### 邮件服务（`services/email_service.py`）

- `send_warning_email()` — 发送主机安全预警邮件，含周同比和责任人邮箱表
- `send_daily_report_email()` — 发送日报邮件，可选 DOCX 附件
- `generate_email_from_report()` — 根据报告数据生成 HTML 邮件，支持 base64 内嵌图片和周同比箭头

### IP 批量查询（`services/ip_query.py`）

自动区分 IPv4/IPv6：
- IPv4 → lzltool.cn（POST 签名，每批 300）
- IPv6 → tooldeer.com（GET，每批 500）

## 四数据集模式

`DATASET_DEFINITIONS`（`app/db.py`）定义四个数据集，统一 CRUD 操作通过 `dataset_key` 分派：

| Key | 表 | 说明 |
|---|---|---|
| `owner-mappings` | `owner_mappings` | 项目-责任人映射 |
| `owner-emails` | `owner_emails` | 责任人-邮箱映射 |
| `unquota-hosts` | `unquota_hosts` | 未配额主机列表 |
| `deferred-install-hosts` | `deferred_install_hosts` | 暂不安装主机列表 |

## 配置

仓库根目录的 `.env` 文件（gitignored，参见 `.env.example`）。`app/config.py` 通过 `python-dotenv` 读取。

**数据库：** `DATABASE_HOST/PORT/USER/PASSWORD/NAME/CHARSET`
**应用：** `APP_HOST/PORT/RELOAD`、`SECRET_KEY`、`DEFAULT_ADMIN_USERNAME/PASSWORD`
**LLM：** `LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT_SECONDS`
**邮件：** `SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS`

LLM 和邮件配置也可通过 `/api/llm-settings` 和 `/api/email/settings` 在数据库 `app_settings` 表中动态覆盖。

## 模板和静态文件

- React SPA 构建产物：`app/static/react/`（index.html + assets/）
- Jinja2 模板：`app/templates/`（base.html → app_shell.html → 各页面）
- 自定义 CSS：`app/static/app.css`
- 供应商库：`app/static/vendor/tabler/`、`tabler-icons/`
- 数据集导入模板：`app/static/import-templates/`
- 日报 DOCX 模板：`app/static/report-templates/daily-report-template.docx`
- 邮件模板内嵌图片：`app/static/email-images/`

---

## GitNexus — 代码智能

此项目由 GitNexus 索引为 **report_tool**。GitNexus 规则详见 `AGENTS.md`（自动生成，勿手动编辑）。

> 如果任何 GitNexus 工具警告索引过期，先在终端运行 `npx gitnexus analyze`。

### 必须做

- **修改任何符号前必须运行影响分析。** 运行 `mcp__gitnexus__impact({target: "symbolName", direction: "upstream"})` 并报告影响半径。
- **提交前必须运行 `mcp__gitnexus__detect_changes()`** 验证更改范围。
- **影响分析返回 HIGH 或 CRITICAL 风险时必须警告用户** 才能继续编辑。
- 探索不熟悉的代码时，使用 `mcp__gitnexus__query({query: "概念"})` 查找执行流程。
- 需要符号完整上下文时，使用 `mcp__gitnexus__context({name: "symbolName"})`。

### 禁止做

- 禁止在未先运行影响分析的情况下编辑函数、类或方法。
- 禁止忽略 HIGH 或 CRITICAL 风险警告。
- 禁止用查找替换重命名符号 — 使用 `mcp__gitnexus__rename`。
- 禁止在未运行 `mcp__gitnexus__detect_changes()` 的情况下提交更改。

### MCP 资源

| 资源 | 用途 |
|---|---|
| `gitnexus://repo/report_tool/context` | 代码库概览，检查索引新鲜度 |
| `gitnexus://repo/report_tool/clusters` | 所有功能区域 |
| `gitnexus://repo/report_tool/processes` | 所有执行流程 |
| `gitnexus://repo/report_tool/process/{name}` | 分步执行追踪 |
| `gitnexus://repo/report_tool/schema` | Cypher 查询的图 schema |
