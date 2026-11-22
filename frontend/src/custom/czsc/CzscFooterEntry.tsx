/**
 * stock-preview.footer 插槽入口 — 在个股对话框内弹出二级弹层 (Q7)
 *
 * 不修改 StockPreviewDialog.tsx, 通过插槽 context {symbol, name, view} 获取标的。
 * 点击「缠论分析」按钮 → 弹出 Modal, 内嵌精简版分析面板。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Modal } from '@/components/Modal'
import { fetchCzscAnalyze, fetchCzscHealth, type CzscAnalyzeResult } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import type { FrontendSlotContextMap } from '@/extensions/types'
import { CzscChart } from './CzscChart'
import { CzscResultTabs } from './CzscResultTabs'

type SlotProps = FrontendSlotContextMap['stock-preview.footer']

export function CzscFooterEntry({ symbol, name }: SlotProps) {
  // view 字段插槽提供但本入口不使用 (首版仅日K)
  const [open, setOpen] = useState(false)

  const health = useQuery({
    queryKey: QK.czscHealth,
    queryFn: fetchCzscHealth,
    staleTime: 30_000,
    enabled: open,
  })

  const analyze = useQuery<CzscAnalyzeResult>({
    queryKey: QK.czscAnalyze(symbol, '日线'),
    queryFn: () => fetchCzscAnalyze({ symbol, freq: '日线', features: 'fx,bi,zs' }),
    enabled: open && health.data?.ok === true,
    staleTime: 5 * 60_000,
  })

  const serveOk = health.data?.ok === true

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center h-7 px-2.5 rounded-btn bg-elevated text-xs text-secondary hover:bg-elevated/80 hover:text-foreground transition-colors"
      >
        缠论分析
      </button>

      {open && (
        <Modal
          onClose={() => setOpen(false)}
          ariaLabel={`缠论分析 · ${symbol} ${name ?? ''}`}
          panelClassName="w-full max-w-5xl max-h-[85vh] bg-base rounded-lg shadow-xl flex flex-col"
        >
          <div className="flex items-center justify-between px-4 py-2 border-b border-border">
            <h2 id="czsc-dialog-title" className="text-sm font-medium">
              缠论分析 · {symbol} {name ?? ''}
            </h2>
            <span className={`inline-flex items-center gap-1 text-xs ${serveOk ? 'text-green-500' : 'text-red-500'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${serveOk ? 'bg-green-500' : 'bg-red-500'}`} />
              {serveOk ? '服务在线' : '服务未启动'}
            </span>
          </div>

          <div className="flex-1 overflow-auto p-3">
            {!serveOk ? (
              <div className="text-xs text-amber-500 bg-amber-500/10 rounded-btn px-3 py-2">
                ⚠ 缠论后端未就绪。请执行:
                <code className="mx-1 px-1 bg-elevated rounded">cd backend && uv sync --extra czsc</code>
                安装依赖后重启后端。
              </div>
            ) : analyze.isFetching ? (
              <div className="text-center text-sm text-muted py-8">分析中…</div>
            ) : analyze.isError ? (
              <div className="text-center text-sm text-red-500 py-8">分析失败, 请重试</div>
            ) : analyze.data ? (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <div className="lg:col-span-2 bg-elevated rounded-btn p-2">
                  <CzscChart result={analyze.data} height={560} />
                </div>
                <div className="bg-elevated rounded-btn p-2 max-h-[420px] overflow-auto">
                  <CzscResultTabs result={analyze.data} />
                </div>
              </div>
            ) : null}
          </div>
        </Modal>
      )}
    </>
  )
}
