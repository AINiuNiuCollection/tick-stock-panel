import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Notebook,
  Plus,
  Search,
  Pin,
  PinOff,
  Trash2,
  CheckSquare,
  Square,
  StickyNote,
  Bug,
  SlidersHorizontal,
  Lightbulb,
  Sparkles,
  X,
  Tag as TagIcon,
  Download,
  Pencil,
  Bold,
  Highlighter,
  List,
  ListOrdered,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignJustify,
  Check,
  ChevronDown,
  Search as SearchIcon,
  Flag,
  HelpCircle,
  Star,
  Link2,
  Eye,
  Clock,
  RefreshCw,
  CandlestickChart,
  Image as ImageIcon,
} from 'lucide-react'
import { api, type MemoEntry, type MemoType } from '@/lib/api'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'
import { KChartDialog, type KChartData } from '@/components/memo/KChartDialog'
import { parseKChartFromSvg } from '@/components/memo/kchart-svg'

// ---- 类型元数据 ----
const TYPE_META: Record<MemoType, { label: string; icon: typeof Bug; color: string; bg: string }> = {
  note:    { label: '速记', icon: StickyNote,       color: 'text-slate-500',   bg: 'bg-slate-100 dark:bg-slate-800' },
  bug:     { label: 'Bug',  icon: Bug,              color: 'text-red-500',     bg: 'bg-red-50 dark:bg-red-950/40' },
  param:   { label: '参数', icon: SlidersHorizontal, color: 'text-blue-500',    bg: 'bg-blue-50 dark:bg-blue-950/40' },
  idea:    { label: '想法', icon: Lightbulb,        color: 'text-amber-500',   bg: 'bg-amber-50 dark:bg-amber-950/40' },
  todo:    { label: '待办', icon: CheckSquare,      color: 'text-violet-500',  bg: 'bg-violet-50 dark:bg-violet-950/40' },
  insight: { label: '洞察', icon: Sparkles,         color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-950/40' },
}

const ALL_TYPES: MemoType[] = ['note', 'bug', 'param', 'idea', 'todo', 'insight']

const HIGHLIGHT_COLORS = [
  { name: '黄', value: '#fef08a' },
  { name: '绿', value: '#bbf7d0' },
  { name: '蓝', value: '#bfdbfe' },
  { name: '粉', value: '#fbcfe8' },
  { name: '橙', value: '#fed7aa' },
  { name: '紫', value: '#e9d5ff' },
  { name: '无', value: 'transparent' },
]

// OneNote 风格标记
const MARKERS = [
  { id: 'todo',       label: '待办',   icon: CheckSquare,  html: '<span style="color:#7c3aed;font-weight:600">☐ </span>' },
  { id: 'important',  label: '重要',   icon: Star,         html: '<span style="color:#f59e0b;font-weight:600">★ </span>' },
  { id: 'question',   label: '问题',   icon: HelpCircle,   html: '<span style="color:#3b82f6;font-weight:600">? </span>' },
  { id: 'priority',   label: '优先',   icon: Flag,         html: '<span style="color:#ef4444;font-weight:600">⚑ </span>' },
  { id: 'done',       label: '完成',   icon: Check,        html: '<span style="color:#10b981;font-weight:600">✓ </span>' },
  { id: 'idea',       label: '想法',   icon: Lightbulb,    html: '<span style="color:#f59e0b;font-weight:600">💡 </span>' },
]

// ---- 主组件 ----
export function Memo() {
  const qc = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTag, setActiveTag] = useState<string | null>(null)
  const [activeType, setActiveType] = useState<MemoType | null>(null)
  const [editing, setEditing] = useState<MemoEntry | null>(null)
  const [showEditor, setShowEditor] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)

  const [debouncedQ, setDebouncedQ] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(searchQuery), 300)
    return () => clearTimeout(t)
  }, [searchQuery])

  const { data, isLoading } = useQuery({
    queryKey: ['memo', 'list', debouncedQ, activeTag, activeType],
    queryFn: () => api.listMemos({
      q: debouncedQ || undefined,
      tag: activeTag || undefined,
      type: activeType || undefined,
      limit: 500,
    }),
  })

  const { data: tagsData } = useQuery({
    queryKey: ['memo', 'tags'],
    queryFn: () => api.getMemoTags(),
  })

  // 关注列表 (用于卡片中显示股票名称)
  const { data: watchlistData } = useQuery({
    queryKey: ['watchlist', 'list'],
    queryFn: () => api.watchlistList(),
  })
  const symbolNameMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const s of watchlistData?.symbols ?? []) {
      m[s.symbol] = s.name || s.symbol
    }
    return m
  }, [watchlistData])

  const items = data?.items ?? []
  const total = data?.total ?? 0

  const todoPending = useMemo(
    () => items.filter(it => it.type === 'todo' && !it.content.startsWith('~~')).length,
    [items],
  )

  const createMut = useMutation({
    mutationFn: (body: Parameters<typeof api.createMemo>[0]) => api.createMemo(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memo'] })
      toast('已保存', 'success')
    },
    onError: () => toast('保存失败'),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      api.updateMemo(id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memo'] })
      toast('已更新', 'success')
    },
    onError: () => toast('更新失败'),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteMemo(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memo'] })
      toast('已删除', 'success')
    },
    onError: () => toast('删除失败'),
  })

  const pinMut = useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      api.toggleMemoPin(id, pinned),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memo'] }),
    onError: () => toast('操作失败'),
  })

  const batchDeleteMut = useMutation({
    mutationFn: (ids: string[]) => api.batchDeleteMemos(ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memo'] })
      setSelectedIds(new Set())
      toast('批量删除完成', 'success')
    },
    onError: () => toast('批量删除失败'),
  })

  const openNew = useCallback(() => {
    setEditing(null)
    setShowEditor(true)
  }, [])

  const openEdit = useCallback((item: MemoEntry) => {
    setEditing(item)
    setShowEditor(true)
  }, [])

  const closeEditor = useCallback(() => {
    setShowEditor(false)
    setEditing(null)
  }, [])

  const [viewedMemo, setViewedMemo] = useState<MemoEntry | null>(null)
  const { handleContainerClick: handleDetailImgClick, lightbox: detailImgLightbox } = useImageLightbox()
  const [detailLightboxSrc, setDetailLightboxSrc] = useState<{ src: string; alt: string } | null>(null)

  const showMemoContent = useCallback((item: MemoEntry) => {
    setViewedMemo(item)
  }, [])

  const hideMemoContent = useCallback(() => {
    setViewedMemo(null)
  }, [])

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleTodoDone = useCallback((item: MemoEntry) => {
    const isDone = item.content.startsWith('~~')
    const newContent = isDone
      ? item.content.replace(/^~~([\s\S]*)~~$/, '$1')
      : `~~${item.content}~~`
    updateMut.mutate({ id: item.id, patch: { content: newContent } })
  }, [updateMut])

  const exportMarkdown = useCallback(async () => {
    const now = new Date()
    try {
      const res = await api.exportMemos(now.getFullYear(), now.getMonth() + 1)
      await navigator.clipboard.writeText(res.content)
      toast('已导出到剪贴板，可粘贴到 docs/memo/', 'success')
    } catch {
      toast('导出失败')
    }
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'm') {
        e.preventDefault()
        openNew()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [openNew])

  return (
    <div className="flex flex-col h-full">
      <PageHeader
        title="备忘录"
        subtitle={
          <span className="flex items-center gap-2">
            <span>{total} 条</span>
            {todoPending > 0 && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300">
                {todoPending} 待办
              </span>
            )}
          </span>
        }
        right={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <input
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="搜索备忘..."
                className="w-44 pl-7 pr-3 py-1.5 text-xs rounded-md border border-border bg-surface focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <button
              onClick={exportMarkdown}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-md border border-border hover:bg-elevated transition-colors"
              title="导出本月 Markdown 到剪贴板"
            >
              <Download className="h-3.5 w-3.5" />
              导出
            </button>
            {selectedIds.size > 0 && (
              <button
                onClick={() => setConfirmBatchDelete(true)}
                className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除选中 ({selectedIds.size})
              </button>
            )}
            <button
              onClick={openNew}
              className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-md bg-accent text-white hover:opacity-90 transition-opacity"
            >
              <Plus className="h-3.5 w-3.5" />
              新建
              <kbd className="ml-1 px-1 py-0.5 rounded text-[10px] bg-white/20">Ctrl+M</kbd>
            </button>
          </div>
        }
      />

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧标签栏 */}
        <aside className="w-44 shrink-0 border-r border-border overflow-y-auto py-2 px-2">
          <div className="mb-3">
            <div className="text-[10px] font-medium text-muted uppercase tracking-wider px-2 mb-1">类型</div>
            <button
              onClick={() => setActiveType(null)}
              className={cn(
                'flex items-center gap-1.5 w-full px-2 py-1.5 text-xs rounded-md transition-colors',
                !activeType ? 'bg-accent/10 text-accent' : 'hover:bg-elevated',
              )}
            >
              <Notebook className="h-3.5 w-3.5" />
              全部
            </button>
            {ALL_TYPES.map(t => {
              const meta = TYPE_META[t]
              const Icon = meta.icon
              return (
                <button
                  key={t}
                  onClick={() => setActiveType(activeType === t ? null : t)}
                  className={cn(
                    'flex items-center gap-1.5 w-full px-2 py-1.5 text-xs rounded-md transition-colors',
                    activeType === t ? 'bg-accent/10 text-accent' : 'hover:bg-elevated',
                  )}
                >
                  <Icon className={cn('h-3.5 w-3.5', meta.color)} />
                  {meta.label}
                </button>
              )
            })}
          </div>

          <div>
            <div className="text-[10px] font-medium text-muted uppercase tracking-wider px-2 mb-1">标签</div>
            <button
              onClick={() => setActiveTag(null)}
              className={cn(
                'flex items-center gap-1 w-full px-2 py-1.5 text-xs rounded-md transition-colors',
                !activeTag ? 'bg-accent/10 text-accent' : 'hover:bg-elevated',
              )}
            >
              <TagIcon className="h-3 w-3" />
              全部标签
            </button>
            {(tagsData ?? []).map(({ tag, count }) => (
              <button
                key={tag}
                onClick={() => setActiveTag(activeTag === tag ? null : tag)}
                className={cn(
                  'flex items-center justify-between gap-1 w-full px-2 py-1.5 text-xs rounded-md transition-colors',
                  activeTag === tag ? 'bg-accent/10 text-accent' : 'hover:bg-elevated',
                )}
              >
                <span className="truncate">
                  <span className="text-muted">#</span>{tag}
                </span>
                <span className="text-[10px] text-muted shrink-0">{count}</span>
              </button>
            ))}
            {(tagsData ?? []).length === 0 && (
              <div className="px-2 py-1 text-[11px] text-muted">暂无标签</div>
            )}
          </div>
        </aside>

        {/* 右侧列表 */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {isLoading ? (
            <div className="h-full grid place-items-center text-sm text-muted">加载中...</div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={Notebook}
              title="暂无备忘录"
              hint="点击右上角「新建」或按 Ctrl+M 快速记录"
            />
          ) : (
            <div className="space-y-2 max-w-4xl mx-auto">
              <AnimatePresence initial={false}>
                {items.map(item => (
                  <MemoCard
                    key={item.id}
                    item={item}
                    selected={selectedIds.has(item.id)}
                    symbolNameMap={symbolNameMap}
                    onToggleSelect={() => toggleSelect(item.id)}
                    onEdit={() => openEdit(item)}
                    onDelete={() => deleteMut.mutate(item.id)}
                    onTogglePin={() => pinMut.mutate({ id: item.id, pinned: !item.pinned })}
                    onToggleTodo={() => toggleTodoDone(item)}
                    onView={() => showMemoContent(item)}
                  />
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>

      {/* 查看备忘录模态框 */}
      {viewedMemo && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[105] bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div
            className="bg-surface rounded-2xl border border-border max-w-2xl w-full max-h-[90vh] overflow-hidden shadow-2xl flex flex-col"
            role="dialog"
            aria-modal="true"
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
              <h3 className="text-xl font-semibold text-foreground truncate">
                {viewedMemo.title || '备忘录内容'}
              </h3>
              <button
                onClick={hideMemoContent}
                className="p-1.5 rounded-lg text-muted hover:bg-elevated hover:text-foreground transition-colors shrink-0 ml-4"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="overflow-y-auto px-6 py-4 flex-1">

            <div
              className="text-sm text-foreground leading-relaxed memo-content-preview"
              style={{ overflow: 'visible', display: 'block', WebkitLineClamp: 'unset', WebkitBoxOrient: 'unset' }}
              dangerouslySetInnerHTML={{ __html: stripDangerousHtml(viewedMemo.content) }}
              onClick={handleDetailImgClick}
            />

            {/* 详情页图片附件缩略图栏 */}
            {extractImagesFromContent(viewedMemo.content).length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-border">
                {extractImagesFromContent(viewedMemo.content).map((img, i) => (
                  <div
                    key={i}
                    className="cursor-pointer"
                    onClick={() => setDetailLightboxSrc({ src: img.src, alt: img.alt })}
                  >
                    <img
                      src={img.src}
                      alt={img.alt}
                      className="w-20 h-20 object-cover rounded-lg border border-border"
                    />
                  </div>
                ))}
              </div>
            )}

            <div className="mt-4 flex items-center justify-between">
              <div className="flex items-center gap-3 text-[10px] text-muted">
                <span>创建于 {(viewedMemo.created_at || '').slice(0, 16).replace('T', ' ')}</span>
                {viewedMemo.updated_at && viewedMemo.updated_at !== viewedMemo.created_at && (
                  <span>更新于 {(viewedMemo.updated_at || '').slice(0, 16).replace('T', ' ')}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {viewedMemo.tags.map(tag => (
                  <span
                    key={tag}
                    className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-elevated text-muted"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
            </div>
          </div>
        </motion.div>
      )}

      {/* 全屏编辑器 */}
      <AnimatePresence>
        {showEditor && (
          <MemoEditor
            key="editor"
            editing={editing}
            onClose={closeEditor}
            onSave={(body) => {
              if (editing) {
                updateMut.mutate({ id: editing.id, patch: body })
              } else {
                createMut.mutate(body)
              }
              closeEditor()
            }}
          />
        )}
      </AnimatePresence>

      {/* 详情页图片放大弹窗 */}
      {detailImgLightbox}
      {detailLightboxSrc && (
        <ImageLightbox
          src={detailLightboxSrc.src}
          alt={detailLightboxSrc.alt}
          onClose={() => setDetailLightboxSrc(null)}
        />
      )}

      {/* 批量删除确认对话框 */}
      <AnimatePresence>
        {confirmBatchDelete && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[110] bg-black/40"
              onClick={() => setConfirmBatchDelete(false)}
            />
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed left-1/2 top-1/2 z-[111] -translate-x-1/2 -translate-y-1/2 w-80 rounded-xl border border-border bg-surface shadow-2xl p-5"
            >
              <div className="flex items-center gap-2 mb-2">
                <div className="p-1.5 rounded-lg bg-red-500/10 text-red-500">
                  <Trash2 className="h-4 w-4" />
                </div>
                <span className="text-sm font-semibold text-foreground">确认批量删除？</span>
              </div>
              <p className="text-xs text-muted mb-4">
                将删除选中的 {selectedIds.size} 条备忘录，此操作不可撤销。
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={() => setConfirmBatchDelete(false)}
                  className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-elevated transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={() => {
                    batchDeleteMut.mutate([...selectedIds])
                    setConfirmBatchDelete(false)
                  }}
                  className="px-4 py-1.5 text-xs rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors font-medium"
                >
                  删除
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

// ---- 单条卡片 ----
interface CardProps {
  item: MemoEntry
  selected: boolean
  symbolNameMap: Record<string, string>
  onToggleSelect: () => void
  onEdit: () => void
  onDelete: () => void
  onTogglePin: () => void
  onToggleTodo: () => void
  onView: () => void
}

function MemoCard({ item, selected, symbolNameMap, onToggleSelect, onEdit, onDelete, onTogglePin, onToggleTodo, onView }: CardProps) {
  const meta = TYPE_META[item.type] ?? TYPE_META.note
  const Icon = meta.icon
  const isTodo = item.type === 'todo'
  const isDone = isTodo && item.content.startsWith('~~')
  const timeStr = (item.created_at || '').slice(5, 16).replace('T', ' ')
  const updatedStr = (item.updated_at || '').slice(5, 16).replace('T', ' ')
  const hasUpdate = item.updated_at && item.updated_at !== item.created_at
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.15 }}
      className={cn(
        'group relative rounded-lg border border-border bg-surface px-3 py-2.5 hover:shadow-sm transition-shadow',
        selected && 'ring-1 ring-accent',
      )}
    >
      <div className={cn('absolute left-0 top-2 bottom-2 w-1 rounded-full', meta.bg)} />

      <div className="flex items-start gap-2 pl-1.5">
        <button
          onClick={onToggleSelect}
          className="mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
        >
          {selected
            ? <CheckSquare className="h-3.5 w-3.5 text-accent" />
            : <Square className="h-3.5 w-3.5 text-muted" />}
        </button>

        <div className={cn('mt-0.5 shrink-0', meta.color)}>
          <Icon className="h-4 w-4" />
        </div>

        <div className="flex-1 min-w-0">
          {/* 标签行 + 查看按钮 */}
          <div className="flex items-center justify-between gap-1.5 flex-wrap mb-0.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              {item.pinned && (
                <Pin className="h-3 w-3 text-amber-500 fill-amber-500 shrink-0" />
              )}
              {item.title && (
                <span className="text-sm font-semibold text-foreground truncate max-w-[300px]">
                  {item.title}
                </span>
              )}
              {item.tags.map(tag => (
                <span
                  key={tag}
                  className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-elevated text-muted"
                >
                  #{tag}
                </span>
              ))}
              {item.related_symbol?.map(sym => (
                <span key={sym} className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400">
                  {sym}{symbolNameMap[sym] ? ` ${symbolNameMap[sym]}` : ''}
                </span>
              ))}
              {item.related_strategy?.map(strat => (
                <span key={strat} className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400">
                  {strat}
                </span>
              ))}
            </div>
            <button
              onClick={onView}
              className="p-1.5 rounded hover:bg-elevated text-muted hover:text-accent transition-colors shrink-0"
              title="查看备忘录"
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
          </div>
          {/* 正文 HTML */}
          <div
            className={cn(
              'text-sm text-foreground leading-relaxed memo-content-preview',
              isDone && 'line-through opacity-50',
            )}
            dangerouslySetInnerHTML={{ __html: stripDangerousHtml(item.content) }}
          />
          <div className="flex items-center gap-2 mt-1">
            <span className="inline-flex items-center gap-0.5 text-[10px] text-muted">
              <Clock className="h-2.5 w-2.5" />
              {timeStr}
            </span>
            {hasUpdate && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-muted/70">
                <RefreshCw className="h-2.5 w-2.5" />
                {updatedStr}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-0.5 transition-opacity shrink-0">
          {isTodo && (
            <button
              onClick={onToggleTodo}
              className="p-1 rounded hover:bg-elevated text-muted hover:text-violet-500"
              title={isDone ? '标记未完成' : '标记完成'}
            >
              <CheckSquare className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            onClick={onTogglePin}
            className="p-1 rounded hover:bg-elevated text-muted hover:text-amber-500"
            title={item.pinned ? '取消置顶' : '置顶'}
          >
            {item.pinned
              ? <PinOff className="h-3.5 w-3.5" />
              : <Pin className="h-3.5 w-3.5" />}
          </button>
          <button
            onClick={onEdit}
            className="p-1 rounded hover:bg-elevated text-muted hover:text-accent"
            title="编辑"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setConfirmDelete(true)}
            className="p-1 rounded hover:bg-elevated text-muted hover:text-red-500"
            title="删除"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* 删除确认对话框 */}
      <AnimatePresence>
        {confirmDelete && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[110] bg-black/40"
              onClick={() => setConfirmDelete(false)}
            />
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed left-1/2 top-1/2 z-[111] -translate-x-1/2 -translate-y-1/2 w-80 rounded-xl border border-border bg-surface shadow-2xl p-5"
            >
              <div className="flex items-center gap-2 mb-2">
                <div className="p-1.5 rounded-lg bg-red-500/10 text-red-500">
                  <Trash2 className="h-4 w-4" />
                </div>
                <span className="text-sm font-semibold text-foreground">确认删除？</span>
              </div>
              <p className="text-xs text-muted mb-4">
                {item.title
                  ? `将删除「${item.title}」，此操作不可撤销。`
                  : '将删除此备忘录，此操作不可撤销。'}
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-elevated transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={() => {
                    setConfirmDelete(false)
                    onDelete()
                  }}
                  className="px-4 py-1.5 text-xs rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors font-medium"
                >
                  删除
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ---- HTML 安全处理 ----
function stripDangerousHtml(html: string): string {
  // 移除 script/iframe/on* 事件, 保留基础格式标签
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/\son\w+="[^"]*"/gi, '')
    .replace(/\son\w+='[^']*'/gi, '')
    .replace(/javascript:/gi, '')
}

// ---- 图片放大查看 (Lightbox) ----

/** 图片放大弹窗 */
function ImageLightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <>
      <div
        className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-center justify-center p-8"
        onClick={onClose}
      >
        <img
          src={src}
          alt={alt}
          className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        />
      </div>
      <button
        onClick={onClose}
        className="fixed top-4 right-4 z-[201] p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
        title="关闭 (Esc)"
      >
        <X className="h-5 w-5" />
      </button>
    </>
  )
}

/** 图片点击委托: 监听容器内 img[data-memo-img] 的点击, 弹出放大弹窗 */
function useImageLightbox() {
  const [lightboxImg, setLightboxImg] = useState<{ src: string; alt: string } | null>(null)

  const handleContainerClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement
    if (target.tagName === 'IMG' && target.getAttribute('data-memo-img')) {
      e.preventDefault()
      e.stopPropagation()
      setLightboxImg({
        src: (target as HTMLImageElement).src,
        alt: target.getAttribute('alt') || '',
      })
    }
  }, [])

  const lightbox = lightboxImg ? (
    <ImageLightbox
      src={lightboxImg.src}
      alt={lightboxImg.alt}
      onClose={() => setLightboxImg(null)}
    />
  ) : null

  return { handleContainerClick, lightbox }
}

/** 从 content HTML 中提取 data-memo-images 容器内的图片 */
function extractImagesFromContent(html: string): { src: string; alt: string }[] {
  try {
    const parser = new DOMParser()
    const doc = parser.parseFromString(html, 'text/html')
    const container = doc.querySelector('div[data-memo-images]')
    if (!container) return []
    return Array.from(container.querySelectorAll('img[data-memo-img]')).map(img => ({
      src: img.getAttribute('src') || '',
      alt: img.getAttribute('alt') || '',
    })).filter(img => img.src)
  } catch {
    return []
  }
}

// ---- 全屏沉浸式富文本编辑器 ----
interface EditorProps {
  editing: MemoEntry | null
  onClose: () => void
  onSave: (body: {
    title: string
    content: string
    tags: string[]
    type: MemoType
    pinned: boolean
    related_symbol?: string[]
    related_strategy?: string[]
  }) => void
}

function MemoEditor({ editing, onClose, onSave }: EditorProps) {
  const [title, setTitle] = useState(editing?.title ?? '')
  const initialContent = editing?.content ?? ''
  const [type, setType] = useState<MemoType>(editing?.type ?? 'note')
  const [tags, setTags] = useState<string[]>(editing?.tags ?? [])
  const [relatedSymbol, setRelatedSymbol] = useState<string[]>(editing?.related_symbol ?? [])
  const [relatedStrategy, setRelatedStrategy] = useState<string[]>(editing?.related_strategy ?? [])
  const [showTags, setShowTags] = useState(false)
  const [showLink, setShowLink] = useState(false)
  const [showRuled, setShowRuled] = useState(true)
  const [showHighlightPicker, setShowHighlightPicker] = useState(false)
  const [showMarkers, setShowMarkers] = useState(false)
  const [fmtState, setFmtState] = useState<{ bold: boolean; highlight: boolean }>({ bold: false, highlight: false })
  const [showKChart, setShowKChart] = useState(false)
  const [editingKChart, setEditingKChart] = useState<{ data: KChartData; element: HTMLElement } | null>(null)
  const [imgVersion, setImgVersion] = useState(0)
  const [lightboxSrc, setLightboxSrc] = useState<{ src: string; alt: string } | null>(null)

  const editorRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLInputElement>(null)
  const contentRef = useRef<string>('')
  const initRef = useRef(false)
  const imageInputRef = useRef<HTMLInputElement>(null)

  // 关注列表 & 策略列表
  const { data: watchlistData } = useQuery({
    queryKey: ['watchlist', 'list'],
    queryFn: () => api.watchlistList(),
    enabled: showLink,
  })
  const { data: strategyData } = useQuery({
    queryKey: ['strategies', 'list', 'all'],
    queryFn: () => api.strategyList(undefined, 'all', true),
    enabled: showLink,
  })

  // 初始化：设置 innerHTML（只执行一次，不在 render 中控制 contentEditable 内容）
  // 用 initRef 防止 StrictMode 双调用导致重复初始化
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    const el = editorRef.current
    if (el) {
      if (initialContent) {
        el.innerHTML = initialContent
      }
      contentRef.current = initialContent
    }
    // 延迟聚焦标题，避免动画期间焦点丢失
    const t = setTimeout(() => titleRef.current?.focus(), 100)
    return () => clearTimeout(t)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Esc 关闭, Ctrl+Enter 保存
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        handleSave()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, type, tags, relatedSymbol, relatedStrategy])

  // 追踪选区格式状态 (加粗/底色等高亮)
  useEffect(() => {
    const updateFmt = () => {
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0) return
      const range = sel.getRangeAt(0)
      if (!editorRef.current?.contains(range.commonAncestorContainer)) {
        // 选区不在编辑器内, 清除高亮
        setFmtState({ bold: false, highlight: false })
        return
      }
      try {
        // 检测当前选区是否有底色:
        // queryCommandValue('backColor') 在 Chrome 会返回编辑器容器的 computed background-color,
        // 而非 execCommand 设置的 inline style, 导致加粗后误判为有底色。
        // 正确做法: 遍历选区祖先链, 只检查 inline style 中的 background-color。
        let hasHighlight = false
        let node: Node | null = sel.anchorNode
        while (node && node !== editorRef.current) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            const el = node as HTMLElement
            const bg = el.style.backgroundColor
            if (bg && bg !== 'transparent' && bg !== 'rgba(0, 0, 0, 0)') {
              hasHighlight = true
              break
            }
          }
          node = node.parentNode
        }
        setFmtState({
          bold: document.queryCommandState('bold'),
          highlight: hasHighlight,
        })
      } catch {
        // queryCommandState 可能在某些浏览器抛异常
      }
    }
    document.addEventListener('selectionchange', updateFmt)
    return () => document.removeEventListener('selectionchange', updateFmt)
  }, [])

  const extractTags = useCallback((text: string): string[] => {
    const matches = text.match(/#([\u4e00-\u9fa5a-zA-Z0-9_]+)/g) || []
    return [...new Set(matches.map(m => m.slice(1)))]
  }, [])

  const handleSave = () => {
    const el = editorRef.current
    const htmlContent = el?.innerHTML?.trim() || ''
    const textContent = el?.textContent?.trim() || ''
    if (!textContent) {
      toast('内容不能为空')
      return
    }
    const inlineTags = extractTags(textContent)
    const allTags = [...new Set([...tags, ...inlineTags])]

    onSave({
      title: title.trim(),
      content: htmlContent,
      tags: allTags,
      type,
      pinned: editing?.pinned ?? false,
      related_symbol: relatedSymbol,
      related_strategy: relatedStrategy,
    })
  }

  // ---- 富文本工具命令 ----
  const execCmd = useCallback((cmd: string, value?: string) => {
    // 确保编辑区有焦点
    editorRef.current?.focus()
    document.execCommand(cmd, false, value)
    // 同步 ref
    if (editorRef.current) {
      contentRef.current = editorRef.current.innerHTML
    }
    // execCommand 后 selectionchange 可能不触发 (选区没动, 只有 DOM 变了)
    // 手动派发事件让 updateFmt 重新检测格式状态
    document.dispatchEvent(new Event('selectionchange'))
  }, [])

  const handleBold = () => execCmd('bold')
  const handleBulletList = () => execCmd('insertUnorderedList')
  const handleNumberedList = () => execCmd('insertOrderedList')
  const handleAlignLeft = () => execCmd('justifyLeft')
  const handleAlignCenter = () => execCmd('justifyCenter')
  const handleAlignRight = () => execCmd('justifyRight')
  const handleAlignJustify = () => execCmd('justifyFull')

  const handleHighlight = (color: string) => {
    if (color === 'transparent') {
      // 不使用 execCommand 移除底色:
      // Chrome 中 execCommand('backColor', 'transparent') 会在外层包一个 transparent span,
      // 内层带色的 span 不受影响, 背景色仍然可见。
      // 改为直接遍历 DOM 清除 inline background-color。
      editorRef.current?.focus()
      const sel = window.getSelection()
      if (!sel || !editorRef.current) {
        setShowHighlightPicker(false)
        return
      }

      if (sel.isCollapsed) {
        // 光标折叠态: 从锚点向上遍历祖先, 清除第一个带 inline bg 的元素
        let node: Node | null = sel.anchorNode
        while (node && node !== editorRef.current) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            const el = node as HTMLElement
            if (el.style.backgroundColor) {
              el.style.backgroundColor = ''
              break
            }
          }
          node = node.parentNode
        }
      } else if (sel.rangeCount > 0) {
        // 选区展开态: 清除选区内所有元素的 inline background-color
        const range = sel.getRangeAt(0)
        if (editorRef.current.contains(range.commonAncestorContainer)) {
          const root = (range.commonAncestorContainer.nodeType === Node.TEXT_NODE
            ? range.commonAncestorContainer.parentElement
            : range.commonAncestorContainer) as HTMLElement
          // 检查 root 自身
          if (root && root !== editorRef.current && root.style.backgroundColor) {
            root.style.backgroundColor = ''
          }
          // 检查所有后代元素
          if (root) {
            const elements = root.querySelectorAll('*')
            elements.forEach((el) => {
              const htmlEl = el as HTMLElement
              if (htmlEl.style.backgroundColor && range.intersectsNode(htmlEl)) {
                htmlEl.style.backgroundColor = ''
              }
            })
          }
        }
      }

      if (editorRef.current) {
        contentRef.current = editorRef.current.innerHTML
      }
      // 手动更新格式状态
      setFmtState(prev => ({ ...prev, highlight: false }))
      // 派发 selectionchange 让 updateFmt 重新检测
      document.dispatchEvent(new Event('selectionchange'))
    } else {
      // hiliteColor 在 Firefox 生效, backColor 在 Chrome 生效
      execCmd('hiliteColor', color)
      execCmd('backColor', color)
    }
    setShowHighlightPicker(false)
  }

  // ---- 插入图片 ----
  const handleInsertImage = () => {
    imageInputRef.current?.click()
  }

  const handleImageSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    // 限制 2MB
    if (file.size > 2 * 1024 * 1024) {
      toast('图片大小不能超过 2MB')
      e.target.value = ''
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result as string
      const el = editorRef.current
      if (!el) return
      // 查找或创建隐藏的图片容器
      let imgContainer = el.querySelector<HTMLDivElement>('div[data-memo-images]')
      if (!imgContainer) {
        imgContainer = document.createElement('div')
        imgContainer.setAttribute('data-memo-images', '1')
        imgContainer.style.display = 'none'
        el.appendChild(imgContainer)
      }
      // 在容器中追加 img 标签
      const img = document.createElement('img')
      img.src = dataUrl
      img.setAttribute('data-memo-img', '1')
      img.setAttribute('alt', file.name)
      imgContainer.appendChild(img)
      contentRef.current = el.innerHTML
      // 触发重新渲染缩略图栏
      setImgVersion(v => v + 1)
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  // 删除编辑器中的图片
  const handleDeleteImage = (index: number) => {
    const el = editorRef.current
    if (!el) return
    const imgContainer = el.querySelector<HTMLDivElement>('div[data-memo-images]')
    if (!imgContainer) return
    const imgs = imgContainer.querySelectorAll('img[data-memo-img]')
    if (imgs[index]) {
      imgs[index].remove()
      contentRef.current = el.innerHTML
      setImgVersion(v => v + 1)
    }
  }

  // 从编辑器隐藏容器中提取图片列表
  const editorImages = useMemo(() => {
    const el = editorRef.current
    if (!el) return []
    const imgContainer = el.querySelector<HTMLDivElement>('div[data-memo-images]')
    if (!imgContainer) return []
    return Array.from(imgContainer.querySelectorAll<HTMLImageElement>('img[data-memo-img]')).map(img => ({
      src: img.src,
      alt: img.getAttribute('alt') || '',
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imgVersion])

  // 插入 OneNote 风格标记
  const handleInsertMarker = (html: string) => {
    execCmd('insertHTML', html)
    setShowMarkers(false)
  }

  // 插入手绘 K 线图
  const handleInsertKChart = (svg: string) => {
    execCmd('insertHTML', svg)
  }

  // 双击已插入的 K 线图重新编辑
  const handleKChartDoubleClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement
    const svgEl = target.closest('svg[data-kchart]') as HTMLElement | null
    if (!svgEl) return
    e.preventDefault()
    const data = parseKChartFromSvg(svgEl)
    if (data) {
      setEditingKChart({ data, element: svgEl })
      setShowKChart(true)
    }
  }

  const meta = TYPE_META[type]
  const TypeIcon = meta.icon

  const watchlistSymbols = watchlistData?.symbols ?? []
  const strategies = strategyData?.strategies ?? []

  return (
    <>
      {/* 遮罩 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 全屏编辑面板 */}
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.96, opacity: 0 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className="fixed inset-0 z-[101] flex items-center justify-center p-4 sm:p-6 md:p-10"
      >
        <div className="w-full max-w-3xl h-full max-h-[92vh] flex flex-col rounded-2xl border border-border bg-surface text-foreground shadow-2xl overflow-hidden">
          {/* 顶部工具栏 */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
            {/* 类型选择 */}
            <div className="flex items-center gap-0.5">
              {ALL_TYPES.map(t => {
                const m = TYPE_META[t]
                const Icon = m.icon
                return (
                  <button
                    key={t}
                    onClick={() => setType(t)}
                    className={cn(
                      'flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs transition-all',
                      type === t
                        ? cn(m.bg, m.color, 'font-medium ring-1 ring-current/20')
                        : 'text-muted hover:bg-elevated hover:text-foreground',
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">{m.label}</span>
                  </button>
                )
              })}
            </div>

            {/* 右侧操作：标签 + 关联 + 关闭 */}
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setShowTags(s => !s)}
                className={cn(
                  'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs transition-colors',
                  showTags ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-elevated',
                )}
                title="标签管理"
              >
                <TagIcon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">标签</span>
              </button>
              <button
                onClick={() => setShowLink(s => !s)}
                className={cn(
                  'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs transition-colors',
                  showLink ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-elevated',
                )}
                title="关联股票与策略"
              >
                <Link2 className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">关联</span>
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-muted hover:bg-elevated hover:text-foreground transition-colors"
                title="关闭 (Esc)"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* 富文本工具栏 */}
          <div className="flex items-center gap-0.5 px-4 py-1.5 border-b border-border shrink-0 bg-muted/20 flex-wrap">
            <ToolbarBtn onClick={handleBold} title="加粗 (Ctrl+B)" active={fmtState.bold}>
              <Bold className="h-4 w-4" />
            </ToolbarBtn>

            {/* 高亮颜色选择 */}
            <div className="relative">
              <ToolbarBtn
                onClick={() => setShowHighlightPicker(s => !s)}
                title="文字底色"
                active={showHighlightPicker || fmtState.highlight}
              >
                <Highlighter className="h-4 w-4" />
              </ToolbarBtn>
              <AnimatePresence>
                {showHighlightPicker && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    className="absolute top-full left-0 mt-1 z-20 flex items-center gap-1 p-2 rounded-lg border border-border bg-surface shadow-lg"
                  >
                    {HIGHLIGHT_COLORS.map(c => (
                      <button
                        key={c.value}
                        onMouseDown={e => e.preventDefault()}
                        onClick={() => handleHighlight(c.value)}
                        className="w-6 h-6 rounded border border-border hover:scale-110 transition-transform"
                        style={{ backgroundColor: c.value === 'transparent' ? '#fff' : c.value }}
                        title={c.name}
                      >
                        {c.value === 'transparent' && (
                          <X className="h-3 w-3 mx-auto text-muted" />
                        )}
                      </button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* 标记 (OneNote 风格) */}
            <div className="relative">
              <ToolbarBtn
                onClick={() => setShowMarkers(s => !s)}
                title="插入标记"
                active={showMarkers}
              >
                <Flag className="h-4 w-4" />
              </ToolbarBtn>
              <AnimatePresence>
                {showMarkers && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    className="absolute top-full left-0 mt-1 z-20 w-36 p-1.5 rounded-lg border border-border bg-surface shadow-lg"
                  >
                    {MARKERS.map(mk => {
                      const Icon = mk.icon
                      return (
                        <button
                          key={mk.id}
                          onMouseDown={e => e.preventDefault()}
                          onClick={() => handleInsertMarker(mk.html)}
                          className="flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-xs hover:bg-elevated transition-colors"
                        >
                          <Icon className="h-3.5 w-3.5 shrink-0" />
                          <span dangerouslySetInnerHTML={{ __html: mk.html }} />
                          {mk.label}
                        </button>
                      )
                    })}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <ToolbarDivider />

            <ToolbarBtn
              onClick={() => { setEditingKChart(null); setShowKChart(true) }}
              title="插入手绘 K 线图"
            >
              <CandlestickChart className="h-4 w-4" />
            </ToolbarBtn>

            <ToolbarBtn onClick={handleInsertImage} title="插入图片 (最大 2MB)">
              <ImageIcon className="h-4 w-4" />
            </ToolbarBtn>

            <ToolbarDivider />

            <ToolbarBtn onClick={handleBulletList} title="项目符号">
              <List className="h-4 w-4" />
            </ToolbarBtn>
            <ToolbarBtn onClick={handleNumberedList} title="编号列表">
              <ListOrdered className="h-4 w-4" />
            </ToolbarBtn>

            <ToolbarDivider />

            <ToolbarBtn onClick={handleAlignLeft} title="左对齐">
              <AlignLeft className="h-4 w-4" />
            </ToolbarBtn>
            <ToolbarBtn onClick={handleAlignCenter} title="居中">
              <AlignCenter className="h-4 w-4" />
            </ToolbarBtn>
            <ToolbarBtn onClick={handleAlignRight} title="右对齐">
              <AlignRight className="h-4 w-4" />
            </ToolbarBtn>
            <ToolbarBtn onClick={handleAlignJustify} title="两端对齐">
              <AlignJustify className="h-4 w-4" />
            </ToolbarBtn>

            <ToolbarDivider />

            <ToolbarBtn
              onClick={() => setShowRuled(s => !s)}
              title="显示/隐藏行线"
              active={showRuled}
            >
              <AlignJustify className="h-4 w-4 rotate-90" />
            </ToolbarBtn>
          </div>

          {/* 主编辑区 */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {/* 类型标记 */}
            <div className="flex items-center gap-2 mb-3 text-xs text-muted">
              <TypeIcon className={cn('h-4 w-4', meta.color)} />
              <span className={meta.color}>{meta.label}</span>
              <span className="text-muted/50">·</span>
              <span>{editing ? '编辑' : '新建'}</span>
              {editing && (
                <>
                  <span className="text-muted/50">·</span>
                  <span>{(editing.created_at || '').slice(0, 16).replace('T', ' ')}</span>
                </>
              )}
            </div>

            {/* 标题输入 */}
            <input
              ref={titleRef}
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="标题"
              className="w-full text-xl font-semibold bg-transparent text-foreground border-none focus:outline-none placeholder:text-muted/40 mb-3"
            />

            {/* 富文本编辑区 */}
            <div
              ref={editorRef}
              contentEditable={true}
              suppressContentEditableWarning
              data-placeholder="写下你的想法..."
              onInput={() => {
                if (editorRef.current) {
                  contentRef.current = editorRef.current.innerHTML
                }
              }}
              onDoubleClick={handleKChartDoubleClick}
              className={cn(
                'w-full min-h-[40vh] text-base leading-relaxed bg-transparent text-foreground focus:outline-none cursor-text',
                'memo-content-editor',
                showRuled && 'memo-ruled-lines',
              )}
            />

            {/* 图片附件缩略图栏 */}
            {editorImages.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-border">
                {editorImages.map((img, i) => (
                  <div
                    key={i}
                    className="relative group"
                    onClick={(e) => {
                      e.stopPropagation()
                      setLightboxSrc({ src: img.src, alt: img.alt })
                    }}
                  >
                    <img
                      src={img.src}
                      alt={img.alt}
                      className="w-20 h-20 object-cover rounded-lg border border-border cursor-pointer"
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteImage(i)
                      }}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-destructive text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm"
                      title="删除图片"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* 隐藏的图片上传 input */}
            <input
              ref={imageInputRef}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
              onChange={handleImageSelected}
              className="hidden"
            />
          </div>

          {/* 标签面板 */}
          <AnimatePresence initial={false}>
            {showTags && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2, ease: 'easeInOut' }}
                className="overflow-hidden border-t border-border"
              >
                <div className="px-6 py-4 bg-muted/30 max-h-[30vh] overflow-y-auto">
                  <TagEditor
                    tags={tags}
                    onChange={setTags}
                    watchlistSymbols={watchlistSymbols.map(s => ({ symbol: s.symbol, name: s.name }))}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* 关联面板 */}
          <AnimatePresence initial={false}>
            {showLink && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2, ease: 'easeInOut' }}
                className="overflow-hidden border-t border-border"
              >
                <div className="px-6 py-4 space-y-4 bg-muted/30 max-h-[35vh] overflow-y-auto">
                  {/* 股票关联 */}
                  <SymbolPicker
                    value={relatedSymbol}
                    onChange={setRelatedSymbol}
                    watchlistSymbols={watchlistSymbols.map(s => ({ symbol: s.symbol, name: s.name }))}
                  />
                  {/* 策略关联 */}
                  <StrategyPicker
                    value={relatedStrategy}
                    onChange={setRelatedStrategy}
                    strategies={strategies.map(s => ({ id: s.id, name: s.name }))}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* 底部操作栏 */}
          <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
            <div className="flex items-center gap-2 text-[11px] text-muted">
              <kbd className="px-1.5 py-0.5 rounded border border-border bg-surface">Esc</kbd>
              <span>关闭</span>
              <kbd className="ml-2 px-1.5 py-0.5 rounded border border-border bg-surface">Ctrl+↵</kbd>
              <span>保存</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg border border-border hover:bg-elevated transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                className="px-5 py-2 text-sm rounded-lg bg-accent text-white hover:opacity-90 transition-opacity font-medium"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      </motion.div>

      {/* 手绘 K 线图对话框 */}
      <AnimatePresence>
        {showKChart && (
          <KChartDialog
            initialData={editingKChart?.data}
            onClose={() => { setShowKChart(false); setEditingKChart(null) }}
            onInsert={(svg) => {
              if (editingKChart?.element) {
                // 编辑模式: 替换原有 SVG
                editingKChart.element.outerHTML = svg
                if (editorRef.current) {
                  contentRef.current = editorRef.current.innerHTML
                }
              } else {
                // 新建模式: 插入
                handleInsertKChart(svg)
              }
            }}
          />
        )}
      </AnimatePresence>

      {/* 图片放大弹窗 */}
      {lightboxSrc && (
        <ImageLightbox
          src={lightboxSrc.src}
          alt={lightboxSrc.alt}
          onClose={() => setLightboxSrc(null)}
        />
      )}
    </>
  )
}

// ---- 工具栏按钮 ----
function ToolbarBtn({
  onClick,
  title,
  active,
  children,
}: {
  onClick: () => void
  title: string
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseDown={e => e.preventDefault()} // 不夺焦点
      className={cn(
        'p-1.5 rounded-md transition-colors',
        active
          ? 'bg-accent text-white shadow-sm'
          : 'text-muted hover:bg-elevated hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function ToolbarDivider() {
  return <div className="w-px h-5 bg-border mx-1" />
}

// ---- 标签编辑器 (带确认/取消) ----
function TagEditor({
  tags,
  onChange,
  watchlistSymbols,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  watchlistSymbols: { symbol: string; name?: string | null }[]
}) {
  const [draft, setDraft] = useState<string[]>(tags) // 草稿态
  const [tagInput, setTagInput] = useState('')
  const [showWatchlistPicker, setShowWatchlistPicker] = useState(false)
  const [symbolSearch, setSymbolSearch] = useState('')

  // 确认提交
  const confirmTags = () => {
    onChange(draft)
  }

  // 取消
  const cancelTags = () => {
    setDraft(tags)
    setTagInput('')
  }

  const addTag = (t: string) => {
    const cleaned = t.trim().replace(/^#/, '')
    if (cleaned && !draft.includes(cleaned)) {
      setDraft([...draft, cleaned])
    }
    setTagInput('')
  }

  const removeTag = (t: string) => {
    setDraft(draft.filter(x => x !== t))
  }

  const filteredSymbols = watchlistSymbols.filter(s =>
    s.symbol.toLowerCase().includes(symbolSearch.toLowerCase()) ||
    (s.name || '').toLowerCase().includes(symbolSearch.toLowerCase())
  )

  return (
    <div>
      <div className="text-[11px] font-medium text-muted mb-1.5">标签</div>

      {/* 已选标签 */}
      <div className="flex items-center gap-1.5 flex-wrap mb-2">
        {draft.map(tag => (
          <span
            key={tag}
            className="inline-flex items-center gap-0.5 px-2 py-1 rounded-lg text-xs bg-accent/10 text-accent"
          >
            #{tag}
            <button onClick={() => removeTag(tag)} className="hover:opacity-70 ml-0.5">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {draft.length === 0 && (
          <span className="text-[11px] text-muted">暂无标签</span>
        )}
      </div>

      {/* 输入行 */}
      <div className="flex items-center gap-1.5 mb-2">
        <input
          value={tagInput}
          onChange={e => setTagInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              addTag(tagInput)
            }
          }}
          placeholder="输入标签后回车..."
          className="flex-1 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-surface focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          onClick={() => addTag(tagInput)}
          className="px-2.5 py-1.5 text-xs rounded-lg border border-border hover:bg-elevated transition-colors"
        >
          添加
        </button>
        <button
          onClick={() => setShowWatchlistPicker(s => !s)}
          className={cn(
            'flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border transition-colors',
            showWatchlistPicker
              ? 'border-accent bg-accent/10 text-accent'
              : 'border-border hover:bg-elevated',
          )}
        >
          <SearchIcon className="h-3 w-3" />
          从关注选
        </button>
      </div>

      {/* 关注列表选择器 */}
      <AnimatePresence initial={false}>
        {showWatchlistPicker && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="p-2 rounded-lg border border-border bg-surface max-h-40 overflow-y-auto">
              <input
                value={symbolSearch}
                onChange={e => setSymbolSearch(e.target.value)}
                placeholder="搜索代码或名称..."
                className="w-full px-2 py-1 text-xs mb-2 rounded border border-border bg-transparent focus:outline-none focus:border-accent"
              />
              <div className="grid grid-cols-2 gap-1">
                {filteredSymbols.slice(0, 30).map(s => (
                  <button
                    key={s.symbol}
                    onClick={() => {
                      if (!draft.includes(s.symbol)) {
                        setDraft([...draft, s.symbol])
                      }
                    }}
                    className="flex items-center justify-between px-2 py-1 text-xs rounded hover:bg-elevated transition-colors text-left"
                  >
                    <span className="font-mono">{s.symbol}</span>
                    <span className="text-muted truncate ml-1">{s.name}</span>
                  </button>
                ))}
                {filteredSymbols.length === 0 && (
                  <div className="col-span-2 text-center text-[11px] text-muted py-2">
                    {watchlistSymbols.length === 0 ? '关注列表为空' : '无匹配结果'}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 确认/取消按钮 */}
      <div className="flex items-center justify-end gap-2 mt-2">
        <button
          onClick={cancelTags}
          className="px-3 py-1 text-xs rounded-lg border border-border hover:bg-elevated transition-colors"
        >
          取消
        </button>
        <button
          onClick={confirmTags}
          className="flex items-center gap-1 px-3 py-1 text-xs rounded-lg bg-accent text-white hover:opacity-90 transition-opacity"
        >
          <Check className="h-3 w-3" />
          确认
        </button>
      </div>
    </div>
  )
}

// ---- 股票选择器 (多选: 手动输入 + 关注列表下拉) ----
function SymbolPicker({
  value,
  onChange,
  watchlistSymbols,
}: {
  value: string[]
  onChange: (v: string[]) => void
  watchlistSymbols: { symbol: string; name?: string | null }[]
}) {
  const [showDropdown, setShowDropdown] = useState(false)
  const [search, setSearch] = useState('')
  const [manualInput, setManualInput] = useState('')

  const filtered = watchlistSymbols.filter(s =>
    s.symbol.toLowerCase().includes(search.toLowerCase()) ||
    (s.name || '').toLowerCase().includes(search.toLowerCase())
  )

  const addSymbol = (sym: string) => {
    const cleaned = sym.trim().toUpperCase()
    if (cleaned && !value.includes(cleaned)) {
      onChange([...value, cleaned])
    }
  }

  const removeSymbol = (sym: string) => {
    onChange(value.filter(s => s !== sym))
  }

  const nameOf = (sym: string) => watchlistSymbols.find(s => s.symbol === sym)?.name

  return (
    <div className="space-y-1.5">
      {/* 标签行 */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs font-medium text-foreground">关联股票</span>
        <span className="text-[10px] text-muted">可多选，手动输入或从关注列表选择</span>
      </div>

      {/* 已选股票 chips */}
      {value.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          {value.map(sym => (
            <span
              key={sym}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400"
            >
              {sym}{nameOf(sym) ? ` ${nameOf(sym)}` : ''}
              <button
                onMouseDown={e => e.preventDefault()}
                onClick={() => removeSymbol(sym)}
                className="hover:opacity-70 ml-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* 输入框 + 关注按钮 */}
      <div className="relative">
        <input
          value={manualInput}
          onChange={e => setManualInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              if (manualInput.trim()) {
                addSymbol(manualInput)
                setManualInput('')
              }
            }
          }}
          onFocus={() => setShowDropdown(true)}
          onBlur={() => setTimeout(() => setShowDropdown(false), 250)}
          placeholder="输入股票代码后回车添加，如 300265.SZ"
          className="w-full pl-3 pr-24 py-2.5 text-sm rounded-lg border border-border bg-surface text-foreground focus:outline-none focus:ring-2 focus:ring-accent/30 transition-all"
        />
        {/* 添加按钮 */}
        {manualInput.trim() && (
          <button
            onMouseDown={e => e.preventDefault()}
            onClick={() => {
              addSymbol(manualInput)
              setManualInput('')
            }}
            className="absolute right-12 top-1/2 -translate-y-1/2 p-0.5 text-muted hover:text-accent transition-colors"
            title="添加"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        )}
        {/* 展开关注列表按钮 */}
        <button
          onMouseDown={e => e.preventDefault()}
          onClick={() => setShowDropdown(s => !s)}
          className={cn(
            'absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-0.5 px-2 py-1 text-[11px] rounded-md transition-colors',
            showDropdown ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-elevated hover:text-foreground',
          )}
          title="从关注列表选择"
        >
          <SearchIcon className="h-3 w-3" />
        </button>
      </div>

      {/* 关注列表下拉 */}
      <AnimatePresence initial={false}>
        {showDropdown && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="mt-1 rounded-lg border border-border bg-surface shadow-md max-h-52 overflow-y-auto">
              {/* 搜索框 */}
              <div className="sticky top-0 p-2 bg-surface border-b border-border relative">
                <SearchIcon className="absolute left-3.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="搜索代码或名称..."
                  className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-border bg-surface text-foreground focus:outline-none focus:border-accent"
                  onMouseDown={e => e.preventDefault()}
                />
              </div>
              {/* 列表 */}
              {filtered.length > 0 ? (
                <div className="py-1">
                  {filtered.slice(0, 30).map(s => {
                    const selected = value.includes(s.symbol)
                    return (
                      <button
                        key={s.symbol}
                        onMouseDown={e => {
                          e.preventDefault()
                          if (selected) {
                            removeSymbol(s.symbol)
                          } else {
                            addSymbol(s.symbol)
                          }
                        }}
                        className={cn(
                          'flex items-center justify-between w-full px-3 py-1.5 text-xs hover:bg-elevated transition-colors text-left',
                          selected && 'bg-accent/10',
                        )}
                      >
                        <span className="font-mono text-foreground">{s.symbol}</span>
                        <span className="flex items-center gap-1.5">
                          <span className="text-muted truncate max-w-[140px]">{s.name}</span>
                          {selected && <Check className="h-3 w-3 text-accent shrink-0" />}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="text-center text-[11px] text-muted py-4">
                  {watchlistSymbols.length === 0 ? '关注列表为空' : '无匹配结果'}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ---- 策略选择器 (多选, 只能从列表选) ----
function StrategyPicker({
  value,
  onChange,
  strategies,
}: {
  value: string[]
  onChange: (v: string[]) => void
  strategies: { id: string; name: string }[]
}) {
  const [showDropdown, setShowDropdown] = useState(false)
  const [search, setSearch] = useState('')

  const filtered = strategies.filter(s =>
    s.id.toLowerCase().includes(search.toLowerCase()) ||
    s.name.toLowerCase().includes(search.toLowerCase())
  )

  const toggleStrategy = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter(s => s !== id))
    } else {
      onChange([...value, id])
    }
  }

  // 已选策略的名称映射
  const selectedNames = value.map(id => ({
    id,
    name: strategies.find(s => s.id === id)?.name || id,
  }))

  return (
    <div className="space-y-1.5">
      {/* 标签行 */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs font-medium text-foreground">关联策略</span>
        <span className="text-[10px] text-muted">可多选，仅从策略列表选择</span>
      </div>

      {/* 已选策略 chips */}
      {selectedNames.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          {selectedNames.map(s => (
            <span
              key={s.id}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400"
            >
              {s.name}
              <button
                onMouseDown={e => e.preventDefault()}
                onClick={() => toggleStrategy(s.id)}
                className="hover:opacity-70 ml-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* 选择按钮 */}
      <button
        onClick={() => setShowDropdown(s => !s)}
        className={cn(
          'w-full pl-3 pr-10 py-2.5 text-sm rounded-lg border border-border bg-surface text-left flex items-center justify-between transition-all',
          showDropdown ? 'ring-2 ring-accent/30' : 'hover:bg-elevated',
        )}
      >
        <span className="text-muted">点击选择策略...</span>
        <ChevronDown className={cn(
          'h-4 w-4 text-muted shrink-0 transition-transform',
          showDropdown && 'rotate-180',
        )} />
      </button>

      {/* 下拉列表 */}
      <AnimatePresence initial={false}>
        {showDropdown && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="mt-1 rounded-lg border border-border bg-surface shadow-md max-h-52 overflow-y-auto">
              {/* 搜索框 */}
              <div className="sticky top-0 p-2 bg-surface border-b border-border">
                <div className="relative">
                  <SearchIcon className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted" />
                  <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="搜索策略名称或 ID..."
                    className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-border bg-surface text-foreground focus:outline-none focus:border-accent"
                    onMouseDown={e => e.preventDefault()}
                  />
                </div>
              </div>
              {/* 列表 */}
              {filtered.length > 0 ? (
                <div className="py-1">
                  {filtered.slice(0, 30).map(s => {
                    const selected = value.includes(s.id)
                    return (
                      <button
                        key={s.id}
                        onMouseDown={e => {
                          e.preventDefault()
                          toggleStrategy(s.id)
                        }}
                        className={cn(
                          'flex items-center justify-between w-full px-3 py-1.5 text-xs hover:bg-elevated transition-colors text-left',
                          selected && 'bg-accent/10 text-accent',
                        )}
                      >
                        <span className="font-medium">{s.name}</span>
                        <span className="flex items-center gap-1.5">
                          <span className="text-muted text-[10px] font-mono">{s.id}</span>
                          {selected && <Check className="h-3 w-3 text-accent shrink-0" />}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="text-center text-[11px] text-muted py-4">
                  {strategies.length === 0 ? '策略列表加载中...' : '无匹配结果'}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
