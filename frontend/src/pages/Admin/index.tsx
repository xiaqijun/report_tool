import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Table, Button, Modal, Form, Input, Toast, Popconfirm, Typography, Upload } from '@douyinfe/semi-ui'
import { IconPlus, IconEdit, IconDelete, IconUpload, IconDownload, IconSearch } from '@douyinfe/semi-icons'
import api from '../../api'

const { Title } = Typography

interface DataItem {
  id: number
  [key: string]: any
}

interface DatasetConfig {
  title: string
  columns: [string, string][]
  template_filename?: string
  readOnly?: boolean
  importHint?: string
}

const datasetConfigs: Record<string, DatasetConfig> = {
  'owner-mappings': {
    title: '项目负责人',
    columns: [['enterprise_project', '企业项目'], ['owner_name', '负责人']],
    template_filename: '项目负责人导入模板.xlsx',
  },
  'owner-emails': {
    title: '责任人邮箱',
    columns: [['owner_name', '责任人'], ['email', '邮箱']],
    template_filename: '责任人邮箱导入模板.xlsx',
  },
  'unquota-hosts': {
    title: '未配额主机',
    columns: [['server_id', '服务器ID'], ['ip_address', 'IP地址'], ['server_name', '服务器名称'], ['note', '备注']],
    template_filename: '未配额主机导入模板.xlsx',
  },
  'deferred-install-hosts': {
    title: '暂不安装主机',
    columns: [['server_id', '服务器ID'], ['ip_address', 'IP地址'], ['server_name', '服务器名称'], ['note', '备注']],
    template_filename: '暂不安装主机导入模板.xlsx',
  },
  'unprotected-container-nodes': {
    title: '未防护容器节点',
    columns: [
      ['server_name', '服务器名称'],
      ['server_id', '服务器ID'],
      ['ip_address', 'IP地址'],
      ['cluster_name', '集群名称'],
      ['agent_status', 'Agent状态'],
      ['protection_status', '防护状态'],
      ['server_status', '服务器状态'],
      ['enterprise_project', '企业项目'],
      ['provider', '服务商'],
      ['protection_version', '防护版本'],
      ['updated_at', '导入时间'],
    ],
    readOnly: true,
    importHint: '导入节点列表后，系统仅保留“防护状态=未防护”且“存在容器进程=是”的节点。',
  },
}

