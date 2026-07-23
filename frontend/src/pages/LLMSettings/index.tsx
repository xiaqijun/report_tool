import { useState, useEffect } from 'react'
import { Form, Button, Card, Switch, Toast, Typography } from '@douyinfe/semi-ui'
import { IconSave } from '@douyinfe/semi-icons'
import api from '../../api'

const { Title, Text } = Typography

export default function LLMSettingsPage() {
  const [loading, setLoading] = useState(false)
  const [formApi, setFormApi] = useState<any>(null)
  const [configLoaded, setConfigLoaded] = useState(false)
  const [configComplete, setConfigComplete] = useState(false)

  useEffect(() => {
    if (formApi) fetchData()
  }, [formApi])

  const fetchData = async () => {
    try {
      const response = await api.get('/api/llm-settings')
      if (response.data.settings) {
        const settings = response.data.settings
        formApi.setValues(settings)
        setConfigComplete(Boolean(
          settings.enabled
          && settings.api_base_url
          && settings.model
          && response.data.api_key_configured
        ))
      }
      setConfigLoaded(true)
    } catch {
      Toast.error('获取配置失败')
    }
  }

  const handleSubmit = async (values: any) => {
    setLoading(true)
    try {
      await api.post('/api/llm-settings/save', values)
      Toast.success('保存成功')
      fetchData()
    } catch {
      Toast.error('保存失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Text type="secondary">
          配置日报顶部三段自动生成所使用的大模型连接信息。保存后即刻生效。
        </Text>
        {configLoaded && (
          <div style={{ marginTop: 8 }}>
            <Text type={configComplete ? 'success' : 'warning'}>
              {configComplete ? '当前配置完整，大模型生成已启用' : '当前配置未完整，大模型生成将使用本地兜底文案'}
            </Text>
          </div>
        )}
      </Card>

      <Form onSubmit={handleSubmit} getFormApi={(api) => setFormApi(api)}>
        <Card title="配置" style={{ marginBottom: 16 }}>
          <Form.Switch field="enabled" label="启用大模型生成" />
          <Form.Input field="api_base_url" label="API Base URL" placeholder="https://api.openai.com/v1" />
          <Form.Input field="model" label="模型名称" placeholder="gpt-4.1-mini" />
          <Form.Input field="api_key" label="API Key" type="password" placeholder="留空则保留已保存的 Key" />
          <Form.InputNumber field="timeout_seconds" label="超时时间（秒）" min={1} />
        </Card>

        <Button type="primary" htmlType="submit" loading={loading} icon={<IconSave />}>
          保存配置
        </Button>
      </Form>
    </div>
  )
}
