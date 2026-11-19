/**
 * 缠论分析结果 Tab 列表 — 分型 / 笔 / 中枢
 */
import { useState } from 'react'
import type { CzscAnalyzeResult } from '@/lib/api'

interface Props {
  result: CzscAnalyzeResult
}

type Tab = 'fx' | 'bi' | 'zs'

/** 判断顶分型: czsc 1.0.2 返回 mark='顶分型' (旧版 'Mark.G') */
function isTopMark(mark: string): boolean {
  return mark === 'Mark.G' || mark === '顶分型' || mark.includes('顶')
}

/** 判断向上笔: czsc 1.0.2 返回 direction='向上' (旧版 'Direction.Up') */
function isUpDirection(direction: string): boolean {
  return direction === 'Direction.Up' || direction === '向上' || direction.includes('上')
}

export function CzscResultTabs({ result }: Props) {
  const [tab, setTab] = useState<Tab>('bi')

  const tabs: Array<{ key: Tab; label: string; count: number }> = [
    { key: 'fx', label: '分型', count: result.fx_list.length },
    { key: 'bi', label: '笔', count: result.bi_list.length },
    { key: 'zs', label: '中枢', count: result.zs_list.length },
  ]

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex gap-1 border-b border-border">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted hover:text-foreground'
            }`}
          >
            {t.label} ({t.count})
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto">
        {tab === 'fx' && <FxTable list={result.fx_list} />}
        {tab === 'bi' && <BiTable list={result.bi_list} />}
        {tab === 'zs' && <ZsTable list={result.zs_list} />}
      </div>

      {result.warnings && result.warnings.length > 0 && (
        <div className="text-xs text-amber-600 dark:text-amber-400 bg-amber-500/15 rounded-btn px-2 py-1">
          ⚠ {result.warnings.join('; ')}
        </div>
      )}
    </div>
  )
}

function FxTable({ list }: { list: CzscAnalyzeResult['fx_list'] }) {
  if (!list.length) return <div className="text-xs text-muted p-4">无分型数据</div>
  return (
    <table className="w-full text-xs">
      <thead className="text-foreground sticky top-0 bg-elevated z-10 shadow-sm">
        <tr>
          <th className="text-left p-1.5 font-medium">时间</th>
          <th className="text-left p-1.5 font-medium">类型</th>
          <th className="text-right p-1.5 font-medium">高价</th>
          <th className="text-right p-1.5 font-medium">低价</th>
        </tr>
      </thead>
      <tbody>
        {list.map((fx, i) => (
          <tr key={i} className="border-t border-border hover:bg-base/50">
            <td className="p-1.5 text-foreground/90">{fx.dt}</td>
            <td className="p-1.5">
              <span className={`font-medium ${isTopMark(fx.mark) ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                {isTopMark(fx.mark) ? '▲ 顶分型' : '▽ 底分型'}
              </span>
            </td>
            <td className="p-1.5 text-right font-mono tabular-nums text-foreground">{fx.high.toFixed(2)}</td>
            <td className="p-1.5 text-right font-mono tabular-nums text-foreground">{fx.low.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function BiTable({ list }: { list: CzscAnalyzeResult['bi_list'] }) {
  if (!list.length) return <div className="text-xs text-muted p-4">无笔数据</div>
  return (
    <table className="w-full text-sm">
      <thead className="text-foreground sticky top-0 bg-elevated z-10 shadow-sm">
        <tr>
          <th className="text-center p-2 font-bold text-sm">起始</th>
          <th className="text-center p-2 font-bold text-sm">结束</th>
          <th className="text-center p-2 font-bold text-sm">方向</th>
          <th className="text-center p-2 font-bold text-sm">高</th>
          <th className="text-center p-2 font-bold text-sm">低</th>
          <th className="text-center p-2 font-bold text-sm">长度</th>
          <th className="text-center p-2 font-bold text-sm">力度</th>
        </tr>
      </thead>
      <tbody>
        {list.map((bi, i) => (
          <tr
            key={i}
            // 行底色交替: 奇数行浅黑 (bg-elevated), 偶数行浅灰 (bg-base)
            // bg-elevated / bg-base 是工程 CSS 变量映射, dark 下分别为 #212126 / #0A0A0B
            className={`border-t border-border ${i % 2 === 0 ? 'bg-elevated/60' : 'bg-base/60'} hover:bg-accent/10`}
          >
            <td className="p-2 text-center font-bold text-foreground">{bi.sdt}</td>
            <td className="p-2 text-center font-bold text-foreground">{bi.edt}</td>
            <td className={`p-2 text-center font-bold ${isUpDirection(bi.direction) ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
              {isUpDirection(bi.direction) ? '↑ 上' : '↓ 下'}
            </td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{bi.high.toFixed(2)}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{bi.low.toFixed(2)}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{bi.length}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{bi.power != null ? bi.power.toFixed(3) : '-'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ZsTable({ list }: { list: CzscAnalyzeResult['zs_list'] }) {
  if (!list.length) return <div className="text-xs text-muted p-4">无中枢数据</div>
  return (
    <table className="w-full text-xs">
      <thead className="text-foreground sticky top-0 bg-elevated z-10 shadow-sm">
        <tr>
          <th className="text-left p-1.5 font-medium">起始</th>
          <th className="text-left p-1.5 font-medium">结束</th>
          <th className="text-right p-1.5 font-medium">下沿</th>
          <th className="text-right p-1.5 font-medium">上沿</th>
          <th className="text-right p-1.5 font-medium">级别</th>
          <th className="text-left p-1.5 font-medium">有效</th>
        </tr>
      </thead>
      <tbody>
        {list.map((zs, i) => (
          <tr key={i} className="border-t border-border hover:bg-base/50">
            <td className="p-1.5 text-foreground/90">{zs.start_dt}</td>
            <td className="p-1.5 text-foreground/90">{zs.end_dt}</td>
            <td className="p-1.5 text-right font-mono tabular-nums text-foreground">{zs.zs_range[0]?.toFixed(2)}</td>
            <td className="p-1.5 text-right font-mono tabular-nums text-foreground">{zs.zs_range[1]?.toFixed(2)}</td>
            <td className="p-1.5 text-right font-mono tabular-nums text-foreground">{zs.level}</td>
            <td className="p-1.5">
              <span className={`font-medium ${zs.valid ? 'text-green-600 dark:text-green-400' : 'text-muted'}`}>{zs.valid ? '✓ 有效' : '✗ 无效'}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
