
"D:\CodeHub\github-tick-stock\tick-stock-panel\frontend\src\lib\api.ts"

  /** AI 迭代: 生成 v1 → 跑回测 → 诊断 → 修改 的有界闭环, 草稿已落盘 data/strategies/ai/ */
  strategyAiIterate: (payload: {
    name?: string
    description?: string
    direction?: string
    rules?: string
    execution_backend?: 'polars_expr' | 'matrix_native'
    max_rounds?: number
  }) =>
    request<AiIterateResult>('/api/strategies/ai/iterate', {
      method: 'POST',
      timeoutMs: null,
      body: JSON.stringify(payload),
    }),

  // ===== Memo (备忘录) =====
  listMemos: (params?: { tag?: string; type?: string; q?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams()
    if (params?.tag) qs.set('tag', params.tag)
    if (params?.type) qs.set('type', params.type)
    if (params?.q) qs.set('q', params.q)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const s = qs.toString()
    return request<{ items: MemoEntry[]; total: number }>(`/api/memo${s ? `?${s}` : ''}`)
  },
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
}

// ===== Pipeline =====
