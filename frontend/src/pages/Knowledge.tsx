import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpen,
  Search,
  ChevronRight,
  ChevronDown,
  BarChart3,
  CandlestickChart,
  Swords,
  Shield,
  BookMarked,
  Tag,
  X,
  Globe,
  Library,
} from 'lucide-react'
import { api, type KnowledgeEntry, type KnowledgeCategory } from '@/lib/api'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { cn } from '@/lib/cn'

// ---- 分类元数据 ----
const CATEGORY_META: Record<
  KnowledgeCategory,
  { label: string; icon: typeof BookOpen; color: string; bg: string }
> = {
  basics:     { label: '金融常识', icon: BookOpen,         color: 'text-sky-500',     bg: 'bg-sky-50 dark:bg-sky-950/40' },
  indicators: { label: '技术指标', icon: BarChart3,         color: 'text-blue-500',    bg: 'bg-blue-50 dark:bg-blue-950/40' },
  patterns:   { label: 'K线形态', icon: CandlestickChart,  color: 'text-amber-500',   bg: 'bg-amber-50 dark:bg-amber-950/40' },
  strategies: { label: '常见战法', icon: Swords,            color: 'text-violet-500',  bg: 'bg-violet-50 dark:bg-violet-950/40' },
  risk:       { label: '风控原则', icon: Shield,            color: 'text-red-500',     bg: 'bg-red-50 dark:bg-red-950/40' },
  terms:      { label: '术语词典', icon: BookMarked,        color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-950/40' },
  macro:      { label: '宏观经济', icon: Globe,             color: 'text-teal-500',    bg: 'bg-teal-50 dark:bg-teal-950/40' },
  books:      { label: '书籍',     icon: Library,           color: 'text-purple-500',  bg: 'bg-purple-50 dark:bg-purple-950/40' },
}

const ALL_CATEGORIES: KnowledgeCategory[] = ['basics', 'indicators', 'patterns', 'strategies', 'risk', 'terms', 'macro', 'books']

// ---- 轻量 Markdown → HTML 渲染器 ----
function renderMarkdown(md: string): string {
  // 先提取 SVG 块，用占位符替换，避免被行级转义破坏
  const svgBlocks: string[] = []
  const protectedMd = md.replace(/<svg[\s\S]*?<\/svg>/g, (match) => {
    const idx = svgBlocks.length
    svgBlocks.push(match)
    return `<!--SVG_PLACEHOLDER_${idx}-->`
  })

  const lines = protectedMd.split('\n')
  const html: string[] = []
  let inTable = false
  let tableHeaderParsed = false
  let inList: 'ul' | 'ol' | null = null
  let inBlockquote = false
  let inCode = false
  let codeLang = ''

  const closeList = () => {
    if (inList) {
      html.push(`</${inList}>`)
      inList = null
    }
  }
  const closeBlockquote = () => {
    if (inBlockquote) {
      html.push('</blockquote>')
      inBlockquote = false
    }
  }
  const closeTable = () => {
    if (inTable) {
      html.push('</tbody></table>')
      inTable = false
      tableHeaderParsed = false
    }
  }

  const inline = (text: string): string => {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    // 代码块围栏 ``` 开启/关闭
    if (line.trim().startsWith('```')) {
      if (!inCode) {
        closeList()
        closeBlockquote()
        closeTable()
        inCode = true
        codeLang = line.trim().slice(3).trim()
        html.push(`<pre><code${codeLang ? ` class="language-${codeLang}"` : ''}>`)
        continue
      } else {
        html.push('</code></pre>')
        inCode = false
        codeLang = ''
        continue
      }
    }

    // 代码块内容 — 原样输出, 不做行内转义
    if (inCode) {
      html.push(line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '\n')
      continue
    }

    // 空行
    if (line.trim() === '') {
      closeList()
      closeBlockquote()
      continue
    }

    // SVG 占位符 → 直接还原输出
    const svgMatch = line.match(/^<!--SVG_PLACEHOLDER_(\d+)-->$/)
    if (svgMatch) {
      closeList()
      closeBlockquote()
      closeTable()
      html.push(svgBlocks[parseInt(svgMatch[1], 10)])
      continue
    }

    // 水平线 ---
    if (/^---+$/.test(line.trim()) && !line.includes('|')) {
      closeList()
      closeBlockquote()
      closeTable()
      html.push('<hr />')
      continue
    }

    // 表格检测: | 开头且下一个是分隔行
    if (line.trim().startsWith('|')) {
      if (inList) closeList()
      if (inBlockquote) closeBlockquote()

      if (!inTable) {
        html.push('<table>')
        // 表头
        const cells = line.split('|').slice(1, -1).map(c => c.trim())
        html.push('<thead><tr>' + cells.map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>')
        inTable = true
        tableHeaderParsed = false
        // 跳过分隔行
        if (i + 1 < lines.length && /^\s*\|[-:\s|]+\s*$/.test(lines[i + 1])) {
          i++
          tableHeaderParsed = true
        }
        continue
      }
      // 表体行
      if (tableHeaderParsed || inTable) {
        // 跳过分隔行
        if (/^\s*\|[-:\s|]+\s*$/.test(line)) continue
        const cells = line.split('|').slice(1, -1).map(c => c.trim())
        html.push('<tr>' + cells.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>')
        continue
      }
    } else {
      closeTable()
    }

    // 引用 (支持 > 和 > 连续行)
    if (line.startsWith('>')) {
      if (inList) closeList()
      if (!inBlockquote) {
        html.push('<blockquote>')
        inBlockquote = true
      }
      const content = line.replace(/^>\s?/, '')
      if (content.trim() === '') {
        html.push('<p>&nbsp;</p>')
      } else {
        html.push(`<p>${inline(content)}</p>`)
      }
      continue
    } else {
      closeBlockquote()
    }

    // 标题 H1~H4
    const headingMatch = line.match(/^(#{1,4})\s+(.+)$/)
    if (headingMatch) {
      closeList()
      const level = headingMatch[1].length
      const text = headingMatch[2].trim()
      // 为 H2/H3 生成 id 用于目录跳转
      const slug = text.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase()
      html.push(`<h${level}${slug ? ` id="${slug}"` : ''}>${inline(text)}</h${level}>`)
      continue
    }

    // 无序列表
    if (line.match(/^\s*[-*]\s+/)) {
      if (inList !== 'ul') {
        closeList()
        html.push('<ul>')
        inList = 'ul'
      }
      html.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ''))}</li>`)
      continue
    }

    // 有序列表
    if (line.match(/^\s*\d+\.\s+/)) {
      if (inList !== 'ol') {
        closeList()
        html.push('<ol>')
        inList = 'ol'
      }
      html.push(`<li>${inline(line.replace(/^\s*\d+\.\s+/, ''))}</li>`)
      continue
    }

    // 普通段落
    closeList()
    html.push(`<p>${inline(line)}</p>`)
  }

  closeList()
  closeBlockquote()
  closeTable()
  if (inCode) html.push('</code></pre>')

  return html.join('')
}

// ---- 主组件 ----
export function Knowledge() {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [activeCategory, setActiveCategory] = useState<KnowledgeCategory | null>(null)
  const [expandedCats, setExpandedCats] = useState<Set<KnowledgeCategory>>(new Set(ALL_CATEGORIES as any))
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(searchQuery), 300)
    return () => clearTimeout(t)
  }, [searchQuery])

  const { data, isLoading } = useQuery({
    queryKey: ['knowledge', 'list', debouncedQ, activeCategory],
    queryFn: () => api.listKnowledge({
      q: debouncedQ || undefined,
      category: activeCategory || undefined,
      limit: 1000,
    }),
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0

  // 按分类分组
  const groupedItems = useMemo(() => {
    const m: Record<string, KnowledgeEntry[]> = {}
    for (const it of items) {
      if (!m[it.category]) m[it.category] = []
      m[it.category].push(it)
    }
    return m
  }, [items])

  // 当前选中条目
  const selectedEntry = useMemo(
    () => items.find(it => it.id === selectedId) ?? null,
    [items, selectedId],
  )

  const toggleCategory = useCallback((cat: KnowledgeCategory) => {
    setExpandedCats(prev => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }, [])

  return (
    <div className="flex flex-col h-full">
      <PageHeader
        title="知识库"
        subtitle={
          <span>{total} 条 · 金融常识 · 技术指标 · 战法 · 书籍</span>
        }
        right={
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="搜索知识库..."
              className="w-56 pl-7 pr-3 py-1.5 text-xs rounded-md border border-border bg-surface focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        }
      />

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧目录树 */}
        <aside className="w-56 shrink-0 border-r border-border overflow-y-auto py-2 px-2">
          <div className="mb-2">
            <button
              onClick={() => {
                setActiveCategory(null)
                setSelectedId(null)
              }}
              className={cn(
                'flex items-center gap-1.5 w-full px-2 py-1.5 text-xs rounded-md transition-colors',
                !activeCategory ? 'bg-accent/10 text-accent' : 'hover:bg-elevated',
              )}
            >
              <BookOpen className="h-3.5 w-3.5" />
              全部
              <span className="ml-auto text-[10px] text-muted">{total}</span>
            </button>
          </div>

          {ALL_CATEGORIES.map(cat => {
            const meta = CATEGORY_META[cat]
            const Icon = meta.icon
            const catItems = groupedItems[cat] ?? []
            const isExpanded = expandedCats.has(cat)
            const isActive = activeCategory === cat

            return (
              <div key={cat} className="mb-1">
                <div className="flex items-center">
                  <button
                    onClick={() => toggleCategory(cat)}
                    className="p-0.5 text-muted hover:text-foreground shrink-0"
                  >
                    {isExpanded
                      ? <ChevronDown className="h-3 w-3" />
                      : <ChevronRight className="h-3 w-3" />}
                  </button>
                  <button
                    onClick={() => {
                      setActiveCategory(isActive ? null : cat)
                      setSelectedId(null)
                    }}
                    className={cn(
                      'flex items-center gap-1.5 flex-1 px-1.5 py-1.5 text-xs rounded-md transition-colors',
                      isActive ? 'bg-accent/10 text-accent' : 'hover:bg-elevated',
                    )}
                  >
                    <Icon className={cn('h-3.5 w-3.5', meta.color)} />
                    {meta.label}
                    <span className="ml-auto text-[10px] text-muted">{catItems.length}</span>
                  </button>
                </div>

                <AnimatePresence initial={false}>
                  {isExpanded && catItems.length > 0 && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden ml-4"
                    >
                      {catItems.map(item => (
                        <button
                          key={item.id}
                          onClick={() => setSelectedId(item.id)}
                          className={cn(
                            'flex items-center w-full pl-2 pr-1.5 py-1 text-[11px] rounded transition-colors text-left',
                            selectedId === item.id
                              ? 'bg-accent/10 text-accent'
                              : 'text-secondary hover:bg-elevated hover:text-foreground',
                          )}
                        >
                          <span className="truncate">{item.title}</span>
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )
          })}

          {/* 搜索结果提示 */}
          {debouncedQ && (
            <div className="mt-3 px-2 py-1.5 text-[10px] text-muted border-t border-border">
              搜索 "{debouncedQ}" · {total} 条结果
            </div>
          )}
        </aside>

        {/* 右侧内容区 */}
        <div className={cn('flex-1 overflow-hidden', selectedEntry ? '' : 'overflow-y-auto px-5 py-4')}>
          {isLoading ? (
            <div className="h-full grid place-items-center text-sm text-muted">加载中...</div>
          ) : selectedEntry ? (
            <KnowledgeDetail entry={selectedEntry} onClose={() => setSelectedId(null)} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={BookOpen}
              title="暂无知识内容"
              hint="请检查后端知识库是否已初始化"
            />
          ) : (
            <KnowledgeGrid
              items={items}
              groupedItems={groupedItems}
              onSelect={setSelectedId}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ---- 知识详情 ----
function KnowledgeDetail({ entry, onClose }: { entry: KnowledgeEntry; onClose: () => void }) {
  const meta = CATEGORY_META[entry.category]
  const Icon = meta.icon
  const contentRef = useRef<HTMLDivElement>(null)
  const [tocItems, setTocItems] = useState<{ id: string; text: string; level: number }[]>([])

  const isLongContent = entry.content.length > 5000

  // 渲染后提取 H2/H3 目录
  useEffect(() => {
    if (!isLongContent || !contentRef.current) {
      setTocItems([])
      return
    }
    const headings = contentRef.current.querySelectorAll('h2, h3')
    const items: { id: string; text: string; level: number }[] = []
    headings.forEach(h => {
      const id = h.getAttribute('id')
      if (id) {
        items.push({ id, text: h.textContent || '', level: h.tagName === 'H2' ? 2 : 3 })
      }
    })
    setTocItems(items)
  }, [entry.id, entry.content, isLongContent])

  const scrollToHeading = useCallback((id: string) => {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [])

  return (
    <div className="flex h-full">
      {/* 目录侧栏 (长文章) */}
      {isLongContent && tocItems.length > 3 && (
        <aside className="w-48 shrink-0 border-r border-border overflow-y-auto py-3 px-2 sticky top-0 h-full">
          <div className="text-[10px] font-medium text-muted uppercase tracking-wider px-2 mb-1.5">目录</div>
          <nav className="space-y-0.5">
            {tocItems.map(item => (
              <button
                key={item.id}
                onClick={() => scrollToHeading(item.id)}
                className={cn(
                  'block w-full text-left text-[11px] rounded transition-colors hover:bg-elevated hover:text-foreground truncate',
                  item.level === 2 ? 'px-2 py-1 text-secondary font-medium' : 'pl-4 pr-2 py-0.5 text-muted',
                )}
                title={item.text}
              >
                {item.text}
              </button>
            ))}
          </nav>
        </aside>
      )}

      {/* 正文区域 */}
      <div className="flex-1 overflow-y-auto">
        <div className={cn('mx-auto px-5 py-4', isLongContent ? 'max-w-3xl' : 'max-w-4xl')}>
          {/* 面包屑 + 关闭 */}
          <div className="flex items-center justify-between mb-3 sticky top-0 bg-surface/80 backdrop-blur-sm py-1 z-10">
            <div className="flex items-center gap-1.5 text-xs text-muted min-w-0">
              <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] shrink-0', meta.bg, meta.color)}>
                <Icon className="h-3 w-3" />
                {meta.label}
              </span>
              <ChevronRight className="h-3 w-3 shrink-0" />
              <span className="text-foreground font-medium truncate">{entry.title}</span>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded-md text-muted hover:bg-elevated hover:text-foreground transition-colors shrink-0 ml-2"
              title="返回列表"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* 标题 */}
          <h1 className="text-xl font-semibold text-foreground mb-2">{entry.title}</h1>

          {/* 摘要 */}
          <p className="text-sm text-secondary mb-3 leading-relaxed">{entry.summary}</p>

          {/* 标签 */}
          {entry.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-4">
              {entry.tags.map(tag => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-elevated text-muted"
                >
                  <Tag className="h-2.5 w-2.5" />
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* 正文 */}
          <div
            ref={contentRef}
            className="knowledge-content text-sm text-foreground"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(entry.content) }}
          />

          {/* 底部留白 */}
          <div className="h-8" />
        </div>
      </div>
    </div>
  )
}

// ---- 知识列表(网格) ----
function KnowledgeGrid({
  items,
  groupedItems,
  onSelect,
}: {
  items: KnowledgeEntry[]
  groupedItems: Record<string, KnowledgeEntry[]>
  onSelect: (id: string) => void
}) {
  // 有搜索时按相关性平铺; 否则按分类分组展示
  const hasSearch = items.length > 0 && items.length < 80

  if (hasSearch) {
    return (
      <div className="max-w-4xl mx-auto space-y-2">
        {items.map(item => (
          <KnowledgeCard key={item.id} item={item} onClick={() => onSelect(item.id)} />
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {ALL_CATEGORIES.map(cat => {
        const catItems = groupedItems[cat]
        if (!catItems || catItems.length === 0) return null
        const meta = CATEGORY_META[cat]
        const Icon = meta.icon

        return (
          <div key={cat}>
            <div className="flex items-center gap-2 mb-2 pb-1 border-b border-border">
              <Icon className={cn('h-4 w-4', meta.color)} />
              <h2 className="text-sm font-semibold text-foreground">{meta.label}</h2>
              <span className="text-[10px] text-muted">{catItems.length} 条</span>
            </div>
            <div className="space-y-2">
              {catItems.map(item => (
                <KnowledgeCard key={item.id} item={item} onClick={() => onSelect(item.id)} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---- 知识卡片 ----
function KnowledgeCard({ item, onClick }: { item: KnowledgeEntry; onClick: () => void }) {
  const meta = CATEGORY_META[item.category]
  const Icon = meta.icon

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border bg-surface px-4 py-3 hover:shadow-sm hover:border-accent/30 transition-all group"
    >
      <div className="flex items-start gap-3">
        <div className={cn('shrink-0 w-7 h-7 rounded-md grid place-items-center', meta.bg)}>
          <Icon className={cn('h-3.5 w-3.5', meta.color)} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-foreground group-hover:text-accent transition-colors truncate">
              {item.title}
            </h3>
            <span className={cn('shrink-0 px-1.5 py-0.5 rounded text-[10px]', meta.bg, meta.color)}>
              {meta.label}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted line-clamp-2 leading-relaxed">{item.summary}</p>
          {item.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {item.tags.slice(0, 4).map(tag => (
                <span
                  key={tag}
                  className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-elevated text-muted"
                >
                  #{tag}
                </span>
              ))}
            </div>
          )}
        </div>
        <ChevronRight className="h-4 w-4 text-muted shrink-0 mt-1 group-hover:text-accent transition-colors" />
      </div>
    </button>
  )
}
