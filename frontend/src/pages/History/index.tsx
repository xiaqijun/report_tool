import { useState, useEffect } from 'react'
import { Table, Button, Input, Toast, Popconfirm, Typography, Modal, Space, TextArea, Spin, Form } from '@douyinfe/semi-ui'
import { IconSearch, IconDelete, IconDownload, IconMail, IconUpload } from '@douyinfe/semi-icons'
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
  tencent_online_unprotected_url?: string
  tencent_agent_missing_url?: string
  tencent_protection_interrupted_url?: string
  tencent_docs_synced_at?: string
}

export default function HistoryPage() {
  const [data, setData] = useState<HistoryRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })

  const [emailModalVisible, setEmailModalVisible] = useState(false)
  const [sending, setSending] = useState(false)
  const [selectedBatch, setSelectedBatch] = useState<string>('')
  const [manualEmails, setManualEmails] = useState('')
  const [ccEmails, setCcEmails] = useState('')
  // Preview state
  const [previewVisible, setPreviewVisible] = useState(false)
  const [previewHtml, setPreviewHtml] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [tencentDocsSettings, setTencentDocsSettings] = useState<any>(null)
  const [tencentDocsModalVisible, setTencentDocsModalVisible] = useState(false)
  const [tencentDocsFormApi, setTencentDocsFormApi] = useState<any>(null)
  const [syncingBatch, setSyncingBatch] = useState('')

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
    fetchTencentDocsSettings()
    const oauthStatus = new URLSearchParams(window.location.search).get('tencent_docs')
    if (oauthStatus === 'authorized') {
      Toast.success('腾讯文档授权成功')
    } else if (oauthStatus) {
      Toast.error('腾讯文档授权失败，请检查配置后重试')
    }
    if (oauthStatus) {
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  const fetchTencentDocsSettings = async () => {
    try {
      const response = await api.get('/api/tencent-docs/settings')
      setTencentDocsSettings(response.data.settings)
    } catch {
      Toast.error('获取腾讯文档配置失败')
    }
  }

  const handleSaveTencentDocsSettings = async (values: any) => {
    try {
      const response = await api.post('/api/tencent-docs/settings', values)
      setTencentDocsSettings(response.data.settings)
      setTencentDocsModalVisible(false)
      Toast.success('腾讯文档配置已保存')
    } catch (error: any) {
      Toast.error(error.response?.data?.detail || '保存腾讯文档配置失败')
    }
  }

  const handleTencentDocsSync = async (batchCode: string) => {
    if (!tencentDocsSettings?.authorized) {
      Toast.warning('请先完成腾讯文档授权')
      return
    }
    if (!tencentDocsSettings?.target_document_url) {
      Toast.warning('请先配置目标腾讯表格链接')
      setTencentDocsModalVisible(true)
      return
    }
    setSyncingBatch(batchCode)
    try {
      await api.post(`/api/history/${batchCode}/tencent-docs/sync`)
      Toast.success('三个报表已覆盖写入目标腾讯表格')
      await fetchData(pagination.current, searchQuery)
    } catch (error: any) {
      Toast.error(error.response?.data?.detail || '同步腾讯文档失败')
    } finally {
      setSyncingBatch('')
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
    const uniqueEmails = manualEmails
      ? manualEmails
          .split(/[,;，；\n]+/)
          .map((e) => e.trim())
          .filter((e) => e && e.includes('@'))
      : []

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

  const columns = [
    { title: '生成时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
    { title: '批次号', dataIndex: 'batch_code', key: 'batch_code', width: 140 },
    { title: '操作人', dataIndex: 'operator_name', key: 'operator_name', width: 80 },
    { title: '在线未防护', dataIndex: 'online_unprotected_count', key: 'online_unprotected_count', width: 90, align: 'center' as const },
    { title: '未安装', dataIndex: 'agent_missing_count', key: 'agent_missing_count', width: 70, align: 'center' as const },
    { title: '防护中断', dataIndex: 'protection_interrupted_count', key: 'protection_interrupted_count', width: 90, align: 'center' as const },
    { title: '缺失负责人', dataIndex: 'missing_owner_count', key: 'missing_owner_count', width: 90, align: 'center' as const },
    {
      title: '腾讯文档',
      key: 'tencent_docs',
      width: 230,
      render: (_: any, record: HistoryRecord) => {
        const links = [
          ['未防护', record.tencent_online_unprotected_url],
          ['未安装', record.tencent_agent_missing_url],
          ['防护中断', record.tencent_protection_interrupted_url],
        ]
        const synced = links.every(([, url]) => Boolean(url))
        if (!synced) {
          return (
            <Button
              size="small"
              type="primary"
              icon={<IconUpload />}
              loading={syncingBatch === record.batch_code}
              onClick={() => handleTencentDocsSync(record.batch_code)}
            >
              同步到目标文档
            </Button>
          )
        }
        return (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {links.map(([label, url]) => (
              <Button key={label} size="small" onClick={() => window.open(url, '_blank')}>
                {label}
              </Button>
            ))}
            <Button
              size="small"
              type="secondary"
              loading={syncingBatch === record.batch_code}
              onClick={() => handleTencentDocsSync(record.batch_code)}
            >
              重新同步
            </Button>
          </div>
        )
      },
    },
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

  const tencentDocsTokenExpiresAt = String(tencentDocsSettings?.token_expires_at || '')
    .replace('T', ' ')
    .slice(0, 16)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Text>腾讯文档：{tencentDocsSettings?.authorized ? '已配置' : '未配置'}</Text>
          <Button onClick={() => setTencentDocsModalVisible(true)}>手工令牌配置</Button>
          {tencentDocsSettings?.target_document_url && (
            <Button onClick={() => window.open(tencentDocsSettings.target_document_url, '_blank')}>打开目标文档</Button>
          )}
          {tencentDocsTokenExpiresAt && (
            <Text type="tertiary">有效至 {tencentDocsTokenExpiresAt}</Text>
          )}
        </div>
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

      <Modal
        title="腾讯文档手工令牌配置"
        visible={tencentDocsModalVisible}
        onOk={() => tencentDocsFormApi?.submitForm()}
        onCancel={() => setTencentDocsModalVisible(false)}
        width={640}
      >
        <Form
          initValues={{ ...tencentDocsSettings, access_token: '', open_id: '' }}
          onSubmit={handleSaveTencentDocsSettings}
          getFormApi={(formApi) => setTencentDocsFormApi(formApi)}
        >
          <Form.Input field="client_id" label="Client ID" rules={[{ required: true, message: '请输入 Client ID' }]} />
          <Form.Input
            field="access_token"
            label="Access Token"
            type="password"
            placeholder={tencentDocsSettings?.authorized ? '已保存，留空不修改' : '请输入 Access Token'}
            rules={[{ required: !tencentDocsSettings?.authorized, message: '请输入 Access Token' }]}
          />
          <Form.Input
            field="open_id"
            label="Open ID"
            type="password"
            placeholder={tencentDocsSettings?.authorized ? '已保存，留空不修改' : '请输入 Open ID'}
            rules={[{ required: !tencentDocsSettings?.authorized, message: '请输入 Open ID' }]}
          />
          <Form.Input
            field="target_document_url"
            label="目标腾讯表格链接"
            placeholder="https://docs.qq.com/sheet/...?tab=..."
            rules={[{ required: true, message: '请输入目标腾讯表格链接' }]}
          />
        </Form>
      </Modal>

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
          <Text strong style={{ display: 'block', marginBottom: 8 }}>收件人：</Text>
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
