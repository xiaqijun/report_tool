# IP批量查询工具 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 IP 批量查询工具集成到系统中，新建"富强专用工具"菜单，支持 IPv4/IPv6 归属地批量查询。

**Architecture:** 后端 `app/services/ip_query.py` 封装查询逻辑，`POST /api/tools/ip-query` 提供 API；前端新增 `/tools/ip-query` 路由和页面，支持文本粘贴和文件上传两种输入方式。

**Tech Stack:** Python (requests, ipaddress, hashlib), React + TypeScript + Semi UI

---

### Task 1: 后端 — IP 查询服务层

**Files:**
- Create: `app/services/ip_query.py`

- [ ] **Step 1: 创建 `app/services/ip_query.py`**

将 `query_ip.py` 的核心逻辑移植为服务模块，去掉 CLI 部分，封装为可调用的函数：

```python
"""IP 批量查询服务 — 自动区分 IPv4/IPv6，调用不同接口
  IPv4 → lzltool.cn  (POST 签名, 每批 300)
  IPv6 → tooldeer.com (GET 无签名, 每批 500)
"""
import hashlib
import ipaddress
import json
import re
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === lzltool.cn IPv4 常量 ===
CONST1 = '8B45658185274923'
CONST2 = '8A5BF51F1A3A4132'
LZL_BATCH = 300

# === tooldeer IPv6 常量 ===
TOOLDEER_URL = 'https://www.tooldeer.com/api/v1/ipv6'
TOOLDEER_BATCH = 500


def _is_ipv4(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except Exception:
        return False


def _is_ipv6(ip: str) -> bool:
    try:
        ipaddress.IPv6Address(ip)
        return True
    except Exception:
        return False


class _LZLToolAPI:
    """lzltool.cn IPv4 查询封装."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        resp = self.session.get('https://lzltool.cn/tool/ip', verify=False)
        m = re.search(
            r"window\.serverTimeDifference\s*=\s*(\d+)\s*-\s*Math\.round\(Date\.now\(\)\s*/\s*1000\)",
            resp.text,
        )
        self._time_base = int(m.group(1)) if m else 0

    def _ts(self) -> str:
        return str(int(time.time()) + self._time_base - round(time.time()))

    def _sign(self, url: str, data: str, ts: str) -> str:
        sign_input = '|'.join([CONST1, url.strip().lower(), data.strip(), ts, CONST2])
        return hashlib.md5(sign_input.encode()).hexdigest()

    def _query_batch(self, ip_list: list[str]) -> list[dict]:
        url = '/Network/FindIpInfo'
        data = json.dumps({"IpList": ip_list}, separators=(',', ':'))
        ts = self._ts()
        sig = self._sign(url, data, ts)
        resp = self.session.post(
            'https://lzltool.cn' + url,
            data=data,
            headers={
                'RequestSignature': sig,
                'RequestTimestamp': ts,
                'Content-Type': 'application/json',
                'Referer': 'https://lzltool.cn/tool/ip',
                'Origin': 'https://lzltool.cn',
            },
            verify=False,
            timeout=30,
        )
        result = resp.json()
        if result.get('Succeed'):
            return result.get('Data', [])
        raise Exception(f"lzltool 错误: {result.get('Message')}")

    def query(self, ip_list: list[str]) -> list[dict]:
        results = []
        for i in range(0, len(ip_list), LZL_BATCH):
            batch = ip_list[i:i + LZL_BATCH]
            results.extend(self._query_batch(batch))
        return results


def _query_ipv4(ip_list: list[str]) -> list[dict]:
    """查询 IPv4 归属地."""
    if not ip_list:
        return []
    lzl = _LZLToolAPI()
    results = []
    for item in lzl.query(ip_list):
        results.append({
            'Ip': item['Ip'],
            'Country': item.get('Country', ''),
            'Province': item.get('Province', ''),
            'City': item.get('City', ''),
            'Operator': item.get('Operator', ''),
            'Source': 'lzltool',
        })
    return results


def _query_ipv6(ip_list: list[str]) -> list[dict]:
    """查询 IPv6 归属地."""
    if not ip_list:
        return []
    results = []
    for i in range(0, len(ip_list), TOOLDEER_BATCH):
        batch = ip_list[i:i + TOOLDEER_BATCH]
        body = '\n'.join(batch)
        resp = requests.get(
            TOOLDEER_URL,
            params={'wd': body, 'lang': 'cn'},
            timeout=30,
            verify=False,
        )
        data = resp.json()
        if data.get('code') == 200:
            for item in data.get('data', []):
                results.append({
                    'Ip': item['Ip'],
                    'Country': item.get('CountryLong', ''),
                    'Province': item.get('Region', ''),
                    'City': item.get('City', ''),
                    'Operator': '',
                    'Source': 'tooldeer',
                })
        else:
            raise Exception(f"tooldeer 错误: {data.get('msg')}")
    return results


def classify_ips(raw_ips: list[str]) -> dict:
    """对 IP 列表去重并分类。

    Returns:
        {
            'v4': [...], 'v6': [...], 'invalid': [...],
            'total': N, 'unique': N, 'duplicate_count': N,
        }
    """
    ips = list(dict.fromkeys(raw_ips))
    dup_count = len(raw_ips) - len(ips)

    v4 = [ip for ip in ips if _is_ipv4(ip)]
    v6 = [ip for ip in ips if _is_ipv6(ip)]
    invalid = [ip for ip in ips if not _is_ipv4(ip) and not _is_ipv6(ip)]

    return {
        'v4': v4,
        'v6': v6,
        'invalid': invalid,
        'total': len(raw_ips),
        'unique': len(ips),
        'duplicate_count': dup_count,
    }


def query_ips(ip_list: list[str]) -> list[dict]:
    """查询一批 IP 的归属地信息，自动区分 v4/v6。

    Args:
        ip_list: 原始 IP 字符串列表（含空行、无效值等）

    Returns:
        结果列表，每条: {Ip, Country, Province, City, Operator, Source}
    """
    classification = classify_ips(ip_list)

    results = []

    # 查询 IPv4
    if classification['v4']:
        results.extend(_query_ipv4(classification['v4']))

    # 查询 IPv6
    if classification['v6']:
        results.extend(_query_ipv6(classification['v6']))

    # 无效 IP 也记录
    for ip in classification['invalid']:
        results.append({
            'Ip': ip,
            'Country': '(无效IP)',
            'Province': '',
            'City': '',
            'Operator': '',
            'Source': '',
        })

    return results
```

