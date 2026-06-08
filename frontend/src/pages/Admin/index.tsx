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
  template_filename: string
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
  }, [datasetKey])

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
      await api.post(`/api/admin/${datasetKey}/import`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      Toast.success('导入成功')
      fetchData()
    } catch {
      Toast.error('导入失败')
    }
  }

  if (!config) {
    return <div>未知数据集</div>
  }

  const columns = [
    ...config.columns.map(([key, label]) => ({
      title: label,
      dataIndex: key,
      key,
    })),
    {
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
    },
  ]

  return (
    <div>
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
          <Button icon={<IconDownload />} onClick={() => window.open(`/static/import-templates/${config.template_filename}`)}>
            下载模板
          </Button>
          <Button type="primary" icon={<IconPlus />} onClick={handleAdd}>
            新增
          </Button>
        </div>
      </div>

      <Table
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          pageSize: 20,
          showTotal: true,
          onPageChange: (page) => fetchData(page, searchQuery),
        }}
      />

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
    </div>
  )
}
