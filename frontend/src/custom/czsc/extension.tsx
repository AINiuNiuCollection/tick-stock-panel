/**
 * czsc 缠论分析扩展 — 前端注册入口
 *
 * 提供:
 *   - /czsc 独立分析页 (含参数面板)
 *   - stock-preview.footer 插槽: 在个股对话框内弹出二级弹层
 *
 * 通过 extensions/registry.ts 自动发现, 不修改 router.tsx / Layout.tsx。
 */
import { Activity } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { CzscPage } from './CzscPage'
import { CzscFooterEntry } from './CzscFooterEntry'

// FrontendExtension.slots 数组在不同 K 间不协变 (ComponentType 逆变),
// 需用 as 断言 — 运行时 registry 只按 name 分桶, 类型断言不影响行为。
// 参考 _template/extension.tsx.example 的写法 (模板未参与 tsc 编译故未暴露)。
const extension: FrontendExtension = {
  id: 'tsp.czsc',
  apiVersion: 1,
  routes: [
    { id: 'czsc', path: '/czsc', component: CzscPage },
  ],
  navigation: [
    { id: 'czsc', routeId: 'czsc', label: '缠论分析', icon: Activity, order: 600 },
  ],
  slots: [
    {
      name: 'stock-preview.footer',
      id: 'czsc-stock-footer',
      order: 50,
      component: CzscFooterEntry,
    },
  ] as FrontendExtension['slots'],
}

export default extension
