frontend/src/pages/backtest/StrategyBacktest.tsx

删除  3100-3110行

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