export default function AdminPage() {
  const { datasetKey } = useParams<{ datasetKey: string }>()
  const [data, setData] = useState<DataItem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<DataItem | null>(null)
  const [formApi, setFormApi] = useState<any>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [pagination, setPagination] = useState({ current: 1, total: 0 })
  const [tencentDocsSettings, setTencentDocsSettings] = useState<any>(null)
  const [tencentDocsModalVisible, setTencentDocsModalVisible] = useState(false)
  const [tencentDocsFormApi, setTencentDocsFormApi] = useState<any>(null)
  const [tencentDocsSyncing, setTencentDocsSyncing] = useState(false)

  const config = datasetKey ? datasetConfigs[datasetKey] : null

  const fetchData = async (page = 1, q = '') => {
    if (!datasetKey) return
    setLoading(true)
    try {
      const response = await api.get(`/api/admin/${datasetKey}`, { params: { page, q } })
      setData(response.data.records)
      setPagination({ current: response.data.page, total: response.data.total })
    } catch {
      Toast.error('获取数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    if (datasetKey === 'unprotected-container-nodes') {
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
    }
  }, [datasetKey])

  const fetchTencentDocsSettings = async () => {
    try {
      const response = await api.get('/api/tencent-docs/settings')
      setTencentDocsSettings(response.data.settings)
    } catch {
      Toast.error('获取腾讯文档配置失败')
    }
  }

  const handleAdd = () => {
    setEditingRecord(null)
    setModalVisible(true)
  }

  const handleEdit = (record: DataItem) => {
    setEditingRecord(record)
    setModalVisible(true)
  }

  const handleDelete = async (id: number) => {
    if (!datasetKey) return
    try {
      await api.delete(`/api/admin/${datasetKey}/${id}`)
      Toast.success('删除成功')
      fetchData(pagination.current, searchQuery)
    } catch {
      Toast.error('删除失败')
    }
  }

  const handleSave = async (values: any) => {
    if (!datasetKey) return
    try {
      if (editingRecord) {
        await api.put(`/api/admin/${datasetKey}/${editingRecord.id}`, values)
        Toast.success('更新成功')
      } else {
        await api.post(`/api/admin/${datasetKey}`, values)
        Toast.success('添加成功')
      }
      setModalVisible(false)
      fetchData(pagination.current, searchQuery)
    } catch {
      Toast.error('保存失败')
    }
  }

  const handleImport = async (file: any) => {
    if (!datasetKey) return
    try {
      const rawFile = file?.fileInstance || file?.originFileObj || file
      const formData = new FormData()
      formData.append('import_file', rawFile)
      const response = await api.post(`/api/admin/${datasetKey}/import`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      Toast.success(`导入成功，共 ${response.data.count ?? 0} 条`)
      fetchData()
    } catch {
      Toast.error('导入失败')
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

  const handleTencentDocsAuthorize = () => {
    if (!tencentDocsSettings?.client_id || !tencentDocsSettings?.has_client_secret || !tencentDocsSettings?.redirect_uri) {
      Toast.warning('请先完成腾讯文档应用配置')
      setTencentDocsModalVisible(true)
      return
    }
    window.location.href = '/api/tencent-docs/authorize'
  }

  const handleTencentDocsSync = async () => {
    setTencentDocsSyncing(true)
    try {
      const response = await api.post('/api/tencent-docs/sync')
      Toast.success(`腾讯文档同步成功，共 ${response.data.count ?? 0} 条`)
      await Promise.all([fetchData(), fetchTencentDocsSettings()])
    } catch (error: any) {
      Toast.error(error.response?.data?.detail || '腾讯文档同步失败')
    } finally {
      setTencentDocsSyncing(false)
    }
  }

  if (!config) {
    return <div>未知数据集</div>
  }

  const columns: any[] = [
    ...config.columns.map(([key, label]) => ({
      title: label,
      dataIndex: key,
      key,
    })),
  ]

  if (!config.readOnly) {
    columns.push({
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: DataItem) => (
        <div style={{ display: 'flex', gap: 8 }}>
          <Button size="small" icon={<IconEdit />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" type="danger" icon={<IconDelete />}>
              删除
            </Button>
          </Popconfirm>
        </div>
      ),
    })
  }

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title heading={4} style={{ margin: 0 }}>{config.title}</Title>
        {config.importHint && <div style={{ marginTop: 8, color: 'var(--semi-color-text-2)' }}>{config.importHint}</div>}
      </div>
      {datasetKey === 'unprotected-container-nodes' && (
        <div style={{ marginBottom: 16, padding: '12px 16px', borderRadius: 8, background: '#fff', border: '1px solid var(--semi-color-border)' }}>
          <strong>腾讯文档：</strong>
          <span style={{ marginLeft: 8 }}>{tencentDocsSettings?.authorized ? '已授权' : '未授权'}</span>
          {tencentDocsSettings?.last_sync_at && (
            <span style={{ marginLeft: 16, color: 'var(--semi-color-text-2)' }}>
              最近同步 {tencentDocsSettings.last_sync_at}，{tencentDocsSettings.last_sync_count ?? 0} 条
            </span>
          )}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Input
            placeholder="搜索..."
            value={searchQuery}
            onChange={(v) => setSearchQuery(v)}
            prefix={<IconSearch />}
            style={{ width: 250 }}
          />
          <Button onClick={() => fetchData(1, searchQuery)}>搜索</Button>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Upload
            accept=".xlsx,.xls,.csv"
            showUploadList={false}
            customRequest={({ file }) => handleImport(file)}
          >
            <Button icon={<IconUpload />}>导入数据</Button>
          </Upload>
          {datasetKey === 'unprotected-container-nodes' && (
            <>
              <Button onClick={() => setTencentDocsModalVisible(true)}>腾讯文档配置</Button>
              <Button onClick={handleTencentDocsAuthorize}>
                {tencentDocsSettings?.authorized ? '重新授权' : '腾讯文档授权'}
              </Button>
              <Button type="primary" loading={tencentDocsSyncing} onClick={handleTencentDocsSync}>
                同步腾讯文档
              </Button>
            </>
          )}
          {config.template_filename && (
            <Button icon={<IconDownload />} onClick={() => window.open(`/static/import-templates/${config.template_filename}`)}>
              下载模板
            </Button>
          )}
          {!config.readOnly && (
            <Button type="primary" icon={<IconPlus />} onClick={handleAdd}>
              新增
            </Button>
          )}
        </div>
      </div>

      <Table
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={loading}
        scroll={{ x: 'max-content' }}
        pagination={{
          ...pagination,
          pageSize: 20,
          showTotal: true,
          onPageChange: (page) => fetchData(page, searchQuery),
        }}
      />

      {!config.readOnly && (
        <Modal
          title={editingRecord ? '编辑记录' : '新增记录'}
          visible={modalVisible}
          onOk={() => formApi?.submitForm()}
          onCancel={() => setModalVisible(false)}
        >
          <Form
            initValues={editingRecord || {}}
            onSubmit={handleSave}
            getFormApi={(api) => setFormApi(api)}
          >
            {config.columns.map(([key, label]) => (
              <Form.Input key={key} field={key} label={label} />
            ))}
          </Form>
        </Modal>
      )}

      {datasetKey === 'unprotected-container-nodes' && (
        <Modal
          title="腾讯文档开放 API 配置"
          visible={tencentDocsModalVisible}
          onOk={() => tencentDocsFormApi?.submitForm()}
          onCancel={() => setTencentDocsModalVisible(false)}
          width={640}
        >
          <Form
            initValues={{ ...tencentDocsSettings, client_secret: '' }}
            onSubmit={handleSaveTencentDocsSettings}
            getFormApi={(formApi) => setTencentDocsFormApi(formApi)}
          >
            <Form.Input field="client_id" label="Client ID" rules={[{ required: true, message: '请输入 Client ID' }]} />
            <Form.Input
              field="client_secret"
              label="Client Secret"
              type="password"
              placeholder={tencentDocsSettings?.has_client_secret ? '已保存，留空表示不修改' : '请输入 Client Secret'}
            />
            <Form.Input
              field="redirect_uri"
              label="OAuth 回调地址"
              placeholder="https://你的域名/api/tencent-docs/callback"
              rules={[{ required: true, message: '请输入 HTTPS 回调地址' }]}
            />
            <Form.Input field="file_id" label="腾讯文档链接 / File ID" rules={[{ required: true, message: '请输入表格链接或 File ID' }]} />
            <Form.Input field="sheet_id" label="Sheet ID（可选）" placeholder="留空自动读取第一个工作表" />
            <Form.Input field="sheet_range" label="读取范围" placeholder="A1:T500" />
          </Form>
        </Modal>
      )}
    </div>
  )
}
