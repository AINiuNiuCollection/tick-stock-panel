/**
 * 上证-异动波段策略扩展 — 前端注册入口
 *
 * 提供:
 *   - /shangzheng 弹窗页 (window.open 打开, 不在导航菜单显示)
 *     上证指数跟踪: 信号源=上证指数(写死), 交易标的可配置(默认 512100.SH 中证1000ETF)
 *     后端在指数上算信号, 前端用信号日对齐交易标的 K 线重算盈亏 (matching=open_t+1)
 *
 * 通过 extensions/registry.ts 自动发现, 不修改 router.tsx / Layout.tsx。
 * 入口: StrategyBacktest 策略列表的「单独回测」按钮 → window.open('/shangzheng?...')
 */
import type { FrontendExtension } from '@/extensions/types'
import { ShangZhengPage } from './ShangZhengPage'

const extension: FrontendExtension = {
  id: 'tsp.shangzheng',
  apiVersion: 1,
  routes: [
    { id: 'shangzheng', path: '/shangzheng', component: ShangZhengPage },
  ],
  // 不注册 navigation — 此页面仅由「单独回测」按钮 window.open 弹出
}

export default extension
