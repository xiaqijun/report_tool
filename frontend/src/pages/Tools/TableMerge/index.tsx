import { useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Button, Spin, Switch, Tag, Toast } from '@douyinfe/semi-ui'
import IconClose from '@douyinfe/semi-icons/lib/es/icons/IconClose'
import IconDownload from '@douyinfe/semi-icons/lib/es/icons/IconDownload'
import IconFile from '@douyinfe/semi-icons/lib/es/icons/IconFile'
import IconTickCircle from '@douyinfe/semi-icons/lib/es/icons/IconTickCircle'
import IconUpload from '@douyinfe/semi-icons/lib/es/icons/IconUpload'
import api from '../../../api'
import './styles.css'

interface MergeStats {
  input_files: number
  workbooks: number
  rows_read: number
  rows_written: number
  duplicate_rows: number
  deduplicated: boolean
  columns: number
}

interface VulnerabilityStats {
  hss_input_files: number
  hss_workbooks: number
  hss_rows_read: number
  hss_duplicate_rows: number
  rows_written: number
  elb_input_files: number
  elb_workbooks: number
  elb_rows_read: number
  elb_duplicate_rows: number
  elb_unique_ips: number
  public_rows: number
  non_public_rows: number
  filtered_rows: number
  filtered_by_level: Record<string, number>
  remove_risk_levels: string[]
  columns: number
}

interface ProcessResult<T> {
  job_id: string
  filename: string
  download_url: string
  stats: T
}

interface FileBucketProps {
  label: string
  title: string
  description: string
  files: File[]
  onChange: (files: File[]) => void
}

const allowedExtensions = ['.xlsx', '.xlsm', '.zip']
const riskLevels = ['低危', '中危', '高危', '严重']

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return minutes ? `${minutes}分${rest}秒` : `${rest}秒`
}

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

function acceptedFiles(incoming: File[]) {
  return incoming.filter(file => allowedExtensions.some(extension => file.name.toLowerCase().endsWith(extension)))
}

