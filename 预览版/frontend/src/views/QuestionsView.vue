<script setup lang="ts">
import { computed, onActivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { Menu, Search, SlidersHorizontal, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { questionApi, notebookApi, exportApi, dashboardApi } from '../api'
import { toast } from '../api/request'
import QuestionCard from '../components/QuestionCard.vue'
import MarkdownView from '../components/MarkdownView.vue'
import { SUBJECTS, SUBJECT_COLORS, subjectColor } from '../utils/subjects'
import type { Question } from '../types'

const route = useRoute()
const router = useRouter()
const items = ref<Question[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const currentSubject = ref('')            // '' = 全部
const knowledgePoint = ref('')
const errorType = ref('')
const filtersOpen = ref(false)
const sortBy = ref('created_at')          // created_at | difficulty
const sortOrder = ref('desc')             // desc | asc
const loading = ref(false)
const subjectCounts = ref<{ name: string; count: number }[]>([])
const sidebarTotal = ref(0)  // 全部错题总数（全局，不随筛选变化）
const notebooks = ref<{ id: number; name: string; color: string; count: number }[]>([])
const selectedIds = ref<number[]>([])
const bulkOpen = ref(false)
const bulkSubject = ref('')
const bulkKnowledge = ref('')
const bulkError = ref('')
const bulkDifficulty = ref('')
const savedFilters = ref<{ name: string; keyword: string; subject: string; knowledgePoint: string; errorType: string; sortValue: string }[]>([])
const sidebarOpen = ref(false)
let loadRequestId = 0

// 合并侧栏：学科聚合 + 空学科错题本（未出现在聚合中的已创建错题本）
const sidebarItems = computed(() => {
  const rows = subjectCounts.value.map(s => ({
    name: s.name, count: s.count,
    color: subjectColor(s.name),
    notebookId: notebooks.value.find(n => n.name === s.name + '错题本')?.id ?? null,
  }))
  const names = new Set(rows.map(r => r.name))
  for (const nb of notebooks.value) {
    const subject = nb.name.replace(/错题本$/, '')
    if (!names.has(subject) && subject) {
      rows.push({ name: subject, count: 0, color: nb.color, notebookId: nb.id })
      names.add(subject)
    }
  }
  rows.sort((a, b) => b.count - a.count)
  return rows
})
const newNotebook = ref(false)
const newSubject = ref('数学')
const newName = ref('数学错题本')
const newColor = ref('#007AFF')

const subjects = ['', ...SUBJECTS]
const errorTypes = ['', '概念不清', '审题失误', '粗心', '计算错误', '方法不当', '超纲', '其他']

const sortOptions = [
  { value: 'created_at_desc', label: '录入时间 · 新→旧' },
  { value: 'created_at_asc', label: '录入时间 · 旧→新' },
  { value: 'difficulty_desc', label: '难度 · 难→易' },
  { value: 'difficulty_asc', label: '难度 · 易→难' },
]
const sortValue = ref('created_at_desc')
watch(sortValue, (v) => {
  const splitAt = v.lastIndexOf('_')
  sortBy.value = v.slice(0, splitAt)
  sortOrder.value = v.slice(splitAt + 1)
  page.value = 1
  load()
})
watch(errorType, () => { page.value = 1; load() })

async function load(append = false): Promise<boolean> {
  const requestId = ++loadRequestId
  loading.value = true
  try {
    const res = await questionApi.list({
      subject: currentSubject.value || undefined,
      knowledge_point: knowledgePoint.value || undefined,
      error_type: errorType.value || undefined,
      keyword: keyword.value || undefined,
      sort_by: sortBy.value,
      order: sortOrder.value,
      page: page.value, page_size: 20,
    })
    if (requestId !== loadRequestId) return false
    items.value = append ? [...items.value, ...res.items] : res.items
    total.value = res.total
    return true
  } catch {
    return false
  } finally {
    if (requestId === loadRequestId) loading.value = false
  }
}

async function loadMore() {
  if (loading.value || items.value.length >= total.value) return
  page.value += 1
  if (!await load(true)) page.value -= 1
}

function selectSubject(s: string) {
  sidebarOpen.value = false
  const query = { ...route.query }
  delete query.knowledge_point
  if (s) query.subject = s
  else delete query.subject
  router.replace({ path: route.path, query })
}

function syncRouteFilters() {
  currentSubject.value = typeof route.query.subject === 'string' ? route.query.subject : ''
  knowledgePoint.value = typeof route.query.knowledge_point === 'string' ? route.query.knowledge_point : ''
  page.value = 1
}

function clearKnowledgePoint() {
  const query = { ...route.query }
  delete query.knowledge_point
  if (currentSubject.value) query.subject = currentSubject.value
  else delete query.subject
  router.replace({ path: route.path, query })
}

async function loadSidebar() {
  const [d, nbs, ov] = await Promise.all([dashboardApi.distributions(), notebookApi.list(), dashboardApi.overview()])
  subjectCounts.value = d.subjects
  notebooks.value = nbs
  sidebarTotal.value = ov.total
}

watch(() => [route.query.subject, route.query.knowledge_point], () => {
  syncRouteFilters()
  load()
})
onMounted(async () => {
  syncRouteFilters()
  await Promise.all([loadSidebar(), load()])
  loadSavedFilters()
  window.addEventListener('keydown', onKeydown)
  // 测试入口：?export=1 自动打开导出对话框（用于 headless 打印验证）
  if (new URLSearchParams(location.search).get('export')) openExport()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
// keep-alive 切回时刷新数据（筛选/滚动等状态保持不变）
onActivated(() => { Promise.all([loadSidebar(), load()]) })

async function onSearch() { page.value = 1; await load() }
function clearFilters() {
  keyword.value = ''
  errorType.value = ''
  sortValue.value = 'created_at_desc'
  filtersOpen.value = false
  page.value = 1
  load()
}
async function onDelete(id: number) {
  if (!confirm('确定删除这道错题？')) return
  await questionApi.remove(id)
  await Promise.all([load(), loadSidebar()])
}
async function onSaved(q: Question) {
  await questionApi.update(q.id, q)
  toast('已保存')
  await Promise.all([load(), loadSidebar()])
}

function toggleSelected(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter(item => item !== id)
    : [...selectedIds.value, id]
}

async function applyBulk() {
  if (!selectedIds.value.length) return
  const data = { subject: bulkSubject.value || undefined, knowledge_point: bulkKnowledge.value || undefined,
    error_type: bulkError.value || undefined, difficulty: bulkDifficulty.value || undefined }
  if (!Object.values(data).some(Boolean)) { toast('请选择至少一个修改字段', 'error'); return }
  try {
    const result = await questionApi.bulkUpdate(selectedIds.value, data)
    toast(`已更新 ${result.updated} 道错题`)
    selectedIds.value = []
    bulkOpen.value = false
    await Promise.all([load(), loadSidebar()])
  } catch { /* request interceptor handles error */ }
}

function loadSavedFilters() {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem('recall-question-filters') || '[]')
    savedFilters.value = Array.isArray(stored) ? stored.filter((item): item is typeof savedFilters.value[number] =>
      !!item && typeof item === 'object' && typeof (item as { name?: unknown }).name === 'string'
    ).map(item => ({
      name: item.name, keyword: item.keyword || '', subject: item.subject || '', knowledgePoint: item.knowledgePoint || '',
      errorType: item.errorType || '', sortValue: sortOptions.some(option => option.value === item.sortValue) ? item.sortValue : 'created_at_desc',
    })) : []
  } catch { savedFilters.value = [] }
}
function saveCurrentFilter() {
  const name = prompt('保存筛选名称')?.trim()
  if (!name) return
  const item = { name, keyword: keyword.value, subject: currentSubject.value, knowledgePoint: knowledgePoint.value, errorType: errorType.value, sortValue: sortValue.value }
  savedFilters.value = [...savedFilters.value.filter(filter => filter.name !== name), item]
  localStorage.setItem('recall-question-filters', JSON.stringify(savedFilters.value))
}
function applySavedFilter(filter: typeof savedFilters.value[number] | undefined) {
  if (!filter) return
  keyword.value = filter.keyword
  errorType.value = filter.errorType
  sortValue.value = filter.sortValue
  router.replace({ path: '/questions', query: { ...(filter.subject ? { subject: filter.subject } : {}), ...(filter.knowledgePoint ? { knowledge_point: filter.knowledgePoint } : {}) } })
}
function onSavedFilterChange(event: Event) {
  const index = Number((event.target as HTMLSelectElement).value)
  if (Number.isInteger(index)) applySavedFilter(savedFilters.value[index])
}
function deleteSavedFilter(name: string) {
  savedFilters.value = savedFilters.value.filter(filter => filter.name !== name)
  localStorage.setItem('recall-question-filters', JSON.stringify(savedFilters.value))
}
async function refreshAfterCardChange() {
  await Promise.all([load(), loadSidebar()])
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && exportOpen.value) exportOpen.value = false
}

function pickSubject(s: string) {
  newSubject.value = s
  newName.value = s + '错题本'
  newColor.value = SUBJECT_COLORS[s] || '#007AFF'
}
async function createNotebook() {
  if (!newName.value.trim()) return
  // 已存在同名错题本则提示
  if (notebooks.value.some(n => n.name === newName.value.trim())) {
    toast('该学科错题本已存在', 'error')
    return
  }
  await notebookApi.create(newName.value.trim(), newColor.value)
  newNotebook.value = false
  await loadSidebar()
  toast(`✅ 已创建「${newName.value.trim()}」`)
}
async function removeSubjectNotebook(s: { name: string; count: number }) {
  const msg = s.count > 0
    ? `确定删除「${s.name}错题本」？其中 ${s.count} 道错题将一并删除！`
    : `确定删除「${s.name}错题本」？`
  if (!confirm(msg)) return
  const r = await questionApi.deleteBySubject(s.name)
  toast(`🗑️ 已删除「${s.name}错题本」`)
  if (currentSubject.value === s.name) selectSubject('')
  await Promise.all([loadSidebar(), load()])
}
function download(type: 'pdf' | 'md') {
  const fn = type === 'pdf' ? 'recall_export.pdf' : 'recall_export.md'
  const p = type === 'pdf'
    ? exportApi.pdf({ subject: currentSubject.value || undefined })
    : exportApi.markdown({ subject: currentSubject.value || undefined })
  p.then((blob) => {
    const url = URL.createObjectURL(blob as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = fn; a.click()
    URL.revokeObjectURL(url)
  })
}

// ===== 导出对话框（可选答案/解析 + 渲染预览 + 打印 PDF）=====
const exportOpen = ref(false)
const exportMd = ref('')
const exportAnswer = ref(true)
const exportAnalysis = ref(true)
const exportLoading = ref(false)

async function refreshExportMd() {
  exportLoading.value = true
  try {
    const params = new URLSearchParams()
    if (currentSubject.value) params.set('subject', currentSubject.value)
    params.set('include_answer', String(exportAnswer.value))
    params.set('include_analysis', String(exportAnalysis.value))
    const resp = await fetch(`/api/export/markdown?${params.toString()}`)
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(body?.message || '导出内容加载失败')
    }
    exportMd.value = await resp.text()
  } catch (error) {
    exportMd.value = '⚠️ 导出内容加载失败'
    toast(error instanceof Error ? error.message : '导出内容加载失败', 'error')
  } finally {
    exportLoading.value = false
  }
}

function openExport() {
  exportOpen.value = true
  refreshExportMd()
}

function toggleExportOption() {
  refreshExportMd()
}

function downloadMd() {
  const blob = new Blob([exportMd.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'recall_export.md'; a.click()
  URL.revokeObjectURL(url)
}

function printPdf() {
  // 内容为空时先加载再打印（避免打印空白页）
  if (!exportMd.value || exportMd.value.startsWith('⚠️')) {
    refreshExportMd().then(() => window.print())
  } else {
    window.print()
  }
}

// 仅在用户明确下载 PDF 时加载较大的导出依赖，避免影响错题本首屏。
const pdfGenerating = ref(false)
async function downloadPdf() {
  if (pdfGenerating.value) return
  if (!exportMd.value || exportMd.value.startsWith('⚠️')) {
    await refreshExportMd()
  }
  if (!exportMd.value || exportMd.value.startsWith('⚠️')) return
  pdfGenerating.value = true
  try {
    const [{ default: html2canvas }, { jsPDF }] = await Promise.all([import('html2canvas'), import('jspdf')])
    await new Promise(resolve => setTimeout(resolve, 100))
    const el = document.getElementById('export-preview')
    if (!el) { toast('预览区域不存在', 'error'); return }
    const canvas = await html2canvas(el, { scale: 2, useCORS: true, backgroundColor: '#ffffff', logging: false })
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pageW = 210
    const pageH = 297
    const margin = 8
    const imgW = pageW - margin * 2
    const imgH = canvas.height * imgW / canvas.width
    const imgData = canvas.toDataURL('image/jpeg', 0.95)
    let heightLeft = imgH
    let position = margin
    pdf.addImage(imgData, 'JPEG', margin, position, imgW, imgH)
    heightLeft -= (pageH - margin * 2)
    while (heightLeft > 0) {
      position = margin - (imgH - heightLeft)
      pdf.addPage()
      pdf.addImage(imgData, 'JPEG', margin, position, imgW, imgH)
      heightLeft -= (pageH - margin * 2)
    }
    pdf.save('recall_export.pdf')
    toast('✅ PDF 已下载')
  } catch (e) {
    toast('PDF 生成失败，请重试', 'error')
    console.error(e)
  } finally {
    pdfGenerating.value = false
  }
}
</script>

<template>
  <div class="flex min-h-[calc(100vh-60px)]">
    <button type="button" class="fixed left-3 top-[68px] z-30 inline-flex items-center gap-1 rounded-btn border border-border bg-card px-3 py-1.5 text-caption text-textSecondary shadow-sm md:hidden" @click="sidebarOpen = true">
      <Menu :size="15" /> 错题本
    </button>
    <div v-if="sidebarOpen" class="fixed inset-0 z-30 bg-black/30 md:hidden" @click="sidebarOpen = false" />
    <!-- 左栏：学科错题本；小屏使用可关闭抽屉，避免挤压题目正文 -->
    <aside class="fixed inset-y-[60px] left-0 z-40 w-[280px] shrink-0 bg-card border-r border-border p-4 flex flex-col overflow-y-auto transition-transform md:static md:w-[260px] md:translate-x-0"
           :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full'">
      <div class="flex items-center justify-between px-2 pb-2">
        <span class="text-caption text-textTertiary">错题本</span>
        <div class="flex items-center gap-2">
          <button type="button" aria-label="关闭错题本侧栏" class="text-textSecondary md:hidden" @click="sidebarOpen = false"><X :size="16" /></button>
          <button class="text-caption text-primary font-medium" @click="newNotebook = !newNotebook">＋ 新增</button>
        </div>
      </div>
      <div class="flex items-center gap-2 px-2 py-2 rounded-btn cursor-pointer"
           :class="currentSubject === '' ? 'bg-primary/10 font-medium' : 'hover:bg-bg'"
           @click="selectSubject('')">
        <span class="w-2 h-2 rounded-full shrink-0 bg-textTertiary" />
        <span class="flex-1 truncate">全部错题</span>
        <span class="text-caption text-textTertiary font-medium tabular-nums w-8 text-center inline-block shrink-0">{{ sidebarTotal }}</span>
        <span class="w-5 h-5 shrink-0" />
      </div>
      <div v-for="s in sidebarItems" :key="s.name"
           class="flex items-center gap-2 px-2 py-2 rounded-btn cursor-pointer group"
           :class="currentSubject === s.name ? 'bg-primary/10 font-medium' : 'hover:bg-bg'"
           @click="selectSubject(s.name)">
        <span class="w-2 h-2 rounded-full shrink-0" :style="{ background: s.color }" />
        <span class="flex-1 truncate">{{ s.name }}</span>
        <span class="text-caption text-textTertiary tabular-nums w-8 text-center inline-block shrink-0">{{ s.count }}</span>
        <!-- 每个错题本都有 ✕ 删除（点击确认后删除该学科全部错题） -->
        <button class="w-5 h-5 rounded text-textTertiary hover:text-error text-caption shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                @click.stop="removeSubjectNotebook(s)">✕</button>
      </div>
      <div v-if="!sidebarItems.length" class="text-caption text-textTertiary text-center py-4">暂无错题</div>

      <!-- 新增学科错题本 -->
      <div v-if="newNotebook" class="mt-3 space-y-2 border-t border-border pt-3">
        <div class="flex gap-1 flex-wrap">
          <button v-for="s in SUBJECTS" :key="s"
                  class="text-caption px-2 py-0.5 rounded-tag border"
                  :class="newSubject === s ? 'bg-primary text-white border-primary' : 'border-border text-textSecondary'"
                  @click="pickSubject(s)">{{ s }}</button>
        </div>
        <input v-model="newName" placeholder="错题本名称" class="w-full border border-border rounded-btn p-2 text-body" />
        <div class="flex gap-2">
          <button v-for="c in Object.values(SUBJECT_COLORS)" :key="c" class="w-5 h-5 rounded-full border border-border"
                  :style="{ background: c }" @click="newColor = c" />
        </div>
        <button class="w-full bg-primary text-white rounded-btn py-1.5 text-sm" @click="createNotebook">创建</button>
      </div>
    </aside>

    <!-- 右栏 -->
    <main class="min-w-0 flex-1 p-4 pt-14 sm:p-6 sm:pt-6 overflow-y-auto">
      <div class="flex items-center mb-4 gap-2 flex-wrap">
        <h1 class="text-h1">{{ currentSubject ? currentSubject + '错题本' : '错题本' }}</h1>
        <div class="ml-auto flex gap-2 flex-wrap">
          <button class="text-caption px-3 py-1.5 rounded-btn border border-border text-textSecondary" @click="openExport">导出 MD</button>
          <button class="text-caption px-3 py-1.5 rounded-btn border border-border text-textSecondary" @click="openExport">导出 PDF</button>
        </div>
      </div>

      <div class="flex gap-2 mb-4 flex-wrap items-center">
        <button class="px-3 py-1 rounded-tag border text-caption"
                :class="currentSubject === '' ? 'bg-primary border-primary text-white' : 'bg-card border-border text-textSecondary'"
                @click="selectSubject('')">全部 ({{ sidebarTotal }})</button>
        <button v-for="s in sidebarItems" :key="s.name" class="px-3 py-1 rounded-tag border text-caption"
                :class="currentSubject === s.name ? 'bg-primary border-primary text-white' : 'bg-card border-border text-textSecondary'"
                @click="selectSubject(s.name)">{{ s.name }} ({{ s.count }})</button>
        <button v-if="knowledgePoint" class="px-3 py-1 rounded-tag border border-primary/30 bg-primary/10 text-primary text-caption"
                @click="clearKnowledgePoint">知识点：{{ knowledgePoint }} ×</button>
        <button class="ml-auto inline-flex items-center gap-1.5 border rounded-btn px-3 py-1.5 text-caption transition-colors"
                :class="filtersOpen || errorType || sortValue !== 'created_at_desc' ? 'border-primary/40 bg-primary/5 text-primary' : 'border-border text-textSecondary hover:border-borderStrong'"
                @click="filtersOpen = !filtersOpen"><SlidersHorizontal :size="15" /> 筛选与排序</button>
        <label class="relative">
          <Search :size="15" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-textTertiary" />
          <input v-model="keyword" placeholder="搜索错题" class="border border-border rounded-btn py-1.5 pl-8 pr-3 w-48 text-body outline-none focus:border-primary"
                 @keyup.enter="onSearch" />
        </label>
        <button class="bg-primary text-white rounded-btn px-4 py-1.5 text-sm" @click="onSearch">搜索</button>
      </div>
      <div v-if="filtersOpen" class="mb-4 rounded-card border border-border bg-card px-4 py-3 flex items-center gap-3">
        <span class="text-caption text-textSecondary">错因</span>
        <select v-model="errorType" class="border border-border rounded-btn px-3 py-1.5 text-caption bg-card outline-none focus:border-primary">
          <option value="">全部错因</option>
          <option v-for="e in errorTypes.slice(1)" :key="e">{{ e }}</option>
        </select>
        <span class="text-caption text-textSecondary">排序</span>
        <select v-model="sortValue" class="border border-border rounded-btn px-3 py-1.5 text-caption bg-card outline-none focus:border-primary">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <button class="ml-auto inline-flex items-center gap-1 text-caption text-textTertiary hover:text-error" @click="clearFilters"><X :size="14" /> 重置筛选</button>
      </div>

      <div class="flex items-center gap-2 text-caption text-textSecondary mb-3">
        <span>共 {{ total }} 道错题<span v-if="errorType || knowledgePoint" class="ml-1">· 已应用筛选</span></span>
        <button type="button" class="text-primary" @click="saveCurrentFilter">保存当前筛选</button>
        <select v-if="savedFilters.length" aria-label="已保存筛选" class="border border-border rounded-btn px-2 py-1 text-caption bg-card" @change="onSavedFilterChange">
          <option value="" selected>恢复筛选</option>
          <option v-for="(filter, index) in savedFilters" :key="filter.name" :value="index">{{ filter.name }}</option>
        </select>
        <button v-for="filter in savedFilters" :key="`delete-${filter.name}`" type="button" class="text-textTertiary hover:text-error" :aria-label="`删除保存筛选 ${filter.name}`" :title="`删除 ${filter.name}`" @click="deleteSavedFilter(filter.name)"><X :size="13" /></button>
      </div>
      <div v-if="selectedIds.length" class="mb-3 flex flex-wrap items-center gap-2 rounded-btn border border-primary/30 bg-primary/5 px-3 py-2">
        <span class="text-caption text-primary">已选择 {{ selectedIds.length }} 道</span>
        <button class="text-caption border border-primary/30 rounded-btn px-2 py-1 text-primary" @click="bulkOpen = !bulkOpen">批量编辑</button>
        <button class="text-caption text-textSecondary" @click="selectedIds = []">取消选择</button>
      </div>
      <div v-if="bulkOpen" class="mb-3 grid grid-cols-1 sm:grid-cols-5 gap-2 rounded-card border border-border bg-card p-3">
        <select v-model="bulkSubject" aria-label="批量学科" class="border border-border rounded-btn px-2 py-1.5 text-caption"><option value="">学科不变</option><option v-for="s in SUBJECTS" :key="s">{{ s }}</option></select>
        <input v-model="bulkKnowledge" aria-label="批量知识点" placeholder="知识点不变" class="border border-border rounded-btn px-2 py-1.5 text-caption" />
        <select v-model="bulkError" aria-label="批量错因" class="border border-border rounded-btn px-2 py-1.5 text-caption"><option value="">错因不变</option><option v-for="e in errorTypes.slice(1)" :key="e">{{ e }}</option></select>
        <select v-model="bulkDifficulty" aria-label="批量难度" class="border border-border rounded-btn px-2 py-1.5 text-caption"><option value="">难度不变</option><option v-for="d in ['易','中','难']" :key="d">{{ d }}</option></select>
        <button class="bg-primary text-white rounded-btn px-3 py-1.5 text-caption" @click="applyBulk">应用修改</button>
      </div>

      <div v-if="loading" class="space-y-3">
        <div v-for="i in 3" :key="i" class="bg-bg border border-border rounded-card h-24 animate-pulse" />
      </div>
      <div v-else-if="items.length === 0" class="text-center py-16">
        <div class="text-4xl mb-3">📭</div>
        <div class="text-textSecondary mb-4">暂无错题</div>
        <div class="flex gap-3 justify-center">
          <router-link to="/capture" class="bg-primary text-white rounded-btn px-4 py-2 text-sm">📷 识图录入</router-link>
          <router-link to="/input" class="border border-border bg-card rounded-btn px-4 py-2 text-sm text-textSecondary">✍️ 文本录入</router-link>
          <router-link to="/chat" class="border border-border bg-card rounded-btn px-4 py-2 text-sm text-textSecondary">💬 AI 答疑</router-link>
        </div>
      </div>
      <div v-for="q in items" v-else :key="q.id" class="flex items-start gap-2">
        <input type="checkbox" :checked="selectedIds.includes(q.id)" :aria-label="`选择错题 ${q.id}`" class="mt-5 accent-[#007AFF]" @change="toggleSelected(q.id)" />
        <QuestionCard class="flex-1 min-w-0" :q="q" @delete="onDelete" @saved="onSaved" @changed="refreshAfterCardChange" />
      </div>

      <div v-if="items.length < total" class="text-center py-4">
        <button class="text-primary text-caption disabled:opacity-40" :disabled="loading" @click="loadMore">{{ loading ? '加载中…' : `加载更多（${items.length}/${total}）` }}</button>
      </div>
    </main>

    <!-- 导出对话框 -->
    <div v-if="exportOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 no-print" @click.self="exportOpen = false">
      <div class="bg-card rounded-card w-[720px] max-w-[92vw] max-h-[85vh] flex flex-col shadow-xl">
        <div class="flex items-center px-5 py-3 border-b border-border">
          <b class="text-body">📤 导出错题本</b>
          <span class="ml-auto text-caption text-textTertiary">{{ currentSubject || '全部' }} · 预览即最终效果</span>
          <button class="ml-3 text-textTertiary hover:text-error" @click="exportOpen = false">✕</button>
        </div>
        <div class="px-5 py-3 flex items-center gap-4 border-b border-border/60">
          <label class="flex items-center gap-1.5 text-caption cursor-pointer">
            <input type="checkbox" v-model="exportAnswer" class="accent-[#007AFF]" @change="toggleExportOption" /> 包含答案
          </label>
          <label class="flex items-center gap-1.5 text-caption cursor-pointer">
            <input type="checkbox" v-model="exportAnalysis" class="accent-[#007AFF]" @change="toggleExportOption" /> 包含解析
          </label>
          <div class="ml-auto flex gap-2">
            <button class="text-caption border border-border rounded-btn px-3 py-1.5 text-textSecondary hover:border-borderStrong" @click="downloadMd">⬇️ 下载 MD</button>
            <button class="text-caption bg-primary text-white rounded-btn px-3 py-1.5 disabled:opacity-50" :disabled="pdfGenerating" @click="downloadPdf">
              {{ pdfGenerating ? '生成中…' : '⬇️ 下载 PDF' }}
            </button>
          </div>
        </div>
        <div class="flex-1 overflow-y-auto p-5 bg-bg/50">
          <div v-if="exportLoading" class="text-center text-caption text-textTertiary py-8">加载中…</div>
          <div v-else id="export-preview" class="bg-card border border-border rounded-card p-5"><MarkdownView :content="exportMd" /></div>
        </div>
      </div>
    </div>

    <!-- 打印区域（@media print 时只显示这里；打开导出时才挂载，确保内容已加载） -->
    <div v-if="exportOpen" id="print-area" class="print-only">
      <MarkdownView :content="exportMd" />
    </div>
  </div>
</template>
