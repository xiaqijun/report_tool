import { useState, useEffect, useRef, useCallback } from 'react'
import { Form, Button, Toast, Row, Col, DatePicker, Modal, TextArea } from '@douyinfe/semi-ui'
import { IconSave, IconCamera, IconAIStrokedLevel1, IconEyeOpened } from '@douyinfe/semi-icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../../api'
import './styles.css'

const SCREENSHOT_MAP: Record<string, string> = {
  waf_screenshot_path: 'waf',
  waf_qps_screenshot_path: 'waf-qps',
  cfw_screenshot_path: 'cfw',
  cfw_bandwidth_screenshot_path: 'cfw-bandwidth',
  hss_screenshot_path: 'hss',
  ddos_screenshot_path: 'ddos',
  secmaster_screenshot_path: 'secmaster',
  emergency_response_screenshot_path: 'emergency-response',
  key_work_screenshot_path: 'key-work',
  legacy_items_screenshot_path: 'legacy-items',
}

type TrendFluctuation = {
  key: string
  name: string
  metric: string
  current: number
  previous: number
  previous_date?: string
  delta: number
  percent: number | null
  direction: 'up' | 'down'
}

function normalizeScreenshotUrl(path?: string) {
  const value = (path || '').trim()
  if (!value) return null
  if (value.startsWith('http://') || value.startsWith('https://')) return value
  if (value.startsWith('/uploads/') || value.startsWith('/daily-report/screenshots/')) return value
  if (value.startsWith('uploads/') || value.startsWith('daily-report/screenshots/')) return `/${value}`
  if (value.startsWith('data/')) return `/${value.replace(/^data\//, '')}`
  return `/${value.replace(/^\/+/, '')}`
}

function formatReportDate(value: string | number | Date | string[] | Date[]) {
  const normalizedValue = Array.isArray(value) ? value[0] : value
  if (normalizedValue instanceof Date) {
    return `${normalizedValue.getFullYear()}-${String(normalizedValue.getMonth() + 1).padStart(2, '0')}-${String(normalizedValue.getDate()).padStart(2, '0')}`
  }
  return String(normalizedValue ?? '').slice(0, 10)
}

function ScreenshotBtn({ field, label, formApi, reportDate, initPath, onPathChange }: { field: string; label: string; formApi: any; reportDate: string; initPath?: string; onPathChange?: (path: string) => void }) {
  const section = SCREENSHOT_MAP[field]
  const [preview, setPreview] = useState<string | null>(null)
  const [pasting, setPasting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const prevInitPath = useRef<string>()

  // Update preview when initPath changes (from parent screenshotPaths)
  useEffect(() => {
    if (initPath && initPath !== prevInitPath.current) {
      prevInitPath.current = initPath
      setPreview(normalizeScreenshotUrl(initPath))
      return
    }
    if (!initPath && prevInitPath.current) {
      prevInitPath.current = undefined
      setPreview(null)
    }
  }, [initPath])

  const uploadFile = useCallback(async (file: File) => {
    setPasting(true)
    try {
      const reader = new FileReader()
      const dataUri = await new Promise<string>(r => { reader.onload = () => r(reader.result as string); reader.readAsDataURL(file) })
      setPreview(dataUri)
      const res = await api.post('/api/daily-report/screenshots/paste', { section, report_date: reportDate, image: dataUri })
      if (res.data?.path) {
        if (formApi) formApi.setValue(field, res.data.path)
        onPathChange?.(res.data.path)
      }
    } catch (e: any) { Toast.error(e?.response?.data?.detail || e?.message || '上传失败') }
    finally { setPasting(false) }
  }, [section, field, formApi, onPathChange, reportDate])

  const onPaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) { e.preventDefault(); uploadFile(file); return }
      }
    }
    const files = e.clipboardData?.files
    if (files?.length) {
      for (let i = 0; i < files.length; i++) {
        if (files[i].type.startsWith('image/')) {
          e.preventDefault(); uploadFile(files[i]); return
        }
      }
    }
  }, [uploadFile])

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (formApi) formApi.setValue(field, f)
    uploadFile(f)
  }, [field, formApi, uploadFile])

  return (
    <div className="sc-upload">
      <div className={`sc-zone${pasting ? ' pasting' : ''}${preview ? ' has-img' : ''}`}
        tabIndex={0} onPaste={onPaste}
        onClick={(e) => (e.target as HTMLElement).focus()}
        title="点击聚焦 → Ctrl+V 粘贴 | 📷 选择文件">
        {preview ? (
          <>
            <img src={preview} alt="" />
            <span className="sc-clear" onClick={(e) => { e.stopPropagation(); setPreview(null); if (formApi) formApi.setValue(field, '') }} title="清除图片">&times;</span>
            <span className="sc-pick" onClick={(e) => { e.stopPropagation(); fileRef.current?.click() }} title="更换图片">
              <IconCamera size="small" />
            </span>
          </>
        ) : (
          <div className="sc-zone-hint">
            <span className="sc-label">{label}</span>
            <span className="sc-action">点击聚焦 → Ctrl+V 粘贴 | 📷 选择文件</span>
          </div>
        )}
        {!preview && (
          <span className="sc-pick" onClick={(e) => { e.stopPropagation(); fileRef.current?.click() }} title="选择文件">
            <IconCamera size="small" />
          </span>
        )}
      </div>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" style={{ display: 'none' }}
        onChange={onFileChange} />
    </div>
  )
}

