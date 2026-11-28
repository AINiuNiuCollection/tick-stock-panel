/**
 * 大盘研究扩展 — 前端注册入口
 *
 * 提供:
 *   - /market 大盘研究页 (5 Tab: 总览/政策事件/缠论多级别/策略实验室/市场结构)
 *     本期实装: 缠论多级别 (指数深历史结构) + 策略实验室 (信号注册表/回测/寻优)
 *
 * 通过 extensions/registry.ts 自动发现, 不修改 router.tsx / Layout.tsx。
 * 设计文档: docs/index_tracker_design_2026-11-27.md
 */
import { LineChart } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { MarketPage } from './MarketPage'

const extension: FrontendExtension = {
  id: 'tsp.market',
  apiVersion: 1,
  routes: [
    { id: 'market', path: '/market', component: MarketPage },
  ],
  navigation: [
    { id: 'market', routeId: 'market', label: '大盘研究', icon: LineChart, order: 650 },
  ],
}

export default extension
