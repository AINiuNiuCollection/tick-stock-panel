  // ── 回测历史记录 API ──
  // 回测完成后自动保存完整结果+参数标签, 供"回测分析"页历史记录列表加载
  backtestHistoryList: () =>
    request<{ items: BacktestHistoryMeta[] }>('/api/backtest/history'),

  backtestHistoryDetail: (id: string) =>
    request<BacktestHistoryRecord>(`/api/backtest/history/${encodeURIComponent(id)}`),

  backtestHistorySave: (payload: { result: StrategyBacktestResult; labels?: Record<string, any>; name?: string }) =>
    request<BacktestHistoryMeta>('/api/backtest/history', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  backtestHistoryRename: (id: string, name: string) =>
    request<BacktestHistoryMeta>(`/api/backtest/history/${encodeURIComponent(id)}?name=${encodeURIComponent(name)}`, {
      method: 'PATCH',
    }),

  backtestHistoryDelete: (id: string) =>
    request<{ ok: boolean }>(`/api/backtest/history/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  strategyBacktestRun: (payload: {
