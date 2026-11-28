/**
 * 大盘研究页 (/market 路由) — 5 Tab 布局
 *
 * 设计文档: docs/index_tracker_design_2026-11-27.md §5
 * 本期实装 (后端 API 已就绪):
 *   - 总览仪表盘: /api/market/overview 快照 (v2 Tab 0, 设计 §1.1)
 *   - 政策事件: /api/market/events + /events/series 三层联动 (P3)
 *   - 缠论多级别: /api/czsc/analyze 分析上证指数 (P0-2 深历史)
 *   - 策略实验室: /api/market 信号注册表/回测/寻优 (P1/P2)
 *   - 市场结构: /api/market/breadth 宽度走势 (v3-⑤)
 */
import { useState } from 'react'
import { PageHeader } from '@/components/PageHeader'
import { MarketCzscTab } from './MarketCzscTab'
import { MarketEventsTab } from './MarketEventsTab'
import { MarketLab } from './MarketLab'
import { MarketOverviewTab } from './MarketOverviewTab'
import { MarketStructureTab } from './MarketStructureTab'

type TabKey = 'overview' | 'events' | 'czsc' | 'lab' | 'structure'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: '总览' },
  { key: 'events', label: '政策事件' },
  { key: 'czsc', label: '缠论多级别' },
  { key: 'lab', label: '策略实验室' },
  { key: 'structure', label: '市场结构' },
]

export function MarketPage() {
  const [tab, setTab] = useState<TabKey>('lab')

  return (
    <div className="flex flex-col h-full min-h-0">
      <PageHeader
        title="大盘研究"
        subtitle="上证指数信号/回测/寻优 — 信号源=白名单指数, 交易标的=宽基ETF"
      />
      <nav className="flex gap-1 px-5 pt-2 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-accent text-foreground'
                : 'border-transparent text-muted hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="flex-1 min-h-0 overflow-hidden">
        {tab === 'overview' && <MarketOverviewTab />}
        {tab === 'events' && <MarketEventsTab />}
        {tab === 'czsc' && <MarketCzscTab />}
        {tab === 'lab' && <MarketLab />}
        {tab === 'structure' && <MarketStructureTab />}
      </main>
    </div>
  )
}
