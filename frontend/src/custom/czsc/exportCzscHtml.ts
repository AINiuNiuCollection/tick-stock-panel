/**
 * 缠论分析结论 HTML 导出 — 生成自包含 HTML 字符串 (前端 Blob 下载)。
 *
 * 设计:
 *   - 纯前端实现, 无后端依赖, 无新 npm 包
 *   - HTML 字符串含内联 CSS + 表格 + 嵌入 K 线图 (base64 PNG, 由 echarts.getDataURL 提供)
 *   - 文件可离线打开, 与现有 Review.tsx 下载 Markdown 模式一致 (Blob + createObjectURL + a.click)
 *
 * 兼容 czsc 1.0.2 与旧版契约:
 *   - 分型 mark: '顶分型' (1.0.2) / 'Mark.G' (旧版) → 顶分型
 *   - 笔 direction: '向上' (1.0.2) / 'Direction.Up' (旧版) → 向上
 */
import type { CzscAnalyzeResult } from '@/lib/api'

function isTopMark(mark: string): boolean {
  return mark === 'Mark.G' || mark === '顶分型' || mark.includes('顶')
}

function isUpDirection(direction: string): boolean {
  return direction === 'Direction.Up' || direction === '向上' || direction.includes('上')
}

function esc(s: string | number | null | undefined): string {
  if (s == null) return ''
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch] as string))
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toFixed(digits)
}

