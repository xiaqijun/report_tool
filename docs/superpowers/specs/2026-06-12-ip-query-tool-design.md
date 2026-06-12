# IP批量查询工具 — 设计说明

**日期：** 2026-06-12  
**状态：** 待审核

## 概述

将 `query_ip.py`（独立 Python 脚本）集成到报告管理工具系统中，作为"富强专用工具"菜单下的第一个工具。面向所有登录用户，支持批量查询 IPv4/IPv6 地址的归属地信息。

## 菜单结构

侧边栏新增独立顶级分组，与"主机预警""安全日报"并列：

```
富强专用工具
  ├── IP批量查询     /tools/ip-query
  └── （后续工具追加…）
```

## 后端设计

### 服务层 `app/services/ip_query.py`

移植 `query_ip.py` 的核心逻辑，封装为以下函数：

| 函数 | 职责 |
|---|---|
| `classify_ips(ip_list)` | 将 IP 列表分为 v4 / v6 / invalid 三类，去重 |
| `query_ipv4_batch(ip_list)` | 调用 lzltool.cn API 查询 IPv4 归属地 |
| `query_ipv6_batch(ip_list)` | 调用 tooldeer.com API 查询 IPv6 归属地 |
| `query_ips(ip_list)` | 主入口 — 分类 → 并行查询 → 合并结果 |

**关键实现细节：**
- 保留 lzltool.cn 签名逻辑（`CONST1/CONST2`、时间戳对齐、MD5 签名）
- 保留 tooldeer.com 简单 GET 请求方式
- IPv4 每批 300 个，IPv6 每批 500 个
- 使用 `requests.Session`，忽略 SSL 验证
- 无效 IP 在结果中标记为 `(无效IP)`

**不持久化：** 纯查询功能，无数据库读写。IP 和结果不落库。

### API 端点

在 `app/routers/api.py` 中新增：

```
POST /api/tools/ip-query
```

**请求体：** 支持两种格式，后端自动识别：

格式 A — 文本框粘贴（JSON）：
```json
{
  "ips": ["1.2.3.4", "2001:db8::1", "invalid-text"]
}
```

格式 B — 文件上传（multipart/form-data）：
- `file` 字段：.txt 或 .csv 文件，每行一个 IP

**超时：** 300 秒（5 分钟），适配大批量查询。

**响应体：**
```json
{
  "summary": {
    "total": 3,
    "v4_count": 1,
    "v6_count": 1,
    "invalid_count": 1,
    "duplicate_count": 0
  },
  "results": [
    {
      "ip": "1.2.3.4",
      "country": "中国",
      "province": "广东",
      "city": "深圳",
      "operator": "电信",
      "source": "lzltool"
    },
    {
      "ip": "2001:db8::1",
      "country": "中国",
      "province": "北京",
      "city": "北京",
      "operator": "",
      "source": "tooldeer"
    },
    {
      "ip": "invalid-text",
      "country": "(无效IP)",
      "province": "",
      "city": "",
      "operator": "",
      "source": ""
    }
  ]
}
```

**错误处理：**
- 外部 API 调用失败返回 502，附带错误信息
- 请求体校验失败返回 422
- 认证检查：通过 `require_login` 依赖

## 前端设计

### 路由

在 `App.tsx` 的 `PrivateRoute` 内新增：

```tsx
<Route path="/tools/ip-query" element={<IpQueryPage />} />
```

### 导航菜单

在 `MainLayout.tsx` 的 `navItems` 中新增顶级分组：

```tsx
{
  itemKey: 'tools',
  text: '富强专用工具',
  icon: <IconTool />,
  items: [
    { itemKey: '/tools/ip-query', text: 'IP批量查询', icon: <IconSearch /> },
  ],
}
```

### 页面组件 `frontend/src/pages/Tools/IpQuery/index.tsx`

**布局：**
- 顶部：输入区域 — Tab 切换 "粘贴文本" / "上传文件"
  - Tab 粘贴文本：TextArea，支持换行/空格/逗号分隔的 IP 列表
  - Tab 上传文件：Upload 组件，接受 .txt / .csv，每行一个 IP
- 中上：操作栏（查询按钮 + 去重后的 IP 数量 + 分类统计 v4/v6/无效）
- 中部：加载状态 — 大圈 Spin + 已用时间计时器（大批量时给用户进度感知）
- 主体：结果表格（IP、国家、省份、城市、运营商、来源）
  - 前端分页，默认每页 100 条
  - 支持按列排序
  - 支持导出 CSV（前端生成 Blob 触发下载）

**交互流程：**
1. 用户粘贴 IP 或上传文件
2. 前端解析：从文本中提取 IP 列表（取每行最后一个空白分隔的 token 作为 IP）
3. 去重并显示统计摘要（总数、v4、v6、无效、去重数）
4. 点击"查询"按钮，调用 API，显示计时器
5. 结果以分页表格展示，支持导出

**技术实现：**
- Semi UI 组件：`Tabs`、`TextArea`、`Upload`、`Button`、`Table`、`Spin`、`Toast`、`Tag`
- 文本粘贴走 `api.post('/api/tools/ip-query', { ips })`（JSON）
- 文件上传走 `api.post('/api/tools/ip-query', formData)`（multipart）
- axios 超时设为 330 秒（后端 300s + 余量）
- 表格分页：Semi Table 的 `pagination` 属性
- 导出：前端 `new Blob([csv], {type: 'text/csv'})` + `URL.createObjectURL` 触发下载

**状态管理：**
- 组件内部状态（`useState`），无需 Zustand store
- 状态：`mode`（paste/upload）、`rawText`、`parsedIps`、`loading`、`elapsed`、`results`、`summary`
- 无持久化需求

### 文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `app/services/ip_query.py` | 新建 | IP 查询核心逻辑 |
| `app/routers/api.py` | 修改 | 新增 `/api/tools/ip-query` 端点 |
| `frontend/src/pages/Tools/IpQuery/index.tsx` | 新建 | IP 查询页面 |
| `frontend/src/App.tsx` | 修改 | 新增路由 |
| `frontend/src/components/Layout/MainLayout.tsx` | 修改 | 新增菜单分组 |

## 风险

- **外部 API 依赖：** lzltool.cn 和 tooldeer.com 不可控，可能变更接口或不可用。风险等级：LOW（仅影响查询结果，不影响系统核心功能）。
- **无数据库变更：** 纯查询功能，不存在数据迁移风险。
- **认证仅限登录用户：** 通过 `PrivateRoute` + `require_login` 双重保护。

## 测试要点

- IP 分类正确性（v4 / v6 / 无效 / 混合）
- 去重逻辑
- 批量分片（>300 个 IPv4 / >500 个 IPv6）
- 外部 API 错误处理
- 空输入处理
- 文件上传解析（.txt / .csv，含空行和注释）
- 粘贴文本解析（换行、空格、逗号分隔）
- 大批量超时（数千个 IP，5 分钟内完成）
- 前端表格分页和排序
- 前端导出 CSV 格式正确性
