<script setup lang="ts">
import { computed, onActivated, onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { LabelLayout } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'
import { useRouter } from 'vue-router'
import { dashboardApi, exportApi } from '../api'
import { toast } from '../api/request'
import { loadSubjectOptions } from '../utils/subjects'

echarts.use([GraphChart, LineChart, GridComponent, LegendComponent, TooltipComponent, LabelLayout, CanvasRenderer])

const router = useRouter()
const overview = ref({ total: 0, due_today: 0, week_accuracy: 0, streak: 0 })
const trend = ref<{ date: string; collected: number; reviewed: number; accuracy: number }[]>([])
const distributions = ref<{ subjects: { name: string; count: number }[]; error_types: { name: string; count: number }[] }>({ subjects: [], error_types: [] })
const days = ref(7)
const currentSubject = ref('')
const subjectChips = ref<{ name: string; count: number }[]>([])
const largestSubjectCount = computed(() => Math.max(1, ...distributions.value.subjects.map(s => s.count)))
let trendChart: echarts.EChartsType | null = null
let graphChart: echarts.EChartsType | null = null

async function load() {
  try {
    const [o, t, d] = await Promise.all([
      dashboardApi.overview(currentSubject.value || undefined),
      dashboardApi.trend(days.value, currentSubject.value || undefined),
      dashboardApi.distributions(currentSubject.value || undefined),
    ])
    overview.value = o
    trend.value = t
    distributions.value = d
    renderTrend()
    await loadGraph()
  } catch {
    // 请求层已显示可读错误；保留当前图表数据而不是清空页面。
  }
}

function resizeCharts() {
  trendChart?.resize()
  graphChart?.resize()
}

function renderTrend() {
  trendChart?.dispose()
  trendChart = echarts.init(document.getElementById('trendChart')!)
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['收录', '复习', '正确率'], textStyle: { fontSize: 12 }, top: 0 },
    grid: { left: 40, right: 40, top: 36, bottom: 24 },
    xAxis: { type: 'category', data: trend.value.map(t => t.date.slice(5)), boundaryGap: false },
    yAxis: [
      { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: 'rgba(0,0,0,.05)' } } },
      { type: 'value', min: 0, max: 100, show: false },
    ],
    series: [
      { name: '收录', type: 'line', smooth: true, data: trend.value.map(t => t.collected), itemStyle: { color: '#007AFF' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(0,122,255,.25)' }, { offset: 1, color: 'rgba(0,122,255,.02)' }] } } },
      { name: '复习', type: 'line', smooth: true, data: trend.value.map(t => t.reviewed), itemStyle: { color: '#34C759' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(52,199,89,.2)' }, { offset: 1, color: 'rgba(52,199,89,.02)' }] } } },
      { name: '正确率', type: 'line', smooth: true, yAxisIndex: 1, data: trend.value.map(t => t.accuracy), itemStyle: { color: '#FF9500' }, lineStyle: { type: 'dashed', width: 1.5 } },
    ],
  })
}

async function loadGraph() {
  const g = await dashboardApi.graph(currentSubject.value || undefined)
  graphChart?.dispose()
  graphChart = echarts.init(document.getElementById('graphChart')!)
  const subjectNames = new Map(g.nodes
    .filter(n => n.group === 'subject')
    .map(n => [n.id, n.name]))
  const pointSubjects = new Map(
    g.links
      .filter(l => l.kind === 'belongs' || !l.kind)
      .map(l => [l.target, subjectNames.get(l.source) || ''])
  )
  const nodes = g.nodes.map(n => ({
    id: n.id, name: n.name, symbolSize: Math.min(64, 16 + n.count * 2.4),
    group: n.group, count: n.count, mastery: n.mastery,
    subject: n.group === 'subject' ? n.name : pointSubjects.get(n.id),
    itemStyle: {
      color: n.group === 'subject' ? '#007AFF' : n.mastery < 2 ? '#FF3B30' : n.mastery < 4 ? '#FF9500' : '#34C759',
      shadowBlur: 14, shadowColor: n.group === 'subject' ? 'rgba(0,122,255,.45)' : n.mastery < 2 ? 'rgba(255,59,48,.4)' : n.mastery < 4 ? 'rgba(255,149,0,.4)' : 'rgba(52,199,89,.4)',
      borderColor: '#fff', borderWidth: 2,
    },
    label: {
      // 知识点统一显示名称，避免部分节点有字、部分节点没字造成误解。
      show: true,
      position: n.group === 'subject' ? 'inside' : 'right',
      distance: 8,
      fontSize: 10, fontWeight: n.group === 'subject' ? 600 : 500,
      color: n.group === 'subject' ? '#FFFFFF' : '#1F2937',
      backgroundColor: n.group === 'subject' ? 'transparent' : '#FFFFFF',
      borderColor: n.group === 'subject' ? 'transparent' : '#D1D5DB',
      borderWidth: n.group === 'subject' ? 0 : 1,
      borderRadius: 5, padding: [3, 6],
      shadowBlur: 2, shadowColor: 'rgba(15,23,42,.16)',
      formatter: (params: { data: { name: string } }) => {
        const name = String(params.data.name || '')
        return name.length > 14 ? `${name.slice(0, 13)}…` : name
      },
    },
  }))
  const links = g.links.map(l => ({
    source: l.source, target: l.target,
    kind: l.kind,
    keywords: l.keywords,
    lineStyle: l.kind === 'related'
      ? { color: 'rgba(255,149,0,.58)', width: 1.5, type: 'dashed', curveness: 0.16 }
      : { color: 'rgba(0,122,255,.35)', width: 1.2, curveness: 0.08 },
  }))
  graphChart.setOption({
    tooltip: {
      formatter: (p: any) => {
        if (p.dataType === 'edge') return ''
        const name = echarts.format.encodeHTML(String(p.data.name || ''))
        const meta = p.data.group === 'subject' ? '学科' : `掌握度 ${p.data.mastery ?? 0}/5`
        return `${name}<br/>${meta} · ${p.data.count ?? 0} 题`
      },
    },
    series: [{
      type: 'graph', layout: 'force', data: nodes, links,
      // 为标签预留四周空间，避免长知识点名称被图谱容器裁切。
      left: 96, right: 96, top: 58, bottom: 58,
      roam: true, draggable: true,
      // 用户要求知识点标签统一显示，不自动隐藏任何节点文字。
      labelLayout: { hideOverlap: false },
      force: { repulsion: 420, edgeLength: [58, 100], gravity: 0.22, friction: 0.68 },
      // 不使用 adjacency 聚焦：它会将非相邻节点及其文字淡化到几乎不可读。
      emphasis: { focus: 'none', lineStyle: { width: 2.5, color: 'rgba(0,122,255,.8)' } },
      animationDuration: 900, animationEasingUpdate: 'quinticInOut',
    }],
  })
  graphChart.on('click', (p: any) => {
    if (p.dataType !== 'node') return
    const node = p.data
    router.push({
      path: '/questions',
      query: node.group === 'point'
        ? { subject: node.subject, knowledge_point: node.name }
        : { subject: node.name },
    })
  })
}

async function downloadWeekly(kind: 'markdown' | 'pdf') {
  try {
    const blob = kind === 'pdf'
      ? await exportApi.weeklyPdf({ subject: currentSubject.value || undefined })
      : await exportApi.weeklyMarkdown({ subject: currentSubject.value || undefined })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `recall_weekly.${kind === 'pdf' ? 'pdf' : 'md'}`
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    toast('周报生成失败，请稍后重试', 'error')
  }
}

onMounted(() => {
  load()
  loadSubjectOptions().then((rows: { name: string; count: number }[]) => subjectChips.value = rows)
  window.addEventListener('resize', resizeCharts)
})
onActivated(load)
onUnmounted(() => {
  window.removeEventListener('resize', resizeCharts)
  trendChart?.dispose()
  graphChart?.dispose()
})
</script>

<template>
  <div class="max-w-6xl mx-auto px-4 sm:px-6 py-8">
    <div class="flex items-center mb-6 flex-wrap gap-2">
      <h1 class="text-h1">数据看板</h1>
      <div class="ml-auto flex gap-1 bg-card border border-border rounded-btn p-1 overflow-x-auto max-w-full">
        <button class="px-3 py-1 rounded-tag text-caption"
                :class="currentSubject === '' ? 'bg-primary text-white' : 'text-textSecondary'"
                @click="currentSubject = ''; load()">全部 ({{ overview.total }})</button>
        <button v-for="s in subjectChips" :key="s.name" class="px-3 py-1 rounded-tag text-caption"
                :class="currentSubject === s.name ? 'bg-primary text-white' : 'text-textSecondary'"
                @click="currentSubject = s.name; load()">{{ s.name }} ({{ s.count }})</button>
      </div>
      <div class="sm:ml-3 flex gap-1 bg-card border border-border rounded-btn p-1">
        <button v-for="d in [7, 30]" :key="d" class="px-3 py-1 rounded-tag text-caption"
                :class="days === d ? 'bg-primary text-white' : 'text-textSecondary'"
                @click="days = d; load()">近 {{ d }} 天</button>
      </div>
      <div class="sm:ml-3 flex gap-1 flex-wrap">
        <button class="border border-border rounded-btn px-3 py-1 text-caption text-textSecondary hover:border-primary" @click="downloadWeekly('markdown')">下载周报 MD</button>
        <button class="bg-primary text-white rounded-btn px-3 py-1 text-caption" @click="downloadWeekly('pdf')">下载周报 PDF</button>
      </div>
    </div>

    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
      <div class="bg-card border border-border rounded-card p-4">
        <div class="text-caption text-textSecondary mb-1">错题总数</div>
        <div class="text-2xl font-semibold">{{ overview.total }}</div>
      </div>
      <div class="bg-card border border-border rounded-card p-4">
        <div class="text-caption text-textSecondary mb-1">待复习</div>
        <div class="text-2xl font-semibold text-warning">{{ overview.due_today }}</div>
      </div>
      <div class="bg-card border border-border rounded-card p-4">
        <div class="text-caption text-textSecondary mb-1">本周正确率</div>
        <div class="text-2xl font-semibold text-success">{{ overview.week_accuracy }}%</div>
      </div>
      <div class="bg-card border border-border rounded-card p-4">
        <div class="text-caption text-textSecondary mb-1">连续打卡</div>
        <div class="text-2xl font-semibold">{{ overview.streak }} 天</div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-5">
      <div class="bg-card border border-border rounded-card p-5">
        <h2 class="text-h2 mb-3">学习趋势</h2>
        <div id="trendChart" class="h-52" />
      </div>
      <div class="bg-card border border-border rounded-card p-5">
        <div class="flex items-center justify-between mb-1">
          <h2 class="text-h2">知识图谱</h2>
          <div class="flex items-center gap-3 text-[11px] text-textTertiary">
            <span class="inline-flex items-center gap-1"><i class="w-4 border-t border-primary" />学科归属</span>
            <span class="inline-flex items-center gap-1"><i class="w-4 border-t border-dashed border-warning" />知识点关联</span>
          </div>
        </div>
        <div id="graphChart" class="h-72" />
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-card border border-border rounded-card p-5">
        <h2 class="text-h2 mb-4">学科分布</h2>
        <div v-for="s in distributions.subjects" :key="s.name" class="flex items-center gap-2 mb-3">
          <span class="w-14 text-caption text-textSecondary">{{ s.name }}</span>
          <div class="flex-1 h-2.5 bg-bg rounded-full overflow-hidden">
            <div class="h-full bg-primary rounded-full" :style="{ width: (s.count / largestSubjectCount * 100) + '%' }" />
          </div>
          <span class="w-10 text-right text-caption text-textSecondary">{{ s.count }} 题</span>
        </div>
        <div v-if="!distributions.subjects.length" class="text-caption text-textTertiary text-center py-6">暂无数据</div>
      </div>
      <div class="bg-card border border-border rounded-card p-5">
        <h2 class="text-h2 mb-4">错因分布 TOP</h2>
        <div v-for="(e, i) in distributions.error_types" :key="e.name" class="flex items-center gap-3 mb-3">
          <span class="w-5 h-5 rounded-tag text-xs flex items-center justify-center font-medium"
                :class="i === 0 ? 'bg-error text-white' : i === 1 ? 'bg-warning text-white' : 'bg-bg text-textSecondary'">{{ i + 1 }}</span>
          <span class="flex-1 text-body">{{ e.name }}</span>
          <span class="text-caption text-textSecondary">{{ e.count }} 题</span>
        </div>
        <div v-if="!distributions.error_types.length" class="text-caption text-textTertiary text-center py-6">暂无数据</div>
      </div>
    </div>
  </div>
</template>
