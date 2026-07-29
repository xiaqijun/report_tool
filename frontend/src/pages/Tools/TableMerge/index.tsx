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

interface MergeResult {
  job_id: string
  filename: string
  download_url: string
  stats: MergeStats
}

const allowedExtensions = ['.xlsx', '.xlsm', '.zip']

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

export default function TableMergePage() {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [deduplicate, setDeduplicate] = useState(true)
  const [dragging, setDragging] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<MergeResult | null>(null)

  const totalBytes = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files])

  const addFiles = (incoming: File[]) => {
    const valid: File[] = []
    let rejected = 0
    for (const file of incoming) {
      const lowerName = file.name.toLowerCase()
      if (allowedExtensions.some(extension => lowerName.endsWith(extension))) valid.push(file)
      else rejected += 1
    }
    setFiles(current => {
      const known = new Set(current.map(fileKey))
      return [...current, ...valid.filter(file => !known.has(fileKey(file)))].slice(0, 100)
    })
    setResult(null)
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

  const removeFile = (target: File) => {
    setFiles(current => current.filter(file => fileKey(file) !== fileKey(target)))
    setResult(null)
  }

  const processFiles = async () => {
    if (!files.length) {
      Toast.warning('请先选择 Excel 或 ZIP 文件')
      return
    }
    const form = new FormData()
    files.forEach(file => form.append('files', file, file.name))
    form.append('deduplicate', String(deduplicate))

    setProcessing(true)
    setResult(null)
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(value => value + 1), 1000)
    try {
      const response = await api.post<MergeResult>('/api/tools/table-merge', form, { timeout: 0 })
      setResult(response.data)
      Toast.success('表格处理完成')
    } catch (error: any) {
      Toast.error(error?.response?.data?.detail || error?.message || '表格处理失败')
    } finally {
      setProcessing(false)
      if (timerRef.current) clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  return (
    <div className="table-merge-page">
      <header className="table-merge-header">
        <div>
          <span>DATA PIPELINE</span>
          <h2>表格合并与去重</h2>
        </div>
        {files.length > 0 && (
          <div className="input-summary">
            <strong>{files.length}</strong>
            <span>个输入 · {formatBytes(totalBytes)}</span>
          </div>
        )}
      </header>

      <section className="table-merge-surface">
        <div
          className={`table-dropzone ${dragging ? 'is-dragging' : ''}`}
          onDragEnter={event => { event.preventDefault(); setDragging(true) }}
          onDragOver={event => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click() }}
          role="button"
          tabIndex={0}
        >
          <IconUpload size="extra-large" />
          <strong>选择或拖入文件</strong>
          <span>.xlsx / .xlsm / .zip</span>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xlsm,.zip"
            multiple
            hidden
            onChange={handleInput}
          />
        </div>

        {files.length > 0 && (
          <div className="selected-files">
            <div className="selected-files-head">
              <strong>待处理文件</strong>
              <Button type="tertiary" size="small" onClick={() => { setFiles([]); setResult(null) }}>
                清空
              </Button>
            </div>
            <div className="file-list">
              {files.map(file => (
                <div className="file-row" key={fileKey(file)}>
                  <IconFile />
                  <span title={file.name}>{file.name}</span>
                  <em>{formatBytes(file.size)}</em>
                  <button type="button" title="移除" aria-label={`移除 ${file.name}`} onClick={() => removeFile(file)}>
                    <IconClose />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="processing-bar">
          <label>
            <Switch checked={deduplicate} onChange={checked => { setDeduplicate(checked); setResult(null) }} />
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
            disabled={!files.length}
            onClick={processFiles}
          >
            开始处理
          </Button>
        </div>
      </section>

      {processing && (
        <section className="processing-state">
          <Spin size="large" />
          <div>
            <strong>正在流式处理</strong>
            <span>已用 {formatDuration(elapsed)}</span>
          </div>
        </section>
      )}

      {result && !processing && (
        <section className="merge-result">
          <div className="result-title">
            <IconTickCircle />
            <div>
              <strong>处理完成</strong>
              <span>{result.filename}</span>
            </div>
            <Button icon={<IconDownload />} theme="solid" type="primary" onClick={() => window.location.assign(result.download_url)}>
              下载结果
            </Button>
          </div>
          <div className="result-metrics">
            <div><span>工作簿</span><strong>{result.stats.workbooks.toLocaleString()}</strong></div>
            <div><span>读取行数</span><strong>{result.stats.rows_read.toLocaleString()}</strong></div>
            <div><span>输出行数</span><strong>{result.stats.rows_written.toLocaleString()}</strong></div>
            <div><span>重复记录</span><strong>{result.stats.duplicate_rows.toLocaleString()}</strong></div>
          </div>
          <div className="result-tags">
            <Tag color="blue">{result.stats.columns} 个业务列</Tag>
            <Tag color={result.stats.deduplicated ? 'green' : 'grey'}>
              {result.stats.deduplicated ? '已去重' : '仅合并'}
            </Tag>
          </div>
        </section>
      )}
    </div>
  )
}