- [ ] **Step 2: 测试服务模块**

```bash
cd e:/github/report_tool && python -c "
from app.services.ip_query import classify_ips, query_ips
# 测试 classify_ips
c = classify_ips(['8.8.8.8', '8.8.8.8', '2001:db8::1', 'not-an-ip'])
assert c['duplicate_count'] == 1
assert len(c['v4']) == 1
assert len(c['v6']) == 1
assert len(c['invalid']) == 1
print('classify_ips: OK')

# 测试 query_ips (实际调用外部 API)
results = query_ips(['8.8.8.8', '2001:db8::1', 'invalid'])
assert len(results) == 3
for r in results:
    assert 'Ip' in r and 'Country' in r and 'Source' in r
print('query_ips: OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/services/ip_query.py
git commit -m "feat: add IP query service module (IPv4 lzltool + IPv6 tooldeer)"
```

---

### Task 2: 后端 — API 端点

**Files:**
- Modify: `app/routers/api.py` (新增路由)

- [ ] **Step 1: 在 `app/routers/api.py` 文件末尾新增端点**

在文件最末尾（第 805 行之后）添加以下内容：

```python
class IpQueryRequest(BaseModel):
    ips: list[str]


@router.post("/tools/ip-query")
async def api_ip_query(request: Request, body: Optional[IpQueryRequest] = None):
    """IP 批量查询 — 支持 JSON 和文件上传两种方式."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    from ..services.ip_query import classify_ips, query_ips

    # 格式 A: 文件上传 (multipart/form-data)
    content_type = request.headers.get("content-type", "")
    ips = []

    if body and body.ips:
        # 格式 B: JSON body
        ips = body.ips
    else:
        # 尝试从 form 中读取文件
        form = await request.form()
        upload_file = form.get("file")
        if upload_file and hasattr(upload_file, "filename"):
            content = (await upload_file.read()).decode("utf-8", errors="ignore")
            # 从文件内容中提取 IP（每行最后一个空白分隔的 token）
            for line in content.splitlines():
                line = line.strip()
                if line:
                    ips.append(line.split()[-1])
        else:
            raise HTTPException(status_code=400, detail="请提供 IP 列表或上传文件")

    if not ips:
        raise HTTPException(status_code=400, detail="未识别到有效的 IP 地址")

    classification = classify_ips(ips)

    try:
        results = query_ips(ips)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IP 查询失败: {str(e)}")

    return {
        "summary": {
            "total": classification["total"],
            "unique": classification["unique"],
            "v4_count": len(classification["v4"]),
            "v6_count": len(classification["v6"]),
            "invalid_count": len(classification["invalid"]),
            "duplicate_count": classification["duplicate_count"],
        },
        "results": results,
    }
```

