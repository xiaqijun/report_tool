import { useState, useEffect } from 'react'
import { Table, Button, Input, Toast, Popconfirm, Typography, Modal, Tag, Space, TextArea, Spin } from '@douyinfe/semi-ui'
import { IconSearch, IconDelete, IconDownload, IconMail } from '@douyinfe/semi-icons'
import api from '../../api'

const { Text } = Typography

interface HistoryRecord {
  batch_code: string
  created_at: string
  source_file_name: string
  operator_name: string
  online_unprotected_count: number
  agent_missing_count: number
  protection_interrupted_count: number
  missing_owner_count: number
}

export default function HistoryPage() {
  const [data, setData] = useState<HistoryRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })

  const [emailModalVisible, setEmailModalVisible] = useState(false)
  const [sending, setSending] = useState(false)
  const [selectedBatch, setSelectedBatch] = useState<string>('')
  const [ownerEmails, setOwnerEmails] = useState<any[]>([])
  const [selectedEmails, setSelectedEmails] = useState<string[]>([])
  const [manualEmails, setManualEmails] = useState('')
  const [ccEmails, setCcEmails] = useState('')

  // Preview state
  const [previewVisible, setPreviewVisible] = useState(false)
  const [previewHtml, setPreviewHtml] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)

  const fetchData = async (page = 1, q = '') => {
    setLoading(true)
    try {
      const response = await api.get('/api/history', { params: { page, q } })
      setData(response.data.records)
      setPagination({ ...pagination, current: response.data.page, total: response.data.total })
    } catch {
      Toast.error('获取历史记录失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    fetchOwnerEmails()
  }, [])

  const fetchOwnerEmails = async () => {
    try {
      const response = await api.get('/api/admin/owner-emails', { params: { page: 1 } })
      setOwnerEmails(response.data.records || [])
    } catch {
      // ignore
    }
  }

  const handleDelete = async (batchCode: string) => {
    try {
      await api.delete(`/api/history/${batchCode}`)
      Toast.success('删除成功')
      fetchData(pagination.current, searchQuery)
    } catch {
      Toast.error('删除失败')
    }
  }

  const handleOpenEmailModal = async (batchCode: string) => {
    setSelectedBatch(batchCode)
    setSelectedEmails([])
    // Load default recipients from email settings
    try {
      const res = await api.get('/api/email/settings')
      const s = res.data.settings || {}
      setManualEmails(s.default_to_list || '')
      setCcEmails(s.default_cc_list || '')
    } catch {
      setManualEmails('')
      setCcEmails('')
    }
    setEmailModalVisible(true)
  }

  const handlePreview = async (batchCode: string) => {
    setPreviewLoading(true)
    setPreviewVisible(true)
    try {
      const response = await api.post('/api/email/preview', { batch_code: batchCode })
      setPreviewHtml(response.data.html || '<p>预览生成失败</p>')
    } catch {
      Toast.error('预览失败')
      setPreviewVisible(false)
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleSendEmail = async () => {
    const allEmails = [...selectedEmails]
    if (manualEmails.trim()) {
      const manual = manualEmails
        .split(/[,;，；\n]+/)
        .map((e) => e.trim())
        .filter((e) => e && e.includes('@'))
      allEmails.push(...manual)
    }

    const uniqueEmails = [...new Set(allEmails)]

    if (uniqueEmails.length === 0) {
      Toast.warning('请至少输入一个收件人')
      return
    }

    const ccList = ccEmails
      ? ccEmails
          .split(/[,;，；\n]+/)
          .map((e) => e.trim())
          .filter((e) => e && e.includes('@'))
      : []

    setSending(true)
    try {
      const result = await api.post('/api/send-warning-email', {
        to_list: uniqueEmails,
        cc_list: ccList.length > 0 ? ccList : [],
        batch_code: selectedBatch,
      })
      if (result.data.success) {
        Toast.success(result.data.message)
        setEmailModalVisible(false)
      } else {
        Toast.error(result.data.message)
      }
    } catch (err: any) {
      Toast.error(err?.response?.data?.detail || '发送失败')
    } finally {
      setSending(false)
    }
  }

  const toggleOwnerEmail = (email: string) => {
    setSelectedEmails((prev) =>
      prev.includes(email) ? prev.filter((e) => e !== email) : [...prev, email]
    )
  }

  const columns = [
    { title: '生成时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
    { title: '批次号', dataIndex: 'batch_code', key: 'batch_code', width: 140 },
    { title: '操作人', dataIndex: 'operator_name', key: 'operator_name', width: 80 },
    { title: '在线未防护', dataIndex: 'online_unprotected_count', key: 'online_unprotected_count', width: 90, align: 'center' as const },
    { title: '未安装', dataIndex: 'agent_missing_count', key: 'agent_missing_count', width: 70, align: 'center' as const },
    { title: '防护中断', dataIndex: 'protection_interrupted_count', key: 'protection_interrupted_count', width: 90, align: 'center' as const },
    { title: '缺失负责人', dataIndex: 'missing_owner_count', key: 'missing_owner_count', width: 90, align: 'center' as const },
    {
      title: '操作',
      key: 'action',
      width: 350,
      render: (_: any, record: HistoryRecord) => (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <Button size="small" icon={<IconDownload />} onClick={() => window.open(`/download/${record.batch_code}/online-unprotected`)}>
            未防护
          </Button>
          <Button size="small" icon={<IconDownload />} onClick={() => window.open(`/download/${record.batch_code}/agent-missing`)}>
            未安装
          </Button>
          <Button size="small" icon={<IconDownload />} onClick={() => window.open(`/download/${record.batch_code}/protection-interrupted`)}>
            防护中断
          </Button>
          <Button size="small" type="secondary" icon={<IconMail />} onClick={() => handleOpenEmailModal(record.batch_code)}>
            发送邮件
          </Button>
          <Button size="small" type="tertiary" onClick={() => handlePreview(record.batch_code)}>
            预览邮件
          </Button>
          <Popconfirm
            title="确定删除此记录？"
            onConfirm={() => handleDelete(record.batch_code)}
          >
            <Button size="small" type="danger" icon={<IconDelete />}>删除</Button>
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Input
            placeholder="搜索..."
            value={searchQuery}
            onChange={(v) => setSearchQuery(v)}
            prefix={<IconSearch />}
            style={{ width: 300 }}
          />
          <Button onClick={() => fetchData(1, searchQuery)}>搜索</Button>
        </div>
      </div>
      <Table
        columns={columns}
        dataSource={data}
        rowKey="batch_code"
        loading={loading}
        style={{ width: '100%' }}
        scroll={{ x: 1200 }}
        pagination={{
          ...pagination,
          showTotal: true,
          onPageChange: (page) => fetchData(page, searchQuery),
        }}
      />

      {/* 发送邮件弹窗 */}
      <Modal
        title="发送预警邮件"
        visible={emailModalVisible}
        onCancel={() => setEmailModalVisible(false)}
        footer={
          <Space>
            <Button onClick={() => setEmailModalVisible(false)}>取消</Button>
            <Button type="primary" loading={sending} icon={<IconMail />} onClick={handleSendEmail}>
              发送
            </Button>
          </Space>
        }
        style={{ width: 640 }}
      >
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>从责任人邮箱选择：</Text>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {ownerEmails.length > 0 ? (
              ownerEmails.map((item) => (
                <Tag
                  key={item.email}
                  style={{
                    cursor: 'pointer',
                    border: selectedEmails.includes(item.email) ? '1px solid #0077fa' : '1px solid #d9d9d9',
                    backgroundColor: selectedEmails.includes(item.email) ? '#e6f4ff' : '#fff',
                    color: selectedEmails.includes(item.email) ? '#0077fa' : '#333',
                  }}
                  onClick={() => toggleOwnerEmail(item.email)}
                >
                  {item.owner_name || item.email}
                </Tag>
              ))
            ) : (
              <Text type="secondary">暂无责任人邮箱数据</Text>
            )}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>手动输入收件人：</Text>
          <TextArea
            placeholder="输入邮箱地址，多个用逗号、分号或换行分隔"
            rows={3}
            value={manualEmails}
            onChange={setManualEmails}
          />
        </div>

        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>抄送（可选）：</Text>
          <TextArea
            placeholder="输入邮箱地址，多个用逗号、分号或换行分隔"
            rows={2}
            value={ccEmails}
            onChange={setCcEmails}
          />
        </div>

        <Text type="secondary">
          邮件将自动对比一周前的数据，生成"同上周相比"的变化统计。
        </Text>
      </Modal>

      {/* 邮件预览弹窗 */}
      <Modal
        title="邮件预览"
        visible={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={
          <Button onClick={() => setPreviewVisible(false)}>关闭</Button>
        }
        style={{ width: 900, top: 20 }}
      >
        {previewLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
            <div style={{ marginTop: 16 }}>正在生成预览...</div>
          </div>
        ) : (
          <div
            style={{ border: '1px solid #eee', borderRadius: 4, padding: 16, maxHeight: '70vh', overflow: 'auto' }}
            dangerouslySetInnerHTML={{ __html: previewHtml.replace(/width="(\d+)"/g, 'width="100%"').replace(/max-width:\s*\d+px/g, 'max-width: 100%') }}
          />
        )}
      </Modal>
    </div>
  )
}
