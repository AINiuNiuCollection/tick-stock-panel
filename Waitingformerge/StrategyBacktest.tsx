const buildDefaultOverrides = (detail: StrategyDetail) => normalizeStrategyOverrides(detail, {
  basic_filter: { ...detail.basic_filter },
  entry_signals: detail.entry_signals.map(toSignalId),
  exit_signals: detail.exit_signals.map(toSignalId),
  scoring: { ...detail.scoring },
  scoring_directions: { ...(detail.scoring_directions ?? {}) },
  scoring_replace: true,
  stop_loss: detail.stop_loss,
  take_profit: detail.take_profit,
  trailing_stop: detail.trailing_stop,
  trailing_take_profit_activate: detail.trailing_take_profit_activate,
  trailing_take_profit_drawdown: detail.trailing_take_profit_drawdown,
  score_min: null,
  score_max: null,
  max_hold_days: detail.max_hold_days,
  // ── 连亏冷却: 从策略详情提取, 供回测 override 使用 ──
  cooldown_loss_streak: detail.cooldown_loss_streak,
  cooldown_days: detail.cooldown_days,
})

const strategyBacktestConfigSignature = (detail: StrategyDetail) => JSON.stringify({
  execution_backend: detail.execution_backend,
  basic_filter: detail.basic_filter,
  params: detail.params,
  params_defaults: detail.params_defaults,
  scoring: detail.scoring,
  scoring_directions: detail.scoring_directions,
  entry_signals: detail.entry_signals,
  exit_signals: detail.exit_signals,
  stop_loss: detail.stop_loss,
  take_profit: detail.take_profit,
  trailing_stop: detail.trailing_stop,
  trailing_take_profit_activate: detail.trailing_take_profit_activate,
  trailing_take_profit_drawdown: detail.trailing_take_profit_drawdown,
  max_hold_days: detail.max_hold_days,
  // ── 连亏冷却: 纳入配置签名, 冷却参数变化时触发重算 ──
  cooldown_loss_streak: detail.cooldown_loss_streak,
  cooldown_days: detail.cooldown_days,
})














******************************************************
  // 刷新页面后: 从 localStorage 恢复未完成的回测任务
  useEffect(() => {
    tryReconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const detail = strategyDetail.data
    if (!detail) return
    const configSignature = strategyBacktestConfigSignature(detail)
    const configKey = `${assetType}:${detail.id}:${configSignature}`
    if (loadedStrategyRef.current === configKey) return
    loadedStrategyRef.current = configKey
    if (
      saved?.assetType === assetType
      && saved.selectedStrategy === detail.id
      && saved.strategyConfigSignature === configSignature
      && (saved.params || saved.overrides)
    ) {
      setStrategyParams(mergeStrategyParams(detail, saved.params))
      setOverrides(normalizeStrategyOverrides(detail, saved.overrides ?? buildDefaultOverrides(detail)))
      return
    }
    resetConfigFromDetail(detail)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetType, strategyDetail.data])

  // 当全局回测任务完成时, 把结果写入组件 (切页回来也能恢复)
  useEffect(() => {
    if (backtestTask && !backtestTask.isPending && backtestTask.result) {
      const btResult = backtestTask.result
      setResult(btResult)
      setSharedResult(btResult)  // 自动保存到共享存储, 供分析页面使用
      setResultTab('daily')
      setDailyPage(0)
      setTradePage(0)
      storage.strategyBacktestLast.set({
        selectedStrategy,
        symbols,
        assetType,
        start,
        end,
        matching,
        entryFill,
        exitFill,
        fees,
        stampTax,
        slippage,
        maxPositions,
        maxExposure,
        initialCapital,
        positionSizing,
        mode: simMode,
        holdingDays,
        minuteFill: isMinuteStrategy ? false : highGranularity,
        regimeStates,
        regimeMinScore,
        params: strategyParams,
        overrides,
        strategyConfigSignature: strategyDetail.data
          ? strategyBacktestConfigSignature(strategyDetail.data)
          : undefined,
        result: btResult,
      })

      // ── 静默保存回测历史记录(含完整参数+名称映射), 不阻塞、不报错 ──
      // labels 提取: 策略参数 label / 信号名称 / 因子中文名 — 供分析页"回测参数"Tab 展示
      const detailData = strategyDetail.data
      const paramLabels: Record<string, string> = {}
      if (detailData) {
        for (const p of detailData.params) paramLabels[p.id] = p.label
      }
      const signalLabels: Record<string, string> = { ...signalNames }
      const factorLabelsObj: Record<string, string> = {}
      factorLabels.forEach((label, id) => { factorLabelsObj[id] = label })

      api.backtestHistorySave({
        result: btResult,
        labels: {
          strategy_name: detailData?.name ?? btResult.strategy_info?.name ?? '',
          param_labels: paramLabels,
          signal_labels: signalLabels,
          factor_labels: factorLabelsObj,
        },
      }).catch(() => { /* 静默失败: 不影响回测结果展示 */ })
    }
  }, [backtestTask])









********************************************************************************************
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">连亏冷却(笔)</span>
                      <NumberField
                        value={numOrNull(cooldownLossStreakValue)}
                        min={0} step={1}
                        onChange={n => updateOverride('cooldown_loss_streak', n == null ? null : Math.round(n))}
                        className={INPUT_CLS}
                      />
                      {/* min=0: 0 = 不生效 (后端 cooldown_loss_streak > 0 守卫) */}
                      <span className="mt-0.5 block text-[10px] text-muted">0 = 不生效</span>
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">冷却天数(天)</span>
                      <NumberField
                        value={numOrNull(cooldownDaysValue)}
                        min={1} step={1}
                        onChange={n => updateOverride('cooldown_days', n == null ? null : Math.round(n))}
                        className={INPUT_CLS}
                      />
                    </label>
                  </div>
                </ConfigSection>
              )}
            </div>





    




  
