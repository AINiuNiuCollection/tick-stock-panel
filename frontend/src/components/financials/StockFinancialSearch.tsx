import { SymbolPicker } from '@/components/SymbolPicker'

interface Props {
  onSelect: (symbol: string, name: string) => void
  /** 搜索资产类型, 逗号分隔 (默认 'stock')。如 'stock,index' */
  assetTypes?: string
}

/**
 * 个股模糊搜索框 —— 财务页主入口。
 * 复用通用 SymbolPicker (代码 / 名称 / 拼音首字母模糊匹配), 单选即跳转该股财务详情。
 * 模式对齐 Watchlist.StockSearchBox:useQuery + 外部点击关闭 + 键盘导航。
 *
 * 本组件已退化为 SymbolPicker 的薄包装, 保持财务页调用方零改动。
 */
export function StockFinancialSearch({ onSelect, assetTypes = 'stock' }: Props) {
  return (
    <SymbolPicker
      onSelect={onSelect}
      assetTypes={assetTypes}
      size="md"
      placeholder="输入股票代码或名称，如 600000 / 浦发"
      className="w-full max-w-xl mx-auto"
    />
  )
}