function SectionCard({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="sc">
      <div className="sc-head">
        <span className="sc-badge" data-n={n}>{n}</span>
        <h2 className="sc-title">{title}</h2>
      </div>
      <div className="sc-body">{children}</div>
    </div>
  )
}

export default function DailyReportPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [loading, setLoading] = useState(false)
  const [autoSaveStatus, setAutoSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [lastAutoSavedAt, setLastAutoSavedAt] = useState<Date | null>(null)
  const [formApi, setFormApi] = useState<any>(null)
  const today = new Date().toISOString().slice(0, 10)
  const [screenshotPaths, setScreenshotPaths] = useState<Record<string, string>>({})
  const reportDate = searchParams.get('date') || today
  const dataLoadedRef = useRef(false)
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autoSaveInFlightRef = useRef(false)
  const autoSaveQueuedRef = useRef(false)
  const latestValuesRef = useRef<Record<string, any>>({})
  const screenshotPathsRef = useRef<Record<string, string>>({})
  const reportDateRef = useRef(reportDate)

  useEffect(() => {
    reportDateRef.current = reportDate
    dataLoadedRef.current = false
    autoSaveQueuedRef.current = false
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current)
      autoSaveTimerRef.current = null
    }
    setAutoSaveStatus('idle')
    setLastAutoSavedAt(null)
  }, [reportDate])

  useEffect(() => () => {
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current)
  }, [])

  useEffect(() => { if (formApi) fetchData() }, [formApi, reportDate])

  const updateReportDate = useCallback((nextDate: string) => {
    const normalizedDate = formatReportDate(nextDate)
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev)
      params.set('date', normalizedDate)
      return params
    }, { replace: true })
  }, [setSearchParams])

  const fetchData = async () => {
    if (!formApi) return
    try {
      const res = await api.get('/api/daily-report', { params: { report_date: reportDate } })
      const values: Record<string, unknown> = { ...res.data.report }
      const [y, m, d] = reportDate.split('-').map(Number)
      const prev = new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10)
      if (!values.monitor_start) values.monitor_start = prev + ' 18:00'
      if (!values.monitor_end) values.monitor_end = reportDate + ' 18:00'
      if (!values.waf_qps_specs && res.data.default_waf_qps_specs) values.waf_qps_specs = res.data.default_waf_qps_specs
      if (!values.cfw_bandwidth_spec && res.data.default_cfw_bandwidth_spec) values.cfw_bandwidth_spec = res.data.default_cfw_bandwidth_spec
      if (!values.waf_qps_peak_range && res.data.default_waf_qps_peak_range) values.waf_qps_peak_range = res.data.default_waf_qps_peak_range
      if (!values.cfw_peak_inbound_range && res.data.default_cfw_peak_inbound_range) values.cfw_peak_inbound_range = res.data.default_cfw_peak_inbound_range
      // Extract screenshot paths for preview
      const paths: Record<string, string> = {}
      for (const key of Object.keys(SCREENSHOT_MAP)) {
        if ((values as any)[key] && typeof (values as any)[key] === 'string') {
          paths[key] = (values as any)[key]
        }
      }
      setScreenshotPaths(paths)
      screenshotPathsRef.current = paths
      latestValuesRef.current = values
      formApi.setValues(values)
      dataLoadedRef.current = true
    } catch { Toast.error('获取日报数据失败') }
  }

  const [aiGenerating, setAiGenerating] = useState(false)
  const [fluctuationModalVisible, setFluctuationModalVisible] = useState(false)
  const [trendFluctuations, setTrendFluctuations] = useState<TrendFluctuation[]>([])
  const [fluctuationReasons, setFluctuationReasons] = useState<Record<string, string>>({})
  const [reasonPolishing, setReasonPolishing] = useState(false)
  const updateScreenshotPath = useCallback((field: string, path: string) => {
    screenshotPathsRef.current = { ...screenshotPathsRef.current, [field]: path }
    setScreenshotPaths(screenshotPathsRef.current)
  }, [])

  const handleAiGenerate = async () => {
    if (!formApi) return
    setAiGenerating(true)
    try {
      const values = formApi.getValues() || {}
      const res = await api.post('/api/daily-report/generate-top-section', { ...values, report_date: reportDate })
      const generated = res.data
      if (generated) {
        if (generated.business_stability) formApi.setValue('business_stability', generated.business_stability)
        if (generated.trend_comparison) formApi.setValue('trend_comparison', generated.trend_comparison)
        if (generated.overall_assessment) formApi.setValue('overall_assessment', generated.overall_assessment)
        const fluctuations = Array.isArray(generated.trend_fluctuations) ? generated.trend_fluctuations : []
        if (fluctuations.length > 0) {
          setTrendFluctuations(fluctuations)
          setFluctuationReasons(Object.fromEntries(fluctuations.map((item: TrendFluctuation) => [item.key, ''])))
          setFluctuationModalVisible(true)
        }
        Toast.success('AI 文案已生成')
      }
    } catch { Toast.error('AI 生成失败，请检查 LLM 配置') }
    finally { setAiGenerating(false) }
  }

  const handleWriteFluctuationReasons = async () => {
    if (!formApi) return
    const reasonGroups = new Map<string, TrendFluctuation[]>()
    trendFluctuations.forEach(item => {
      const reason = (fluctuationReasons[item.key] || '')
        .trim()
        .replace(/[。；;，,\s]+$/, '')
        .replace(/\s+/g, ' ')
      if (!reason) return
      reasonGroups.set(reason, [...(reasonGroups.get(reason) || []), item])
    })

    if (reasonGroups.size === 0) {
      setFluctuationModalVisible(false)
      Toast.info('未填写波动原因，已保留原 AI 文案')
      return
    }

    const currentTrend = String(formApi.getValue('trend_comparison') || '').trim().replace(/[。；;\s]+$/, '')
    const groupedReasons = Array.from(reasonGroups.entries()).map(([reason, items]) => ({
      reason,
      device_metrics: items.map(item => `${item.name}${item.metric}`),
    }))
    setReasonPolishing(true)
    try {
      const res = await api.post('/api/daily-report/polish-trend-reasons', {
        trend_comparison: currentTrend,
        reason_groups: groupedReasons,
        fluctuations: trendFluctuations.map(item => ({
          key: item.key,
          name: item.name,
          metric: item.metric,
          direction: item.direction,
        })),
      })
      const polished = String(res.data?.trend_comparison || '').trim()
      if (!polished) throw new Error('AI 润色结果为空')
      formApi.setValue('trend_comparison', polished)
      setFluctuationModalVisible(false)
      Toast.success('AI 已润色并写入趋势分析')
    } catch {
      Toast.error('AI 润色失败，请稍后重试')
    } finally {
      setReasonPolishing(false)
    }
  }

  const formatFluctuationRate = (item: TrendFluctuation) => {
    if (item.percent === null) return '由 0 新增'
    return `${item.percent.toLocaleString('zh-CN', { maximumFractionDigits: 1 })}%`
  }

  const buildSaveFormData = useCallback((values: any, autoSave = false) => {
    const fd = new FormData()
    const payload = { ...screenshotPathsRef.current, ...values }
    for (const [k, v] of Object.entries(payload)) {
      if (v !== undefined && v !== null) fd.append(k, v instanceof File ? v : String(v))
    }
    fd.append('report_date', reportDateRef.current)
    if (autoSave) fd.append('auto_save', '1')
    return fd
  }, [])

  const saveAutomatically = useCallback(async (values: Record<string, any>) => {
    if (!dataLoadedRef.current) return
    const targetDate = reportDateRef.current
    if (autoSaveInFlightRef.current) {
      autoSaveQueuedRef.current = true
      return
    }
    autoSaveInFlightRef.current = true
    autoSaveQueuedRef.current = false
    setAutoSaveStatus('saving')
    try {
      await api.post('/api/daily-report/save', buildSaveFormData(values, true))
      if (reportDateRef.current === targetDate) {
        setAutoSaveStatus('saved')
        setLastAutoSavedAt(new Date())
      }
    } catch {
      setAutoSaveStatus('error')
    } finally {
      autoSaveInFlightRef.current = false
      if (autoSaveQueuedRef.current && dataLoadedRef.current) {
        autoSaveQueuedRef.current = false
        void saveAutomatically(latestValuesRef.current)
      }
    }
  }, [buildSaveFormData])

  const scheduleAutoSave = useCallback((values: Record<string, any>) => {
    latestValuesRef.current = values
    if (!dataLoadedRef.current) return
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current)
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null
      void saveAutomatically(latestValuesRef.current)
    }, 1200)
  }, [saveAutomatically])

  const handleSubmit = async (values: any) => {
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current)
      autoSaveTimerRef.current = null
    }
    autoSaveQueuedRef.current = false
    setLoading(true)
    try {
      await api.post('/api/daily-report/save', buildSaveFormData(values))
      Toast.success('保存成功')
      setAutoSaveStatus('saved')
      setLastAutoSavedAt(new Date())
    } catch { Toast.error('保存失败') }
    finally { setLoading(false) }
  }

  const navigate = useNavigate()

  return (
    <div className="dr-page">
      <Modal
        className="fluctuation-modal"
        title="补充设备大幅波动原因"
        visible={fluctuationModalVisible}
        okText="AI 润色并应用"
        cancelText="保留 AI 结果"
        confirmLoading={reasonPolishing}
        maskClosable={false}
        width={680}
        onOk={handleWriteFluctuationReasons}
        onCancel={() => setFluctuationModalVisible(false)}
      >
        <div className="fluctuation-intro">
          AI 已完成趋势文案。可按实际情况补充影响原因，相同原因会自动合并；不填写则保留原 AI 分析。
        </div>
        <div className="fluctuation-list">
          {trendFluctuations.map(item => (
              <div className={`fluctuation-card ${item.direction}`} key={item.key}>
                <div className="fluctuation-card-head">
                  <div>
                    <div className="fluctuation-device">{item.name}</div>
                    <div className="fluctuation-metric">{item.metric}</div>
                  </div>
                  <span className={`fluctuation-badge ${item.direction}`}>
                    {item.direction === 'up' ? '↑ 大幅上升' : '↓ 大幅下降'} {formatFluctuationRate(item)}
                  </span>
                </div>
                <div className="fluctuation-values">
                  <span>{item.previous_date ? `${item.previous_date} 数量` : '对比数量'} <strong>{item.previous}</strong></span>
                  <span className={`fluctuation-arrow ${item.direction}`}>→</span>
                  <span>当前数量 <strong>{item.current}</strong></span>
                  <span className="fluctuation-delta">变化 {item.delta > 0 ? '+' : ''}{item.delta}</span>
                </div>
                <div className="fluctuation-reason">
                  <label htmlFor={`fluctuation-reason-${item.key}`}>影响原因（选填）</label>
                  <TextArea
                    id={`fluctuation-reason-${item.key}`}
                    value={fluctuationReasons[item.key] || ''}
                    autosize={{ minRows: 2, maxRows: 4 }}
                    placeholder="请输入影响因素，例如：业务发布后集中扫描（无需填写“受……影响”）"
                    onChange={value => setFluctuationReasons(prev => ({ ...prev, [item.key]: value }))}
                  />
                </div>
              </div>
          ))}
        </div>
      </Modal>
      <Form
        onSubmit={handleSubmit}
        onValueChange={(values: Record<string, any>) => scheduleAutoSave(values)}
        getFormApi={setFormApi}
      >
        <div className="dr-header">
          <div className="dr-header-right">
            <span className="dr-header-label">日报日期</span>
            <DatePicker value={reportDate} onChange={v => { if (!v) return; updateReportDate(formatReportDate(v)) }} style={{ width: 150 }} />
          </div>
        </div>
        <SectionCard n={2} title="安全监控">
          <div className="dr-time-row">
            <Row gutter={16}>
              <Col span={12}><Form.Input field="monitor_start" label="监控开始时间" placeholder="2024-01-01 18:00" /></Col>
              <Col span={12}><Form.Input field="monitor_end" label="监控结束时间" placeholder="2024-01-02 18:00" /></Col>
            </Row>
          </div>

          {/* WAF */}
          <div className="dr-prod">
            <div className="dr-prod-title"><span className="dr-prod-dot" style={{ background: '#7c3aed' }} />WAF 应用防火墙</div>
            <Row gutter={16}>
              <Col span={8}><Form.InputNumber field="waf_detail_attacks" label="攻击次数" /></Col>
              <Col span={8}><Form.InputNumber field="waf_detail_blocked" label="拦截次数" /></Col>
              <Col span={8}><Form.InputNumber field="waf_ips_banned" label="封禁IP个数" /></Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 12 }}>
              <Col span={8}><Form.Input field="waf_qps_specs" label="QPS 规格" placeholder="85,000（云模式专业版45000+40个QPS扩展包）" /></Col>
              <Col span={8}><Form.Input field="waf_qps_peak_range" label="峰值时间段" placeholder="如：16:55-18:00" className="dr-input-peak-range dr-input-peak-range-waf" /></Col>
              <Col span={8}><Form.InputNumber field="waf_qps_peak_value" label="峰值" /></Col>
            </Row>
            <Form.Switch field="waf_exceeded_spec" label="超出规格（可能出现限流、随机丢包、自动Bypass等现象）" style={{ marginTop: 10 }} />
            <div className="sc-row"><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["waf_qps_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('waf_qps_screenshot_path', path)} field="waf_qps_screenshot_path" label="WAF QPS 峰值截图（可选）" /><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["waf_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('waf_screenshot_path', path)} field="waf_screenshot_path" label="WAF 攻击监测截图（可选）" /></div>
          </div>

          {/* CFW */}
          <div className="dr-prod">
            <div className="dr-prod-title"><span className="dr-prod-dot" style={{ background: '#0891b2' }} />CFW 云防火墙</div>
            <Row gutter={16}>
              <Col span={12}><Form.InputNumber field="cfw_detail_attacks" label="攻击次数" /></Col>
              <Col span={12}><Form.InputNumber field="cfw_detail_unblocked" label="未阻断次数" /></Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 12 }}>
              <Col span={6}><Form.Input field="cfw_bandwidth_spec" label="带宽规格" placeholder="12050Mbps" /></Col>
              <Col span={6}><Form.Input field="cfw_peak_inbound_range" label="峰值时间段" placeholder="如：6:04-9:04，16:44-18:00" className="dr-input-peak-range dr-input-peak-range-cfw" /></Col>
              <Col span={6}><Form.Input field="cfw_inbound_peak" label="入方向峰值" /></Col>
              <Col span={6}><Form.Input field="cfw_inbound_95th" label="入方向 95 带宽" /></Col>
            </Row>
            <Form.Switch field="cfw_exceeded_spec" label="超出规格（可能出现限流、随机丢包、自动Bypass等现象）" style={{ marginTop: 10 }} />
            <div className="sc-row"><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["cfw_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('cfw_screenshot_path', path)} field="cfw_screenshot_path" label="CFW 攻击监测截图（可选）" /><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["cfw_bandwidth_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('cfw_bandwidth_screenshot_path', path)} field="cfw_bandwidth_screenshot_path" label="CFW 带宽峰值截图（可选）" /></div>
          </div>

          {/* HSS */}
          <div className="dr-prod">
            <div className="dr-prod-title"><span className="dr-prod-dot" style={{ background: '#dc2626' }} />HSS 主机安全</div>
            <Row gutter={16}>
              <Col span={6}><Form.InputNumber field="hss_detail_total" label="告警总数" /></Col>
              <Col span={4}><Form.InputNumber field="hss_detail_fatal" label="致命" /></Col>
              <Col span={4}><Form.InputNumber field="hss_detail_high" label="高危" /></Col>
              <Col span={4}><Form.InputNumber field="hss_detail_medium" label="中危" /></Col>
              <Col span={6}><Form.InputNumber field="hss_detail_low" label="低危" /></Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 12 }}>
              <Col span={12}><Form.InputNumber field="hss_unclosed_event_count" label="未闭环事件数" /></Col>
            </Row>
            <div className="sc-row"><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["hss_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('hss_screenshot_path', path)} field="hss_screenshot_path" label="HSS 主机安全告警截图（可选）" /></div>
          </div>

          {/* DDoS */}
          <div className="dr-prod">
            <div className="dr-prod-title"><span className="dr-prod-dot" style={{ background: '#d97706' }} />DDoS 高防</div>
            <Row gutter={16}>
              <Col span={12}><Form.InputNumber field="ddos_detail_cleanings" label="清洗次数" /></Col>
              <Col span={12}><Form.InputNumber field="ddos_detail_blackholes" label="黑洞次数" /></Col>
            </Row>
            <div className="sc-row"><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["ddos_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('ddos_screenshot_path', path)} field="ddos_screenshot_path" label="DDoS 高防清洗截图（可选）" /></div>
          </div>

          {/* SecMaster */}
          <div className="dr-prod">
            <div className="dr-prod-title"><span className="dr-prod-dot" style={{ background: '#4f46e5' }} />SecMaster 态势感知</div>
            <Row gutter={16}>
              <Col span={4}><Form.InputNumber field="secmaster_detail_total" label="告警总数" /></Col>
              <Col span={4}><Form.InputNumber field="secmaster_detail_fatal" label="致命" /></Col>
              <Col span={4}><Form.InputNumber field="secmaster_detail_high" label="高危" /></Col>
              <Col span={4}><Form.InputNumber field="secmaster_detail_medium" label="中危" /></Col>
              <Col span={4}><Form.InputNumber field="secmaster_detail_low" label="低危" /></Col>
              <Col span={4}><Form.InputNumber field="secmaster_detail_info" label="提示" /></Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 12 }}>
              <Col span={12}><Form.InputNumber field="secmaster_unclosed_event_count" label="未闭环事件数" /></Col>
            </Row>
            <div className="sc-row"><ScreenshotBtn formApi={formApi} reportDate={reportDate} initPath={screenshotPaths["secmaster_screenshot_path"]} onPathChange={(path) => updateScreenshotPath('secmaster_screenshot_path', path)} field="secmaster_screenshot_path" label="SecMaster 态势感知告警截图（可选）" /></div>
          </div>

          <div className="dr-prod">
            <div className="dr-prod-title"><span className="dr-prod-dot" style={{ background: '#f59e0b' }} />事件应急响应</div>
            <div className="no-label"><Form.TextArea field="emergency_response" rows={2} placeholder="无" /></div>
          </div>
        </SectionCard>

        <Row gutter={24}>
          <Col span={12}>
            <SectionCard n={3} title="重点工作内容">
              <div className="no-label"><Form.TextArea field="key_work_content" rows={4} placeholder="暂无" /></div>
            </SectionCard>
          </Col>
          <Col span={12}>
            <SectionCard n={4} title="遗留事项">
              <div className="no-label"><Form.TextArea field="legacy_items" rows={4} placeholder="暂无" /></div>
            </SectionCard>
          </Col>
        </Row>

        <SectionCard n={1} title="总体安全态势">
          <div className="ai-row">
            <Button type="tertiary" size="small" icon={<IconAIStrokedLevel1 />} loading={aiGenerating} onClick={handleAiGenerate}>
              AI 生成态势文案
            </Button>
          </div>
          <Form.TextArea field="business_stability" label="业务运行情况" rows={2} placeholder="今日业务运行稳定，各系统运转正常…" />
          <Form.TextArea field="trend_comparison" label="趋势对比说明" rows={3} placeholder="较昨日趋势相比较，WAF、CFW拦截数量有所上升…" />
          <Form.TextArea field="overall_assessment" label="总体评估" rows={2} placeholder="总体来看，今日安全态势平稳可控…" />
        </SectionCard>

        <div className="dr-submit">
          <div className="dr-submit-btns">
            {autoSaveStatus !== 'idle' && (
              <span className={`auto-save-status ${autoSaveStatus}`} aria-live="polite">
                {autoSaveStatus === 'saving' && '正在自动保存...'}
                {autoSaveStatus === 'saved' && `已自动保存${lastAutoSavedAt ? ` ${lastAutoSavedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : ''}`}
                {autoSaveStatus === 'error' && '自动保存失败'}
              </span>
            )}
            <Button theme="light" size="large" icon={<IconEyeOpened />} style={{ borderRadius: 12 }} onClick={() => navigate(`/daily-report/preview?date=${reportDate}`)}>
              预览日报
            </Button>
            <Button type="primary" htmlType="submit" loading={loading} icon={<IconSave />} size="large">保存日报</Button>
          </div>
        </div>
      </Form>
    </div>
  )
}
