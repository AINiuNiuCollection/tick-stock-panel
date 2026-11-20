/**
 * 缠论分析结果 Tab 列表 — 分型 / 笔 / 中枢 / 买卖点
 */
import { useState } from 'react'
import type { CzscAnalyzeResult, CzscBsPoint } from '@/lib/api'

interface Props {
  result: CzscAnalyzeResult
}

type Tab = 'fx' | 'bi' | 'zs' | 'bs'

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

  const bsList = result.bs_points ?? []
  const tabs: Array<{ key: Tab; label: string; count: number }> = [
    { key: 'fx', label: '分型', count: result.fx_list.length },
    { key: 'bi', label: '笔', count: result.bi_list.length },
    { key: 'zs', label: '中枢', count: result.zs_list.length },
    { key: 'bs', label: '买卖点', count: bsList.length },
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
        {tab === 'bs' && <BsTable list={bsList} />}
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
    <table className="w-full text-sm">
      <thead
        className="sticky top-0 z-10 shadow-sm"
        style={{ backgroundColor: '#1f2937', color: '#ffffff' }}
      >
        <tr>
          <th className="text-center p-2 font-bold text-base text-white">时间</th>
          <th className="text-center p-2 font-bold text-base text-white">类型</th>
          <th className="text-center p-2 font-bold text-base text-white">高价</th>
          <th className="text-center p-2 font-bold text-base text-white">低价</th>
        </tr>
      </thead>
      <tbody>
        {list.map((fx, i) => (
          <tr
            key={i}
            className={`border-t border-border ${i % 2 === 0 ? 'bg-elevated' : 'bg-base'} hover:bg-accent/10`}
          >
            <td className="p-2 text-center font-bold text-foreground">{fx.dt}</td>
            <td className="p-2 text-center font-bold">
              <span className={isTopMark(fx.mark) ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}>
                {isTopMark(fx.mark) ? '▲ 顶分型' : '▽ 底分型'}
              </span>
            </td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{fx.high.toFixed(2)}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{fx.low.toFixed(2)}</td>
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
      <thead
        className="sticky top-0 z-10 shadow-sm"
        style={{ backgroundColor: '#1f2937', color: '#ffffff' }}
      >
        <tr>
          <th className="text-center p-2 font-bold text-base text-white">起始</th>
          <th className="text-center p-2 font-bold text-base text-white">结束</th>
          <th className="text-center p-2 font-bold text-base text-white">方向</th>
          <th className="text-center p-2 font-bold text-base text-white">高</th>
          <th className="text-center p-2 font-bold text-base text-white">低</th>
          <th className="text-center p-2 font-bold text-base text-white">长度</th>
          <th className="text-center p-2 font-bold text-base text-white">力度</th>
        </tr>
      </thead>
      <tbody>
        {list.map((bi, i) => (
          <tr
            key={i}
            // 行底色交替: 偶数行 bg-elevated, 奇数行 bg-base, 不透明确保与文字对比清晰
            className={`border-t border-border ${i % 2 === 0 ? 'bg-elevated' : 'bg-base'} hover:bg-accent/10`}
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
    <table className="w-full text-sm">
      <thead
        className="sticky top-0 z-10 shadow-sm"
        style={{ backgroundColor: '#1f2937', color: '#ffffff' }}
      >
        <tr>
          <th className="text-center p-2 font-bold text-base text-white">起始</th>
          <th className="text-center p-2 font-bold text-base text-white">结束</th>
          <th className="text-center p-2 font-bold text-base text-white">下沿</th>
          <th className="text-center p-2 font-bold text-base text-white">上沿</th>
          <th className="text-center p-2 font-bold text-base text-white">级别</th>
          <th className="text-center p-2 font-bold text-base text-white">有效</th>
        </tr>
      </thead>
      <tbody>
        {list.map((zs, i) => (
          <tr
            key={i}
            className={`border-t border-border ${i % 2 === 0 ? 'bg-elevated' : 'bg-base'} hover:bg-accent/10`}
          >
            <td className="p-2 text-center font-bold text-foreground">{zs.start_dt}</td>
            <td className="p-2 text-center font-bold text-foreground">{zs.end_dt}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{zs.zs_range[0]?.toFixed(2)}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{zs.zs_range[1]?.toFixed(2)}</td>
            <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{zs.level}</td>
            <td className="p-2 text-center font-bold">
              <span className={zs.valid ? 'text-green-600 dark:text-green-400' : 'text-muted'}>{zs.valid ? '✓ 有效' : '✗ 无效'}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * 买卖点表格 — 严格按缠论背驰计算 (MACD面积 + DIF/DEA 高点)
 * 列: 日期 / 类型 / 方向 / 价位 / 关联中枢 / 背驰类型 / 命中条件
 *     / MACD面积对比 / DIF高点对比 / DEA高点对比 / 面积口径
 */
function BsTable({ list }: { list: CzscBsPoint[] }) {
  if (!list.length) return <div className="text-xs text-muted p-4">无买卖点数据 (本次未识别出符合背驰判据的买卖点)</div>
  return (
    <table className="w-full text-sm">
      <thead
        className="sticky top-0 z-10 shadow-sm"
        style={{ backgroundColor: '#1f2937', color: '#ffffff' }}
      >
        <tr>
          <th className="text-center p-2 font-bold text-base text-white">日期</th>
          <th className="text-center p-2 font-bold text-base text-white">类型</th>
          <th className="text-center p-2 font-bold text-base text-white">方向</th>
          <th className="text-center p-2 font-bold text-base text-white">价位</th>
          <th className="text-center p-2 font-bold text-base text-white">关联中枢</th>
          <th className="text-center p-2 font-bold text-base text-white">背驰类型</th>
          <th className="text-center p-2 font-bold text-base text-white">命中条件</th>
          <th className="text-center p-2 font-bold text-base text-white">MACD面积 (a→c)</th>
          <th className="text-center p-2 font-bold text-base text-white">DIF极值 (a→c)</th>
          <th className="text-center p-2 font-bold text-base text-white">面积口径</th>
        </tr>
      </thead>
      <tbody>
        {list.map((bp, i) => {
          const isBuy = bp.direction === '买'
          return (
            <tr
              key={i}
              className={`border-t border-border ${i % 2 === 0 ? 'bg-elevated' : 'bg-base'} hover:bg-accent/10`}
            >
              <td className="p-2 text-center font-bold text-foreground">{bp.dt.slice(0, 10)}</td>
              <td className="p-2 text-center font-bold">
                <span className={isBuy ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}>
                  {bp.type}
                </span>
              </td>
              <td className="p-2 text-center font-bold">
                <span className={isBuy ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}>
                  {isBuy ? '↑ 买' : '↓ 卖'}
                </span>
              </td>
              <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">{bp.price.toFixed(2)}</td>
              <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground">
                {bp.zs_index >= 0 ? `ZS${bp.zs_index + 1}` : '—'}
              </td>
              <td className="p-2 text-center font-bold text-foreground text-xs">{bp.divergence_type ?? '—'}</td>
              <td className="p-2 text-center font-bold text-foreground text-xs">
                {bp.divergence_pass.length ? bp.divergence_pass.join(' + ') : '—'}
              </td>
              <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground text-xs">
                {bp.macd_area_prev != null ? bp.macd_area_prev.toFixed(4) : '—'} → {bp.macd_area_cur != null ? bp.macd_area_cur.toFixed(4) : '—'}
              </td>
              <td className="p-2 text-center font-mono tabular-nums font-bold text-foreground text-xs">
                {bp.dif_peak_prev != null ? bp.dif_peak_prev.toFixed(4) : '—'} → {bp.dif_peak_cur != null ? bp.dif_peak_cur.toFixed(4) : '—'}
              </td>
              <td className="p-2 text-center font-bold text-foreground text-xs">{bp.macd_area_mode}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
