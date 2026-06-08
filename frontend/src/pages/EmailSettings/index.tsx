import { useState, useEffect } from 'react'
import { Form, Button, Card, Switch, Toast, Typography, Space } from '@douyinfe/semi-ui'
import { IconSave, IconMail } from '@douyinfe/semi-icons'
import api from '../../api'

const { Text } = Typography

export default function EmailSettingsPage() {
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState(false)
  const [formApi, setFormApi] = useState<any>(null)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const response = await api.get('/api/email/settings')
      if (response.data.settings) {
        formApi?.setValues(response.data.settings)
      }
    } catch {
      Toast.error('获取配置失败')
    }
  }

  const handleSubmit = async (values: any) => {
    setLoading(true)
    try {
      await api.post('/api/email/settings/save', values)
      Toast.success('保存成功')
      fetchData()
    } catch {
      Toast.error('保存失败')
    } finally {
      setLoading(false)
    }
  }

  const handleTest = async () => {
    const values = formApi?.getValues()
    if (!values?.smtp_host) {
      Toast.warning('请先填写SMTP服务器地址')
      return
    }
    setTesting(true)
    try {
      const result = await api.post('/api/email/test', values)
      if (result.data.success) {
        Toast.success(result.data.message)
      } else {
        Toast.error(result.data.message)
      }
    } catch {
      Toast.error('测试连接失败')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Text type="secondary">
          配置邮件发送的SMTP服务器信息。保存后即刻生效。可点击"测试连接"验证配置是否正确。
        </Text>
      </Card>

      <Form onSubmit={handleSubmit} getFormApi={(api) => setFormApi(api)}>
        <Card title="SMTP 服务器配置" style={{ marginBottom: 16 }}>
          <Form.Input field="smtp_host" label="SMTP 服务器" placeholder="smtp.qq.com" />
          <Form.InputNumber field="smtp_port" label="端口" placeholder="465" min={1} max={65535} />
          <Form.Input field="smtp_user" label="用户名" placeholder="your-email@qq.com" />
          <Form.Input field="smtp_password" label="密码 / 授权码" type="password" placeholder="留空则保留已保存的密码" />
          <Form.Input field="smtp_from" label="发件人地址" placeholder="留空则使用用户名" />
          <Form.Switch field="use_tls" label="使用 SSL/TLS" />
        </Card>

        <Card
          title="邮件主题配置"
          style={{ marginBottom: 16 }}
          headerExtraContent={
            <Text type="tertiary" style={{ fontSize: 12 }}>支持 {`{date}`} 占位符，自动替换为日期</Text>
          }
        >
          <Form.Input
            field="host_warning_subject"
            label="主机预警邮件主题"
            placeholder="【主机安全预警】主机安全Agent防护中断&未安装Agent风险预警 - {date}"
          />
          <Form.Input
            field="daily_report_subject"
            label="安全日报邮件主题"
            placeholder="【安全运营日报】{date}"
          />
          <Form.Input field="default_subject" label="默认邮件主题" placeholder="安全运营日报" />
        </Card>

        <Space>
          <Button type="primary" htmlType="submit" loading={loading} icon={<IconSave />}>
            保存配置
          </Button>
          <Button type="secondary" loading={testing} icon={<IconMail />} onClick={handleTest}>
            测试连接
          </Button>
        </Space>
      </Form>
    </div>
  )
}
