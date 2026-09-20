
"D:\CodeHub\github-tick-stock\tick-stock-panel\frontend\src\lib\api.ts"

添加地方：最后添加

// ===== Memo types =====
export type MemoType = 'note' | 'bug' | 'param' | 'idea' | 'todo' | 'insight'

export interface MemoEntry {
  id: string
  title: string
  content: string
  tags: string[]
  type: MemoType
  pinned: boolean
  related_symbol?: string[]
  related_strategy?: string[]
  created_at: string
  updated_at: string
}
