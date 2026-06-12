import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import MainLayout from './components/Layout/MainLayout'
import LoginPage from './pages/Login'
import DashboardPage from './pages/Dashboard'
import HistoryPage from './pages/History'
import DailyReportPage from './pages/DailyReport'
import PreviewPage from './pages/Preview'
import OperatorsPage from './pages/Operators'
import LLMSettingsPage from './pages/LLMSettings'
import EmailSettingsPage from './pages/EmailSettings'
import AdminPage from './pages/Admin'
import ChangePasswordPage from './pages/ChangePassword'
import IpQueryPage from './pages/Tools/IpQuery'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />
}

export default function App() {
  const { checkAuth } = useAuthStore()
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const init = async () => {
      await checkAuth()
      setChecking(false)
    }
    init()
  }, [])

  // 等待认证检查完成
  if (checking) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0c1220',
        color: '#94a3b8',
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{
            width: 40,
            height: 40,
            border: '3px solid rgba(14, 165, 233, 0.2)',
            borderTopColor: '#0ea5e9',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            margin: '0 auto 16px',
          }}></div>
          <p>加载中...</p>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <PrivateRoute>
            <MainLayout />
          </PrivateRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="daily-report" element={<DailyReportPage />} />
        <Route path="daily-report/preview" element={<PreviewPage />} />
        <Route path="daily-report/operators" element={<OperatorsPage />} />
        <Route path="daily-report/llm-settings" element={<LLMSettingsPage />} />
        <Route path="daily-report/email-settings" element={<EmailSettingsPage />} />
        <Route path="admin/:datasetKey" element={<AdminPage />} />
        <Route path="tools/ip-query" element={<IpQueryPage />} />
        <Route path="change-password" element={<ChangePasswordPage />} />
      </Route>
    </Routes>
  )
}
