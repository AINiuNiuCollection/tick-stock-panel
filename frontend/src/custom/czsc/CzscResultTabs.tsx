/**
 * 缠论分析结果 Tab 列表 — 分型 / 笔 / 中枢
 */
import { useState } from 'react'
import type { CzscAnalyzeResult } from '@/lib/api'

interface Props {
  result: CzscAnalyzeResult
}

type Tab = 'fx' | 'bi' | 'zs'

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
            className={`px-3 py-1.5 text-sm border-b-2 transition-colors ${
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
        <div className="text-xs text-amber-500 bg-amber-500/10 rounded-btn px-2 py-1">
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
      <thead className="text-muted sticky top-0 bg-base">
        <tr>
          <th className="text-left p-1.5">时间</th>
          <th className="text-left p-1.5">类型</th>
          <th className="text-right p-1.5">高价</th>
          <th className="text-right p-1.5">低价</th>
        </tr>
      </thead>
      <tbody>
        {list.map((fx, i) => (
          <tr key={i} className="border-t border-border">
            <td className="p-1.5">{fx.dt}</td>
            <td className="p-1.5">
              <span className={fx.mark === 'Mark.G' ? 'text-red-500' : 'text-green-500'}>
                {fx.mark === 'Mark.G' ? '▲ 顶分型' : '▽ 底分型'}
              </span>
            </td>
            <td className="p-1.5 text-right">{fx.high.toFixed(2)}</td>
            <td className="p-1.5 text-right">{fx.low.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function BiTable({ list }: { list: CzscAnalyzeResult['bi_list'] }) {
  if (!list.length) return <div className="text-xs text-muted p-4">无笔数据</div>
  return (
    <table className="w-full text-xs">
      <thead className="text-muted sticky top-0 bg-base">
        <tr>
          <th className="text-left p-1.5">起始</th>
          <th className="text-left p-1.5">结束</th>
          <th className="text-left p-1.5">方向</th>
          <th className="text-right p-1.5">高</th>
          <th className="text-right p-1.5">低</th>
          <th className="text-right p-1.5">长度</th>
          <th className="text-right p-1.5">力度</th>
        </tr>
      </thead>
      <tbody>
        {list.map((bi, i) => (
          <tr key={i} className="border-t border-border">
            <td className="p-1.5">{bi.sdt}</td>
            <td className="p-1.5">{bi.edt}</td>
            <td className={`p-1.5 ${bi.direction === 'Direction.Up' ? 'text-red-500' : 'text-green-500'}`}>
              {bi.direction === 'Direction.Up' ? '↑ 上' : '↓ 下'}
            </td>
            <td className="p-1.5 text-right">{bi.high.toFixed(2)}</td>
            <td className="p-1.5 text-right">{bi.low.toFixed(2)}</td>
            <td className="p-1.5 text-right">{bi.length}</td>
            <td className="p-1.5 text-right">{bi.power != null ? bi.power.toFixed(3) : '-'}</td>
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
      <thead className="text-muted sticky top-0 bg-base">
        <tr>
          <th className="text-left p-1.5">起始</th>
          <th className="text-left p-1.5">结束</th>
          <th className="text-right p-1.5">下沿</th>
          <th className="text-right p-1.5">上沿</th>
          <th className="text-right p-1.5">级别</th>
          <th className="text-left p-1.5">有效</th>
        </tr>
      </thead>
      <tbody>
        {list.map((zs, i) => (
          <tr key={i} className="border-t border-border">
            <td className="p-1.5">{zs.start_dt}</td>
            <td className="p-1.5">{zs.end_dt}</td>
            <td className="p-1.5 text-right">{zs.zs_range[0]?.toFixed(2)}</td>
            <td className="p-1.5 text-right">{zs.zs_range[1]?.toFixed(2)}</td>
            <td className="p-1.5 text-right">{zs.level}</td>
            <td className="p-1.5">
              <span className={zs.valid ? 'text-green-500' : 'text-muted'}>{zs.valid ? '✓' : '✗'}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
