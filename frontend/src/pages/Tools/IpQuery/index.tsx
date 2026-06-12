import { useState, useRef } from 'react'
import { Tabs, TabPane, TextArea, Button, Table, Spin, Toast, Tag, Upload } from '@douyinfe/semi-ui'
import IconSearch from '@douyinfe/semi-icons/lib/es/icons/IconSearch'
import IconUpload from '@douyinfe/semi-icons/lib/es/icons/IconUpload'
import IconDownload from '@douyinfe/semi-icons/lib/es/icons/IconDownload'
import api from '../../../api'

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

// Extract IPs from text (supports newline, comma, space separation)
function parseIps(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => s.split(/\s+/).pop()!) // Take the last whitespace-delimited token
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

  // Parse text input
  const handleParse = () => {
    const ips = parseIps(rawText)
    setParsedIps(ips)
    if (ips.length === 0) {
      Toast.warning('未识别到有效 IP 地址')
    } else {
      Toast.success(`识别到 ${ips.length} 个 IP 地址`)
    }
  }

  // Handle file upload
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

  // Start query
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

  // Export CSV
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
      {/* Input area */}
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

      {/* Stats + Query button */}
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

      {/* Loading state */}
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

      {/* Results table */}
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