function FileBucket({ label, title, description, files, onChange }: FileBucketProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const addFiles = (incoming: File[]) => {
    const valid = acceptedFiles(incoming)
    const rejected = incoming.length - valid.length
    const known = new Set(files.map(fileKey))
    onChange([...files, ...valid.filter(file => !known.has(fileKey(file)))].slice(0, 100))
    if (rejected) Toast.warning(`${rejected} 个文件格式不受支持`)
  }

  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files || []))
    event.target.value = ''
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    addFiles(Array.from(event.dataTransfer.files || []))
  }

  return (
    <section className="file-bucket">
      <div className="bucket-heading">
        <span>{label}</span>
        <div>
          <strong>{title}</strong>
          <small>{description}</small>
        </div>
        {files.length > 0 && <em>{files.length} 个</em>}
      </div>
      <div
        className={`compact-dropzone ${dragging ? 'is-dragging' : ''}`}
        onDragEnter={event => { event.preventDefault(); setDragging(true) }}
        onDragOver={event => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click() }}
        role="button"
        tabIndex={0}
      >
        <IconUpload />
        <span>选择或拖入 .xlsx / .xlsm / .zip</span>
        <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.zip" multiple hidden onChange={handleInput} />
      </div>
      {files.length > 0 && (
        <div className="bucket-files">
          {files.map(file => (
            <div className="file-row" key={fileKey(file)}>
              <IconFile />
              <span title={file.name}>{file.name}</span>
              <em>{formatBytes(file.size)}</em>
              <button
                type="button"
                title="移除"
                aria-label={`移除 ${file.name}`}
                onClick={() => onChange(files.filter(item => fileKey(item) !== fileKey(file)))}
              >
                <IconClose />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

export default function TableMergePage() {
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [mode, setMode] = useState<'vulnerability' | 'merge'>('vulnerability')
  const [hssFiles, setHssFiles] = useState<File[]>([])
  const [elbFiles, setElbFiles] = useState<File[]>([])
  const [mergeFiles, setMergeFiles] = useState<File[]>([])
  const [removeLevels, setRemoveLevels] = useState<string[]>(['低危'])
  const [deduplicate, setDeduplicate] = useState(true)
  const [processing, setProcessing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [vulnerabilityResult, setVulnerabilityResult] = useState<ProcessResult<VulnerabilityStats> | null>(null)
  const [mergeResult, setMergeResult] = useState<ProcessResult<MergeStats> | null>(null)

  const currentFiles = mode === 'vulnerability' ? [...hssFiles, ...elbFiles] : mergeFiles
  const totalBytes = useMemo(
    () => currentFiles.reduce((sum, file) => sum + file.size, 0),
    [currentFiles],
  )

  const startTimer = () => {
    setProcessing(true)
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(value => value + 1), 1000)
  }

  const stopTimer = () => {
    setProcessing(false)
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = null
  }

  const processVulnerabilityFiles = async () => {
    if (!hssFiles.length || !elbFiles.length) {
      Toast.warning('请同时选择 HSS 漏洞报告和 ELB 表格')
      return
    }
    const form = new FormData()
    hssFiles.forEach(file => form.append('hss_files', file, file.name))
    elbFiles.forEach(file => form.append('elb_files', file, file.name))
    form.append('remove_risk_levels', removeLevels.join(','))

    setVulnerabilityResult(null)
    startTimer()
    try {
      const response = await api.post<ProcessResult<VulnerabilityStats>>(
        '/api/tools/vulnerability-process',
        form,
        { timeout: 0 },
      )
      setVulnerabilityResult(response.data)
      Toast.success('最终漏洞报告已生成')
    } catch (error: any) {
      Toast.error(error?.response?.data?.detail || error?.message || '漏洞报告处理失败')
    } finally {
      stopTimer()
    }
  }

  const processMergeFiles = async () => {
    if (!mergeFiles.length) {
      Toast.warning('请先选择 Excel 或 ZIP 文件')
      return
    }
    const form = new FormData()
    mergeFiles.forEach(file => form.append('files', file, file.name))
    form.append('deduplicate', String(deduplicate))

    setMergeResult(null)
    startTimer()
    try {
      const response = await api.post<ProcessResult<MergeStats>>('/api/tools/table-merge', form, { timeout: 0 })
      setMergeResult(response.data)
      Toast.success('表格处理完成')
    } catch (error: any) {
      Toast.error(error?.response?.data?.detail || error?.message || '表格处理失败')
    } finally {
      stopTimer()
    }
  }

  const toggleRiskLevel = (level: string) => {
    setRemoveLevels(current => (
      current.includes(level) ? current.filter(item => item !== level) : [...current, level]
    ))
    setVulnerabilityResult(null)
  }

  return (
    <div className="table-merge-page">
      <header className="table-merge-header">
        <div>
          <span>VULNERABILITY DATA WORKBENCH</span>
          <h2>漏洞数据处理</h2>
          <p>把 HSS 与 ELB 原始表格整理成可直接交付的漏洞主机报告。</p>
        </div>
        {currentFiles.length > 0 && (
          <div className="input-summary">
            <strong>{currentFiles.length}</strong>
            <span>个输入 · {formatBytes(totalBytes)}</span>
          </div>
        )}
      </header>

      <div className="mode-switch" role="tablist" aria-label="处理模式">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'vulnerability'}
          className={mode === 'vulnerability' ? 'is-active' : ''}
          onClick={() => setMode('vulnerability')}
        >
          漏洞报告处理
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'merge'}
          className={mode === 'merge' ? 'is-active' : ''}
          onClick={() => setMode('merge')}
        >
          通用合并去重
        </button>
      </div>

      {mode === 'vulnerability' ? (
        <>
          <section className="pipeline-card">
            <div className="pipeline-heading">
              <strong>一次完成四步处理</strong>
              <span>全程流式读写，支持直接上传 ZIP</span>
            </div>
            <div className="pipeline-track">
              {[
                ['01', '分别合并', '汇总 HSS / ELB'],
                ['02', '完全去重', '保留首次记录'],
                ['03', 'IP 关联', '标记对外服务'],
                ['04', '风险过滤', '生成最终报告'],
              ].map(([number, title, detail]) => (
                <div className="pipeline-step" key={number}>
                  <i>{number}</i>
                  <strong>{title}</strong>
                  <span>{detail}</span>
                </div>
              ))}
            </div>
          </section>

          <div className="source-grid">
            <FileBucket
              label="HSS"
              title="漏洞主机报告"
              description="需包含服务器IP、风险等级列"
              files={hssFiles}
              onChange={files => { setHssFiles(files); setVulnerabilityResult(null) }}
            />
            <FileBucket
              label="ELB"
              title="负载均衡后端表"
              description="需包含后端服务器-私网IP地址列"
              files={elbFiles}
              onChange={files => { setElbFiles(files); setVulnerabilityResult(null) }}
            />
          </div>

          <section className="filter-panel">
            <div className="filter-copy">
              <span>最终筛选</span>
              <strong>去掉哪些风险等级</strong>
              <small>默认去掉低危；不勾选则保留全部风险等级。</small>
            </div>
            <div className="risk-options">
              {riskLevels.map(level => (
                <label className={removeLevels.includes(level) ? 'is-selected' : ''} key={level}>
                  <input
                    type="checkbox"
                    checked={removeLevels.includes(level)}
                    onChange={() => toggleRiskLevel(level)}
                  />
                  <span>{level}</span>
                </label>
              ))}
            </div>
            <Button
              type="primary"
              size="large"
              icon={<IconTickCircle />}
              loading={processing}
              disabled={!hssFiles.length || !elbFiles.length}
              onClick={processVulnerabilityFiles}
            >
              生成最终报告
            </Button>
          </section>
        </>
      ) : (
        <section className="generic-merge-card">
          <FileBucket
            label="MERGE"
            title="Excel / ZIP 文件"
            description="所有工作簿表头需保持一致"
            files={mergeFiles}
            onChange={files => { setMergeFiles(files); setMergeResult(null) }}
          />
          <div className="processing-bar">
            <label>
              <Switch checked={deduplicate} onChange={checked => { setDeduplicate(checked); setMergeResult(null) }} />
              <span>
                <strong>合并后去重</strong>
                <small>按原始数据列完全一致判断，保留首次出现记录</small>
              </span>
            </label>
            <Button
              type="primary"
              size="large"
              icon={<IconTickCircle />}
              loading={processing}
              disabled={!mergeFiles.length}
              onClick={processMergeFiles}
            >
              开始处理
            </Button>
          </div>
        </section>
      )}

      {processing && (
        <section className="processing-state">
          <Spin size="large" />
          <div>
            <strong>{mode === 'vulnerability' ? '正在生成最终漏洞报告' : '正在流式合并表格'}</strong>
            <span>已用 {formatDuration(elapsed)}，大文件请保持页面打开</span>
          </div>
        </section>
      )}

      {mode === 'vulnerability' && vulnerabilityResult && !processing && (
        <section className="merge-result">
          <div className="result-title">
            <IconTickCircle />
            <div>
              <strong>最终报告已生成</strong>
              <span>{vulnerabilityResult.filename}</span>
            </div>
            <Button
              icon={<IconDownload />}
              theme="solid"
              type="primary"
              onClick={() => window.location.assign(vulnerabilityResult.download_url)}
            >
              下载最终报告
            </Button>
          </div>
          <div className="result-metrics result-metrics-six">
            <div><span>HSS 读取</span><strong>{vulnerabilityResult.stats.hss_rows_read.toLocaleString()}</strong></div>
            <div><span>HSS 重复</span><strong>{vulnerabilityResult.stats.hss_duplicate_rows.toLocaleString()}</strong></div>
            <div><span>风险过滤</span><strong>{vulnerabilityResult.stats.filtered_rows.toLocaleString()}</strong></div>
            <div><span>最终输出</span><strong>{vulnerabilityResult.stats.rows_written.toLocaleString()}</strong></div>
            <div><span>ELB 唯一 IP</span><strong>{vulnerabilityResult.stats.elb_unique_ips.toLocaleString()}</strong></div>
            <div><span>对外服务主机</span><strong>{vulnerabilityResult.stats.public_rows.toLocaleString()}</strong></div>
          </div>
          <div className="result-tags">
            <Tag color="blue">{vulnerabilityResult.stats.columns} 列</Tag>
            <Tag color="green">已合并去重</Tag>
            <Tag color="cyan">已完成 IP 标记</Tag>
            <Tag color="amber">
              {vulnerabilityResult.stats.remove_risk_levels.length
                ? `已去掉 ${vulnerabilityResult.stats.remove_risk_levels.join('、')}`
                : '保留全部风险等级'}
            </Tag>
          </div>
        </section>
      )}

      {mode === 'merge' && mergeResult && !processing && (
        <section className="merge-result">
          <div className="result-title">
            <IconTickCircle />
            <div>
              <strong>处理完成</strong>
              <span>{mergeResult.filename}</span>
            </div>
            <Button icon={<IconDownload />} theme="solid" type="primary" onClick={() => window.location.assign(mergeResult.download_url)}>
              下载结果
            </Button>
          </div>
          <div className="result-metrics">
            <div><span>工作簿</span><strong>{mergeResult.stats.workbooks.toLocaleString()}</strong></div>
            <div><span>读取行数</span><strong>{mergeResult.stats.rows_read.toLocaleString()}</strong></div>
            <div><span>输出行数</span><strong>{mergeResult.stats.rows_written.toLocaleString()}</strong></div>
            <div><span>重复记录</span><strong>{mergeResult.stats.duplicate_rows.toLocaleString()}</strong></div>
          </div>
          <div className="result-tags">
            <Tag color="blue">{mergeResult.stats.columns} 个业务列</Tag>
            <Tag color={mergeResult.stats.deduplicated ? 'green' : 'grey'}>
              {mergeResult.stats.deduplicated ? '已去重' : '仅合并'}
            </Tag>
          </div>
        </section>
      )}
    </div>
  )
}