- [ ] **Step 2: 验证新增的 import 无冲突**

确认 `app/routers/api.py` 文件顶部已有 `UploadFile, File, Form` 的 import（第 4 行已有），以及 `Optional` import（第 7 行已有）。无需额外修改。

- [ ] **Step 3: 验证端点可访问**

```bash
# 启动后端
cd e:/github/report_tool && timeout 5 python main.py 2>&1 &
sleep 2
# 测试 API
curl -s -X POST http://localhost:8000/api/tools/ip-query \
  -H "Content-Type: application/json" \
  -d '{"ips": ["8.8.8.8"]}'
```

预期返回包含 `summary` 和 `results` 的 JSON。注意：需要先登录获取 session cookie。

- [ ] **Step 4: Commit**

```bash
git add app/routers/api.py
git commit -m "feat: add POST /api/tools/ip-query endpoint"
```

---

### Task 3: 前端 — IP 查询页面

**Files:**
- Create: `frontend/src/pages/Tools/IpQuery/index.tsx`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p e:/github/report_tool/frontend/src/pages/Tools/IpQuery
```

- [ ] **Step 2: 创建 `frontend/src/pages/Tools/IpQuery/index.tsx`**

```tsx
import { useState, useRef } from 'react'
import { Tabs, TabPane, TextArea, Button, Table, Spin, Toast, Tag, Upload } from '@douyinfe/semi-ui'
import IconSearch from '@douyinfe/semi-icons/lib/es/icons/IconSearch'
import IconUpload from '@douyinfe/semi-icons/lib/es/icons/IconUpload'
import IconDownload from '@douyinfe/semi-icons/lib/es/icons/IconDownload'
import api from '../../api'

interface IpResult {
  Ip: string
  Country: string
  Province: string
  City: string
  Operator: string
  Source: string
}

interface Summary {
  total: number
  unique: number
  v4_count: number
  v6_count: number
  invalid_count: number
  duplicate_count: number
}

// 从文本中提取 IP 列表
function parseIps(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => s.split(/\s+/).pop()!) // 取每行最后一个 token
    .filter(Boolean)
}