/** 生成自包含 HTML 字符串。chartDataURL 可选 (base64 PNG, 来自 echarts.getDataURL)。 */
export function buildCzscHtml(
  result: CzscAnalyzeResult,
  chartDataURL: string | null,
  generatedAt: Date = new Date(),
): string {
  const ts = generatedAt.toISOString().replace('T', ' ').slice(0, 19)
  const fxRows = result.fx_list.map(fx => `
      <tr>
        <td>${esc(fx.dt)}</td>
        <td class="${isTopMark(fx.mark) ? 'up' : 'down'}">${isTopMark(fx.mark) ? '▲ 顶分型' : '▽ 底分型'}</td>
        <td class="num">${fmtNum(fx.high)}</td>
        <td class="num">${fmtNum(fx.low)}</td>
      </tr>`).join('')

  const biRows = result.bi_list.map(bi => `
      <tr>
        <td>${esc(bi.sdt)}</td>
        <td>${esc(bi.edt)}</td>
        <td class="${isUpDirection(bi.direction) ? 'up' : 'down'}">${isUpDirection(bi.direction) ? '↑ 向上' : '↓ 向下'}</td>
        <td class="num">${fmtNum(bi.high)}</td>
        <td class="num">${fmtNum(bi.low)}</td>
        <td class="num">${bi.length}</td>
        <td class="num">${fmtNum(bi.power, 3)}</td>
      </tr>`).join('')

  const zsRows = result.zs_list.map(zs => `
      <tr>
        <td>${esc(zs.start_dt)}</td>
        <td>${esc(zs.end_dt)}</td>
        <td class="num">${fmtNum(zs.zs_range[0])}</td>
        <td class="num">${fmtNum(zs.zs_range[1])}</td>
        ${'zd' in zs ? `<td class="num">${fmtNum((zs as { zd?: number }).zd)}</td>` : '<td>-</td>'}
        ${'zg' in zs ? `<td class="num">${fmtNum((zs as { zg?: number }).zg)}</td>` : '<td>-</td>'}
        <td class="${zs.valid ? 'up' : 'muted'}">${zs.valid ? '✓ 有效' : '✗ 无效'}</td>
      </tr>`).join('')

  const signalRows = Object.entries(result.signals || {}).map(([k, v]) => `
      <tr>
        <td>${esc(k)}</td>
        <td>${esc(typeof v === 'object' ? JSON.stringify(v) : String(v))}</td>
      </tr>`).join('')

  const chartHtml = chartDataURL
    ? `<section><h2>K 线图 (分型 / 笔 / 中枢标记)</h2><img class="chart" src="${esc(chartDataURL)}" alt="czsc chart"/></section>`
    : ''

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>缠论分析报告 ${esc(result.symbol)} ${esc(result.freq)}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f8fafc; color: #1e293b; line-height: 1.6; }
  .container { max-width: 1200px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); padding: 32px; }
  h1 { font-size: 22px; margin: 0 0 4px 0; }
  h2 { font-size: 16px; margin: 28px 0 12px 0; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }
  .meta { color: #64748b; font-size: 13px; margin-bottom: 24px; }
  .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin: 16px 0 24px 0; }
  .summary .card { background: #f1f5f9; border-radius: 6px; padding: 12px 16px; }
  .summary .label { color: #64748b; font-size: 12px; }
  .summary .value { font-size: 20px; font-weight: 600; color: #0f172a; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px; }
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
  th { background: #f8fafc; font-weight: 600; color: #475569; font-size: 12px; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  tr:hover td { background: #f8fafc; }
  .up { color: #dc2626; }
  .down { color: #16a34a; }
  .muted { color: #94a3b8; }
  .chart { max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 4px; }
  .footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 12px; }
  .empty { color: #94a3b8; padding: 16px; text-align: center; }
</style>
</head>
<body>
<div class="container">
  <h1>缠论分析报告 · ${esc(result.symbol)}</h1>
  <div class="meta">
    频率: ${esc(result.freq)} ·
    生成时间: ${esc(ts)} ·
    数据源: ${esc(result.source)}${result.cached ? ' · 缓存' : ' · 实时'}
  </div>

  <div class="summary">
    <div class="card"><div class="label">K 线数</div><div class="value">${result.bar_count}</div></div>
    <div class="card"><div class="label">分型</div><div class="value">${result.fx_list.length}</div></div>
    <div class="card"><div class="label">笔</div><div class="value">${result.bi_list.length}</div></div>
    <div class="card"><div class="label">中枢</div><div class="value">${result.zs_list.length}</div></div>
  </div>

  ${chartHtml}

  <section>
    <h2>笔 (${result.bi_list.length})</h2>
    ${result.bi_list.length ? `<table>
      <thead><tr><th>起始</th><th>结束</th><th>方向</th><th class="num">高</th><th class="num">低</th><th class="num">长度</th><th class="num">力度</th></tr></thead>
      <tbody>${biRows}</tbody>
    </table>` : '<div class="empty">无笔数据</div>'}
  </section>

  <section>
    <h2>中枢 (${result.zs_list.length})</h2>
    ${result.zs_list.length ? `<table>
      <thead><tr><th>起始</th><th>结束</th><th class="num">下沿</th><th class="num">上沿</th><th class="num">zd</th><th class="num">zg</th><th>有效性</th></tr></thead>
      <tbody>${zsRows}</tbody>
    </table>` : '<div class="empty">无中枢数据</div>'}
  </section>

  <section>
    <h2>分型 (${result.fx_list.length})</h2>
    ${result.fx_list.length ? `<table>
      <thead><tr><th>时间</th><th>类型</th><th class="num">高价</th><th class="num">低价</th></tr></thead>
      <tbody>${fxRows}</tbody>
    </table>` : '<div class="empty">无分型数据</div>'}
  </section>

  ${Object.keys(result.signals || {}).length ? `<section>
    <h2>信号 (${Object.keys(result.signals).length})</h2>
    <table>
      <thead><tr><th>信号名</th><th>值</th></tr></thead>
      <tbody>${signalRows}</tbody>
    </table>
  </section>` : ''}

  ${result.warnings && result.warnings.length ? `<section><h2>警告</h2><div class="down">⚠ ${result.warnings.map(esc).join('; ')}</div></section>` : ''}

  <div class="footer">
    由 tick-stock-panel 缠论分析模块生成 · 基于 czsc 库 · 报告完全自包含, 可离线打开
  </div>
</div>
</body>
</html>`
}

/** 生成下载文件名: 缠论分析_${symbol}_${freq}_${YYYYMMDD_HHmm}.html */
export function buildCzscHtmlFilename(symbol: string, freq: string, at: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const ts = `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}_${pad(at.getHours())}${pad(at.getMinutes())}`
  // 文件名安全化: 替换 . / 等特殊字符
  const safeSymbol = symbol.replace(/[.\\/:*?"<>|]/g, '_')
  const safeFreq = freq.replace(/[.\\/:*?"<>|]/g, '_')
  return `缠论分析_${safeSymbol}_${safeFreq}_${ts}.html`
}

/** 触发浏览器下载: Blob + createObjectURL + a.click, 与 Review.tsx 模式一致。 */
export function downloadCzscHtml(html: string, filename: string): void {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 释放对象 URL, 避免内存泄漏
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
