import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Nav, Button, Avatar, Dropdown } from '@douyinfe/semi-ui'
import IconHome from '@douyinfe/semi-icons/lib/es/icons/IconHome'
import IconHistory from '@douyinfe/semi-icons/lib/es/icons/IconHistory'
import IconFile from '@douyinfe/semi-icons/lib/es/icons/IconFile'
import IconUserGroup from '@douyinfe/semi-icons/lib/es/icons/IconUserGroup'
import IconSetting from '@douyinfe/semi-icons/lib/es/icons/IconSetting'
import IconLock from '@douyinfe/semi-icons/lib/es/icons/IconLock'
import IconUnlock from '@douyinfe/semi-icons/lib/es/icons/IconUnlock'
import IconMenu from '@douyinfe/semi-icons/lib/es/icons/IconMenu'
import IconChevronDown from '@douyinfe/semi-icons/lib/es/icons/IconChevronDown'
import IconBell from '@douyinfe/semi-icons/lib/es/icons/IconBell'
import IconCalendar from '@douyinfe/semi-icons/lib/es/icons/IconCalendar'
import IconTick from '@douyinfe/semi-icons/lib/es/icons/IconTick'
import IconSearch from '@douyinfe/semi-icons/lib/es/icons/IconSearch'
import { useAuthStore } from '../../store/auth'

const { Header, Sider, Content } = Layout

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const isDailyReport = location.pathname.startsWith('/daily-report')
  const isTools = location.pathname.startsWith('/tools')
  const currentModule = isTools ? '富强专用工具' : (isDailyReport ? '安全日报' : '主机预警')

  const navItems = [
    {
      itemKey: 'host-alert',
      text: '主机预警',
      icon: <IconBell />,
      items: [
        { itemKey: '/dashboard', text: '预警生成', icon: <IconHome /> },
        { itemKey: '/admin/owner-mappings', text: '项目负责人', icon: <IconUserGroup /> },
        { itemKey: '/admin/owner-emails', text: '责任人邮箱', icon: <IconUserGroup /> },
        { itemKey: '/admin/unquota-hosts', text: '未配额主机', icon: <IconUserGroup /> },
        { itemKey: '/admin/deferred-install-hosts', text: '暂不安装主机', icon: <IconUserGroup /> },
        { itemKey: '/history', text: '历史记录', icon: <IconHistory /> },
      ],
    },
    {
      itemKey: 'daily-report',
      text: '安全日报',
      icon: <IconCalendar />,
      items: [
        { itemKey: '/daily-report', text: '填写日报', icon: <IconFile /> },
        { itemKey: '/daily-report/preview', text: '预览日报', icon: <IconFile /> },
        { itemKey: '/daily-report/operators', text: '运营人员', icon: <IconUserGroup /> },
        { itemKey: '/daily-report/llm-settings', text: '大模型配置', icon: <IconSetting /> },
      ],
    },
    {
      itemKey: 'tools',
      text: '富强专用工具',
      icon: <IconTick />,
      items: [
        { itemKey: '/tools/ip-query', text: 'IP批量查询', icon: <IconSearch /> },
      ],
    },
    {
      itemKey: 'settings',
      text: '设置',
      icon: <IconSetting />,
      items: [
        { itemKey: '/daily-report/email-settings', text: '邮件配置', icon: <IconSetting /> },
      ],
    },
  ]

  const userMenu = (
    <Dropdown
      render={
        <Dropdown.Menu>
          <Dropdown.Item icon={<IconLock />} onClick={() => navigate('/change-password')}>
            修改密码
          </Dropdown.Item>
          <Dropdown.Item icon={<IconUnlock />} onClick={handleLogout}>
            退出登录
          </Dropdown.Item>
        </Dropdown.Menu>
      }
    >
      <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Avatar size="small" style={{ backgroundColor: '#0077fa' }}>
          {user?.display_name?.[0] || user?.username?.[0] || 'U'}
        </Avatar>
        <span>{user?.display_name || user?.username}</span>
        <IconChevronDown size="small" />
      </div>
    </Dropdown>
  )

  return (
    <Layout style={{ minHeight: '100vh', width: '100%' }}>
      <Sider
        style={{
          width: collapsed ? 64 : 240,
          minWidth: collapsed ? 64 : 240,
          maxWidth: collapsed ? 64 : 240,
          transition: 'all 0.3s',
          overflow: 'hidden',
          position: 'sticky',
          top: 0,
          height: '100vh',
          zIndex: 100,
          backgroundColor: '#fff',
        }}
      >
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 20px',
          borderBottom: '1px solid #e8e8e8',
        }}>
          <h1 style={{
            color: '#111827',
            margin: 0,
            fontSize: collapsed ? 18 : 20,
            fontWeight: 800,
            letterSpacing: '0.5px',
            whiteSpace: 'nowrap',
          }}>
            {collapsed ? '报告' : '报告管理工具'}
          </h1>
        </div>
        <Nav
          items={navItems}
          selectedKeys={[location.pathname]}
          defaultOpenKeys={['host-alert', 'daily-report', 'tools']}
          onClick={({ itemKey }) => {
            // 只有叶子节点才导航（没有子菜单的项）
            const isLeaf = !navItems.some(group => group.itemKey === itemKey)
            if (isLeaf) {
              navigate(itemKey as string)
            }
          }}
          style={{ height: 'calc(100vh - 64px)', backgroundColor: '#fff' }}
        />
      </Sider>
      <Layout style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100vh' }}>
        <Header
          style={{
            backgroundColor: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #eee',
            height: 64,
            flexShrink: 0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Button
              icon={<IconMenu />}
              type="tertiary"
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 20 }}
            />
            <span style={{ fontSize: 16, fontWeight: 600, color: '#1f2937' }}>{currentModule}</span>
          </div>
          {userMenu}
        </Header>
        <Content style={{ padding: 24, backgroundColor: '#f5f5f5', flex: 1, overflow: 'auto', width: '100%' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