export default function IpQueryPage() {
  const [activeTab, setActiveTab] = useState<string>('paste')
  const [rawText, setRawText] = useState('')
  const [parsedIps, setParsedIps] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [results, setResults] = useState<IpResult[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 解析文本
  const handleParse = () => {
    const ips = parseIps(rawText)
    setParsedIps(ips)
    if (ips.length === 0) {
      Toast.warning('未识别到有效 IP 地址')
    } else {
      Toast.success(`识别到 ${ips.length} 个 IP 地址`)
    }
  }

  // 处理文件上传
  const handleFileUpload = async ({ file }: { file: File }) => {
    const text = await file.text()
    const ips = parseIps(text)
    setParsedIps(ips)
    if (ips.length === 0) {
      Toast.warning('文件中未识别到有效 IP 地址')
    } else {
      Toast.success(`从文件中识别到 ${ips.length} 个 IP 地址`)
    }
    return { autoRemove: true }
  }

  // 开始查询
  const handleQuery = async () => {
    if (parsedIps.length === 0) {
      Toast.warning('请先输入 IP 地址或上传文件')
      return
    }

    setLoading(true)
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)

    try {
      const resp = await api.post('/api/tools/ip-query', { ips: parsedIps }, { timeout: 330_000 })
      setResults(resp.data.results)
      setSummary(resp.data.summary)
      Toast.success(`查询完成，共 ${resp.data.results.length} 条结果`)
    } catch (err: any) {
      Toast.error(err?.response?.data?.detail || err?.message || '查询失败')
    } finally {
      setLoading(false)
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }

  // 导出 CSV
  const handleExport = () => {
    if (results.length === 0) return
    const header = 'IP\t国家\t省份\t城市\t运营商\t来源'
    const rows = results.map(r =>
      `${r.Ip}\t${r.Country}\t${r.Province}\t${r.City}\t${r.Operator}\t${r.Source}`
    )
    const csv = [header, ...rows].join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ip_result_${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const columns = [
    { title: 'IP', dataIndex: 'Ip', sorter: (a: IpResult, b: IpResult) => a.Ip.localeCompare(b.Ip) },
    { title: '国家', dataIndex: 'Country', sorter: true },
    { title: '省份', dataIndex: 'Province', sorter: true },
    { title: '城市', dataIndex: 'City', sorter: true },
    { title: '运营商', dataIndex: 'Operator', sorter: true },
    {
      title: '来源',
      dataIndex: 'Source',
      render: (text: string) => text ? <Tag size="small">{text}</Tag> : null,
    },
  ]

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return m > 0 ? `${m}分${sec}秒` : `${sec}秒`
  }

  return (
    <div>
      {/* 输入区域 */}
      <div style={{
        background: '#fff',
        borderRadius: 8,
        padding: 24,
        marginBottom: 16,
      }}>
        <h3 style={{ margin: '0 0 16px 0' }}>IP 批量查询</h3>
        <Tabs activeKey={activeTab} onChange={setActiveTab as any}>
          <TabPane tab="粘贴文本" itemKey="paste">
            <TextArea
              value={rawText}
              onChange={setRawText}
              placeholder="粘贴 IP 地址，每行一个，支持换行/空格/逗号分隔&#10;例如：&#10;8.8.8.8&#10;2001:db8::1&#10;192.168.1.1"
              rows={8}
              style={{ marginBottom: 12 }}
            />
            <Button onClick={handleParse} icon={<IconSearch />}>
              解析 IP 列表
            </Button>
          </TabPane>
          <TabPane tab="上传文件" itemKey="upload">
            <Upload
              action=""
              customRequest={({ file }: any) => handleFileUpload({ file })}
              accept=".txt,.csv"
              limit={1}
              style={{ marginBottom: 12 }}
            >
              <Button icon={<IconUpload />}>选择文件（.txt / .csv）</Button>
            </Upload>
            <p style={{ color: '#94a3b8', fontSize: 13 }}>
              文件每行一个 IP 地址，支持空格分隔的内容（取每行最后一个字段）
            </p>
          </TabPane>
        </Tabs>
      </div>

      {/* 统计 + 查询按钮 */}
      {parsedIps.length > 0 && (
        <div style={{
          background: '#fff',
          borderRadius: 8,
          padding: 24,
          marginBottom: 16,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 16,
        }}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Tag color="blue" size="large">共 {parsedIps.length} 个 IP</Tag>
            {summary && (
              <>
                <Tag color="green" size="large">v4: {summary.v4_count}</Tag>
                <Tag color="purple" size="large">v6: {summary.v6_count}</Tag>
                {summary.invalid_count > 0 && (
                  <Tag color="red" size="large">无效: {summary.invalid_count}</Tag>
                )}
              </>
            )}
          </div>
          <Button
            type="primary"
            size="large"
            icon={<IconSearch />}
            loading={loading}
            onClick={handleQuery}
            style={{ minWidth: 120 }}
          >
            开始查询
          </Button>
        </div>
      )}

      {/* 加载状态 */}
      {loading && (
        <div style={{
          background: '#fff',
          borderRadius: 8,
          padding: 48,
          textAlign: 'center',
          marginBottom: 16,
        }}>
          <Spin size="large" />
          <p style={{ marginTop: 16, color: '#64748b' }}>
            正在查询 {parsedIps.length} 个 IP 地址…（已用 {formatTime(elapsed)}）
          </p>
        </div>
      )}

      {/* 结果表格 */}
      {results.length > 0 && !loading && (
        <div style={{
          background: '#fff',
          borderRadius: 8,
          padding: 24,
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
          }}>
            <h3 style={{ margin: 0 }}>查询结果（{results.length} 条）</h3>
            <Button icon={<IconDownload />} onClick={handleExport}>
              导出 CSV
            </Button>
          </div>
          <Table
            columns={columns}
            dataSource={results}
            pagination={{ pageSize: 100 }}
            rowKey="Ip"
            size="small"
          />
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Tools/IpQuery/index.tsx
git commit -m "feat: add IpQuery page with paste and file upload input modes"
```

---

### Task 4: 前端 — 路由和菜单注册

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/MainLayout.tsx`

- [ ] **Step 1: 在 `App.tsx` 中添加路由**

在 import 区域（第 13 行 `ChangePasswordPage` 之后）添加：

```tsx
import IpQueryPage from './pages/Tools/IpQuery'
```

在路由区域（第 81 行 `change-password` 路由之前）添加：

```tsx
        <Route path="tools/ip-query" element={<IpQueryPage />} />
```

最终 `App.tsx` 变更如下：

**Import 区（第 14 行插入新 import）：**
```tsx
import ChangePasswordPage from './pages/ChangePassword'
import IpQueryPage from './pages/Tools/IpQuery'
```

**路由区（在 `admin/:datasetKey` 之后、`change-password` 之前）：**
```tsx
        <Route path="admin/:datasetKey" element={<AdminPage />} />
        <Route path="tools/ip-query" element={<IpQueryPage />} />
        <Route path="change-password" element={<ChangePasswordPage />} />
```

- [ ] **Step 2: 在 `MainLayout.tsx` 中添加导航菜单**

**新增 icon import（第 14 行 `IconCalendar` 之后）：**
```tsx
import IconCalendar from '@douyinfe/semi-icons/lib/es/icons/IconCalendar'
import IconTick from '@douyinfe/semi-icons/lib/es/icons/IconTick'
import IconSearch from '@douyinfe/semi-icons/lib/es/icons/IconSearch'
```

**更新 breadcrumb 逻辑（第 30-31 行 area）：**
```tsx
  const isDailyReport = location.pathname.startsWith('/daily-report')
  const isTools = location.pathname.startsWith('/tools')
  const currentModule = isTools ? '富强专用工具' : (isDailyReport ? '安全日报' : '主机预警')
```

**在 `navItems` 数组中新增顶层分组（第 57 行 `daily-report` 分组之后、`settings` 分组之前）：**
```tsx
    {
      itemKey: 'tools',
      text: '富强专用工具',
      icon: <IconTick />,
      items: [
        { itemKey: '/tools/ip-query', text: 'IP批量查询', icon: <IconSearch /> },
      ],
    },
```

**更新 `defaultOpenKeys`（第 129 行）：**
```tsx
          defaultOpenKeys={['host-alert', 'daily-report', 'tools']}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout/MainLayout.tsx
git commit -m "feat: add /tools/ip-query route and 富强专用工具 nav menu"
```

---

### Task 5: 构建并验证

**Files:** 无新建

- [ ] **Step 1: 构建前端**

```bash
cd e:/github/report_tool/frontend && npm run build
```

- [ ] **Step 2: 启动后端**

```bash
cd e:/github/report_tool && python main.py
```

- [ ] **Step 3: 浏览器验证**

打开 `http://localhost:8000`，登录后检查：
1. 侧边栏出现"富强专用工具"菜单分组（含"IP批量查询"子菜单）
2. 点击进入页面，粘贴几个 IP 测试查询
3. 测试文件上传模式
4. 测试 CSV 导出功能
5. 验证面包屑头部显示"富强专用工具"
6. 验证无数据时不崩溃（空输入、无效 IP）

- [ ] **Step 4: Commit（如有修改）**

```bash
git add -A
git commit -m "chore: build frontend with IP query tool"
```
