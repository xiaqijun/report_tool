# CLAUDE.md

本文件为 Claude Code 在此仓库中工作提供指导。

## 项目概述

内部 Web 工具（报告管理工具 / "Asset Ops"），用于生成服务器资产风险报告。用户上传服务器资产电子表格，系统将其与管理员维护的数据集（负责人映射、未配额主机、延迟安装主机、责任人邮箱）进行交叉比对，生成三类分类结果列表（XLSX + CSV）。

**前端：** React SPA（Semi UI + React Router + Zustand，源码在 `frontend/src/`，构建产物输出到 `app/static/react/`） + Jinja2 模板页面（安全日报 SSR，当前已注释）。
**后端：** FastAPI（`app/main.py` → `create_app()`），SessionMiddleware（基于 cookie），`app/routers/api.py`（JSON API）+ `app/routers/daily_report.py`（日报 Jinja2 SSR，已注释）。
**技术栈：** FastAPI、MySQL（PyMySQL）、React 18、Semi UI、Vite、openpyxl、python-docx。

## 命令

```bash
# 运行应用（从 .env 读取 host/port/reload）
python main.py

# 前端开发（Vite dev server，代理 /api → localhost:8000）
cd frontend && npm run dev

# 前端构建（输出到 app/static/react/）
cd frontend && npm run build

# 运行所有测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_inventory_generation.py

# 安装依赖
uv sync
cd frontend && npm install

# 刷新 GitNexus 索引
npx gitnexus analyze
```

未配置 linter/formatter。

## 架构

```
浏览器
  → React SPA (app/static/react/) — 主要 UI，client-side routing
  → FastAPI (app/main.py → create_app())
    ├── /api/* → api_router (app/routers/api.py) — JSON API
    ├── /daily-report/* → daily_report_router (app/routers/daily_report.py) — Jinja2 SSR [已注释]
    ├── /download/{batch_code}/{result_key} — 文件下载
    └── /* → React SPA catch-all (返回 index.html)
         ↓
    app/db.py (PyMySQL, `?` → `%s` 占位符转换)
         ↓
    app/services/
    ├── inventory.py — 资产报告生成（在线未防护/Agent缺失/防护中断）
    ├── email_service.py — 邮件发送（预警邮件 + 日报邮件）
    ├── daily_report_ai.py — LLM 文案生成（安全态势三段总结）
    ├── docx_generator.py — 日报 DOCX 模板渲染导出
    ├── ip_query.py — IP 批量查询（IPv4/IPv6 自动区分）
    └── spreadsheets.py — XLSX/CSV 读写
```

**路由注册（`app/main.py` → `create_app()`）：**

| 路由 | 状态 | 说明 |
|------|------|------|
| `api_router` (`/api/*`) | 活跃 | JSON API，React 前端调用 |
| `daily_report_router` (`/daily-report/*`) | 已注释 | Jinja2 SSR 日报页面 |
| `auth_router` (`/login`, `/logout`, …) | 已注释 | Jinja2 认证页面 |
| `web_router` (`/dashboard`, `/generate`, `/history`) | 已注释 | Jinja2 旧版页面 |
| `admin_router` (`/admin/{dataset_key}`) | 已注释 | Jinja2 数据集管理 |
| `/download/{batch_code}/{result_key}` | 活跃 | 报告文件下载 |
| `/*` catch-all | 活跃 | React SPA fallback |

**认证流程：** `app/auth.py` 从 `request.session` 读取 user_id/username/display_name。`require_login()` 返回用户字典或 401（API）/ 302 重定向。单用户模式 — 启动时自动在 `users` 表创建管理员账号。

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

**必填：** `DATABASE_HOST/PORT/USER/PASSWORD/NAME/CHARSET`、`SECRET_KEY`
**应用：** `APP_HOST/PORT/RELOAD`、`DEFAULT_ADMIN_USERNAME/PASSWORD`
**LLM（可选，用于日报 AI 文案）：** `LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT_SECONDS`
**邮件（可选，用于发送预警/日报邮件）：** `SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS`

LLM 和邮件配置也可通过 `/api/llm-settings` 和 `/api/email/settings` 在数据库 `app_settings` 表中动态覆盖。

> **注意：** `frontend/` 目录（React 源码）在 `.gitignore` 中。新克隆后需 `cd frontend && npm install` 才能构建前端。

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **report_tool** (1418 symbols, 4671 relationships, 125 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
