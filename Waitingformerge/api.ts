
"D:\CodeHub\github-tick-stock\tick-stock-panel\frontend\src\lib\api.ts"

  createMemo: (body: {
    title?: string
    content: string
    tags?: string[]
    type?: MemoType
    pinned?: boolean
    related_symbol?: string[]
    related_strategy?: string[]
  }) =>
    request<MemoEntry>('/api/memo', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateMemo: (id: string, patch: Partial<{
    title: string
    content: string
    tags: string[]
    type: MemoType
    pinned: boolean
    related_symbol: string[]
    related_strategy: string[]
  }>) =>
    request<MemoEntry>(`/api/memo/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteMemo: (id: string) =>
    request<{ ok: boolean }>(`/api/memo/${id}`, { method: 'DELETE' }),
  batchDeleteMemos: (ids: string[]) =>
    request<{ deleted: number }>('/api/memo/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  toggleMemoPin: (id: string, pinned: boolean) =>
    request<MemoEntry>(`/api/memo/${id}/pin`, {
      method: 'PATCH',
      body: JSON.stringify({ pinned }),
    }),
  getMemoTags: () =>
    request<{ tag: string; count: number }[]>('/api/memo/tags'),
  exportMemos: (year: number, month: number) =>
    request<{ content: string }>(`/api/memo/export?year=${year}&month=${month}`),

  // ===== Knowledge (知识库) =====
  listKnowledge: (params?: { category?: string; q?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.category) qs.set('category', params.category)
    if (params?.q) qs.set('q', params.q)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    const s = qs.toString()
    return request<{ items: KnowledgeEntry[]; total: number }>(`/api/knowledge${s ? `?${s}` : ''}`)
  },
  getKnowledge: (id: string) =>
    request<KnowledgeEntry>(`/api/knowledge/${id}`),
  getKnowledgeCategories: () =>
    request<{ category: string; label: string; count: number }[]>('/api/knowledge/categories'),
}

// ===== Knowledge types =====
export type KnowledgeCategory = 'basics' | 'indicators' | 'patterns' | 'strategies' | 'risk' | 'terms' | 'macro'

export interface KnowledgeEntry {
  id: string
  category: KnowledgeCategory
  title: string
  summary: string
  content: string
  tags: string[]
}
export interface PipelineJob {
  id: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  stage: string
  progress: number          // 0-100 整体进度
  stage_pct: number         // 0-100 当前阶段内进度
  log: { ts: string; stage: string; msg: string }[]
  started_at: string | null
  finished_at: string | null
  duration_s: number | null
  result: {
    universe_size: number
    daily_days: number
    adj_factor_symbols: number
    enriched_days: number
    index_count?: number
    index_daily_rows?: number
    minute_rows: number
    skipped_stages?: string[]
  } | null
  error: string | null
}
