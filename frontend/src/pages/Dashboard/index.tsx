import { useState } from 'react'
import { Card, Row, Col, Button, Toast, Typography, Upload } from '@douyinfe/semi-ui'
import { IconUpload, IconDownload, IconAlertCircle } from '@douyinfe/semi-icons'
import api from '../../api'

const { Title, Text } = Typography

interface DashboardData {
  result: {
    batch_code: string
    counts: {
      online_unprotected: number
      agent_missing: number
      protection_interrupted: number
      missing_owner: number
    }
    previews: Record<string, any[]>
    missing_owner_projects: string[]
  } | null
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData>({ result: null })
  const [loading, setLoading] = useState(false)

  const handleUpload = async (file: any) => {
    setLoading(true)
    try {
      // Semi UI Upload wraps the file; get the raw File object
      const rawFile = file?.fileInstance || file?.originFileObj || file
      const formData = new FormData()
      formData.append('asset_file', rawFile)
      const response = await api.post('/api/generate', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setData(response.data)
      Toast.success('报告生成成功')
    } catch (error: any) {
      Toast.error(error.response?.data?.detail || '生成失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <Card style={{ borderRadius: 12 }}>
        <Title heading={5} style={{ margin: 0 }}>生成预警清单</Title>
        <Text type="secondary" style={{ marginTop: 4, display: 'block' }}>
          支持格式：CSV / XLSX / XLSM
        </Text>
        <div style={{ marginTop: 16 }}>
          <Upload
            accept=".csv,.xlsx,.xlsm"
            showUploadList={false}
            customRequest={({ file }) => handleUpload(file)}
          >
            <Button icon={<IconUpload />} loading={loading} type="primary">
              选择服务器资产总表
            </Button>
          </Upload>
        </div>
      </Card>

      {data.result && (
        <>
          <Row gutter={16}>
            {[
              { label: '在线未防护', value: data.result.counts.online_unprotected, color: '#0077fa' },
              { label: 'Agent 未安装', value: data.result.counts.agent_missing, color: '#fa8c16' },
              { label: '防护中断', value: data.result.counts.protection_interrupted, color: '#ff4d4f' },
              { label: '缺失负责人', value: data.result.counts.missing_owner, color: '#ff4d4f' },
            ].map((item) => (
              <Col span={6} key={item.label}>
                <Text type="secondary" style={{ fontSize: 13 }}>{item.label}</Text>
                <Title heading={3} style={{ color: item.color, margin: '4px 0 0' }}>
                  {item.value}
                </Title>
              </Col>
            ))}
          </Row>

          <div>
            <Title heading={6} style={{ margin: '0 0 12px' }}>结果下载</Title>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Button icon={<IconDownload />} onClick={() => window.open(`/download/${data.result!.batch_code}/online-unprotected`)}>
                在线未防护
              </Button>
              <Button icon={<IconDownload />} onClick={() => window.open(`/download/${data.result!.batch_code}/agent-missing`)}>
                未安装
              </Button>
              <Button icon={<IconDownload />} onClick={() => window.open(`/download/${data.result!.batch_code}/protection-interrupted`)}>
                防护中断
              </Button>
            </div>
            {data.result.missing_owner_projects?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Text type="warning">
                  <IconAlertCircle /> 未匹配负责人项目：{data.result.missing_owner_projects.join('、')}
                </Text>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
