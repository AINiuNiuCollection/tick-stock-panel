/**
 * 大盘研究 — 缠论 Tab (指数多级别结构分析)
 *
 * 复用缠论扩展的分析链路 (/api/czsc/analyze, P0-2 后 IndexDailyKlineSource
 * 挂链首位, 白名单指数直接出深历史), 标的固定上证指数 000001.SH,
 * 级别可切 日线 / 周线 / 月线 (月线可出 1990→今 36 年结构)。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchCzscAnalyze } from '@/lib/api'
import { EmptyState } from '@/components/EmptyState'
import { CzscChart } from '@/custom/czsc/CzscChart'
import { CzscResultTabs } from '@/custom/czsc/CzscResultTabs'

const INDEX_SYMBOL = '000001.SH'
const FREQ_OPTIONS = ['日线', '周线', '月线']

export function MarketCzscTab() {
  const [freq, setFreq] = useState('月线')
  const [submitted, setSubmitted] = useState<{ freq: string } | null>(null)

  const analyze = useQuery({
    queryKey: ['market-czsc-analyze', INDEX_SYMBOL, submitted?.freq],
    queryFn: () =>
      fetchCzscAnalyze({
        symbol: INDEX_SYMBOL,
        freq: submitted!.freq,
        max_bi_num: freq === '月线' ? 200 : 100,
        min_bi_len: 7,
        features: 'fx,bi,zs,bs_points',
        ma_periods: [5, 10, 20],
      }),
    enabled: submitted !== null,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
  })

  return (
    <div className="flex flex-col gap-3 p-3 h-full min-h-0">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setSubmitted({ freq })
        }}
        className="flex flex-wrap items-end gap-3 p-3 bg-elevated rounded-btn"
      >
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">标的</span>
          <span className="h-8 px-2 py-1 text-sm leading-[1.42857143]">上证指数 {INDEX_SYMBOL}</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">级别</span>
          <select
            value={freq}
            onChange={(e) => setFreq(e.target.value)}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
          >
            {FREQ_OPTIONS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={analyze.isFetching}
          className="h-8 min-w-[80px] px-3 py-1 rounded-[3px] bg-accent text-white text-sm font-normal leading-[1.42857143] transition-colors hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {analyze.isFetching ? '分析中…' : '分析'}
        </button>
        {submitted && (
          <span className="text-xs text-muted">
            {submitted.freq} · 笔 {analyze.data?.bi_list.length ?? '—'} · 中枢 {analyze.data?.zs_list.length ?? '—'}
            {analyze.data?.bars.length ? ` · ${analyze.data.bars[0].dt} → ${analyze.data.bars[analyze.data.bars.length - 1].dt}` : ''}
          </span>
        )}
      </form>

      {analyze.isError ? (
        <EmptyState title="缠论分析失败" hint="请确认后端已加载 /api/czsc 路由且指数日K数据已回填" />
      ) : analyze.isFetching && !analyze.data ? (
        <EmptyState title="拉取指数深历史并计算缠论结构中…" />
      ) : !analyze.data ? (
        <EmptyState title="点击「分析」查看指数多级别缠论结构" hint="月线可出 1990→今 36 年结构 (IndexDailyKlineSource 深历史)" />
      ) : (
        <>
          <section className="bg-elevated rounded-btn p-3 shrink-0">
            <CzscChart result={analyze.data} height={420} maPeriods={[5, 10, 20]} />
          </section>
          <section className="bg-elevated rounded-btn p-3 min-h-0 flex-1 overflow-hidden flex flex-col">
            <CzscResultTabs result={analyze.data} />
          </section>
        </>
      )}
    </div>
  )
}
