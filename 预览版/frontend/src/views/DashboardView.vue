<script setup lang="ts">
import { onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { planApi, dashboardApi, questionApi, notebookApi } from '../api'
import { loadSubjectOptions } from '../utils/subjects'
import { useNotebookStore } from '../stores/notebook'
import MarkdownView from '../components/MarkdownView.vue'
import { AlertTriangle, BookOpenCheck, CalendarDays, Camera, ChevronRight, Layers3, MessageCircle, PenLine, Play, Sparkles } from '@lucide/vue'
import type { Question } from '../types'

const router = useRouter()
const store = useNotebookStore()
const due = ref<Question[]>([])
const queue = ref({ overdue_count: 0, total_due: 0, remaining_count: 0, daily_limit: 20 })
const overview = ref({ total: 0, due_today: 0, week_accuracy: 0, streak: 0 })
const recent = ref<Question[]>([])
const learningPlan = ref<{ subject: string; knowledge_point: string; question_count: number; wrong_count: number; overdue_count: number; mastery: number; error_type: string; recommended_count: number; action: string }[]>([])
const alerts = ref<{ type: 'overdue' | 'weak'; title: string; item: { subject: string; knowledge_point: string; recommended_count: number } }[]>([])
const calendar = ref<{ date: string; due: number; completed: number }[]>([])
const currentSubject = ref('')
const subjectChips = ref<{ name: string; count: number }[]>([])

function localMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

async function loadData() {
  try {
    const month = localMonth()
    const [d, o, r, plan, warning, monthData] = await Promise.all([
      planApi.daily(currentSubject.value || undefined, 20),
      dashboardApi.overview(currentSubject.value || undefined),
      questionApi.list({ subject: currentSubject.value || undefined, page: 1, page_size: 5, sort_by: 'created_at', order: 'desc' }),
      dashboardApi.learningPlan(currentSubject.value || undefined),
      dashboardApi.alerts(currentSubject.value || undefined),
      planApi.calendar(month, currentSubject.value || undefined),
    ])
    due.value = d.due
    queue.value = d
    overview.value = o
    recent.value = r.items
    learningPlan.value = plan
    alerts.value = warning
    calendar.value = monthData.days
  } catch { /* 后端未启动时静默 */ }
}

async function loadChips() {
  subjectChips.value = await loadSubjectOptions()
}

onMounted(async () => {
  try {
    await store.load()
    await loadData()
    await loadChips()
  } catch { /* 静默 */ }
})

// keep-alive 切回时刷新数据（界面状态保持不变）
onActivated(() => {
  store.load(); loadData(); loadChips()
})

async function quickAdd() {
  const name = prompt('错题本名称', '默认错题本')
  if (!name) return
  await store.create(name, '#007AFF')
}

function startDailyReview() {
  router.push({ path: '/redo', query: { mode: 'daily', subject: currentSubject.value || undefined } })
}

function startCalendarDay(day: { date: string; due: number }) {
  if (!day.due) return
  router.push({ path: '/redo', query: { mode: 'daily', subject: currentSubject.value || undefined, date: day.date } })
}

function startPlan(item: { subject: string; knowledge_point: string }) {
  router.push({ path: '/redo', query: { mode: 'daily', subject: item.subject, knowledge_point: item.knowledge_point } })
}

const calendarSummary = () => {
  const completed = calendar.value.reduce((sum, item) => sum + item.completed, 0)
  const dueCount = calendar.value.reduce((sum, item) => sum + item.due, 0)
  return `${completed} 次完成 / ${dueCount} 次到期`
}
</script>

<template>
  <div class="max-w-5xl mx-auto px-4 sm:px-6 py-8">
    <div class="flex items-center mb-6 gap-2 flex-wrap">
      <h1 class="text-h1">仪表盘</h1>
      <div class="sm:ml-auto flex gap-2 flex-wrap">
        <button class="px-3 py-1 rounded-tag border text-caption"
                :class="currentSubject === '' ? 'bg-primary border-primary text-white' : 'bg-card border-border text-textSecondary'"
                @click="currentSubject = ''; loadData()">全部 ({{ overview.total }})</button>
        <button v-for="s in subjectChips" :key="s.name" class="px-3 py-1 rounded-tag border text-caption"
                :class="currentSubject === s.name ? 'bg-primary border-primary text-white' : 'bg-card border-border text-textSecondary'"
                @click="currentSubject = s.name; loadData()">{{ s.name }} ({{ s.count }})</button>
        <button class="bg-primary text-white rounded-btn px-4 py-2 text-sm hover:opacity-90 inline-flex items-center gap-1.5" @click="router.push('/review')">
          <BookOpenCheck :size="16" /> 举一反三
        </button>
      </div>
    </div>

    <!-- 今日队列 -->
    <div class="bg-card border border-border rounded-card p-5 mb-6">
      <div class="flex items-center mb-3 gap-3 flex-wrap">
        <div>
          <h2 class="text-h2">今日复习队列</h2>
          <span class="text-caption text-textSecondary">{{ queue.total_due }} 道待处理 · 今日建议先完成 {{ due.length }} 道</span>
        </div>
        <div v-if="due.length" class="sm:ml-auto flex gap-2 flex-wrap">
          <button class="border border-primary/40 text-primary rounded-btn px-3 py-2 text-sm inline-flex items-center gap-1.5 hover:bg-primary/5" @click="router.push('/flashcards')">
            <Layers3 :size="15" /> 3 分钟卡片
          </button>
          <button class="bg-primary text-white rounded-btn px-4 py-2 text-sm inline-flex items-center gap-1.5 hover:opacity-90" @click="startDailyReview">
            <Play :size="15" fill="currentColor" /> 开始今日复习（{{ due.length }}）
          </button>
        </div>
      </div>
      <div v-if="queue.overdue_count" class="mb-3 flex items-center gap-2 rounded-btn border border-warning/30 bg-warning/5 px-3 py-2 text-caption text-warning">
        <AlertTriangle :size="15" /> 有 {{ queue.overdue_count }} 道逾期题已排在队列最前，先完成它们。
      </div>
      <div v-if="due.length === 0" class="text-textSecondary text-body py-6 text-center">
        今日没有到期错题 <button class="text-primary ml-2" @click="router.push('/questions')">去收录新错题</button>
      </div>
      <div v-else class="space-y-2">
        <div v-for="q in due.slice(0, 5)" :key="q.id"
             class="border border-border rounded-btn p-3 flex items-center gap-3 cursor-pointer hover:border-primary/50"
             @click="startDailyReview">
          <span class="w-2 h-2 rounded-full" :style="{ background: q.subject === '数学' ? '#007AFF' : '#FF9500' }" />
          <span class="text-caption px-2 py-0.5 rounded-tag bg-primary/10 text-primary">{{ q.subject }}</span>
          <div class="flex-1 min-w-0 line-clamp-2 text-body"><MarkdownView :content="q.question_text" /></div>
          <ChevronRight :size="16" class="text-textTertiary shrink-0" />
        </div>
      </div>
    </div>

    <!-- 行动建议与复习日历 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
      <section class="lg:col-span-2 bg-card border border-border rounded-card p-5">
        <div class="flex items-center gap-2 mb-4">
          <Sparkles :size="18" class="text-primary" />
          <h2 class="text-h2">本周学习处方</h2>
        </div>
        <div v-if="learningPlan.length" class="space-y-2">
          <button v-for="item in learningPlan" :key="`${item.subject}-${item.knowledge_point}`" type="button"
                  class="w-full text-left border border-border rounded-btn px-3 py-3 hover:border-primary/50 transition"
                  @click="startPlan(item)">
            <div class="flex items-center gap-2">
              <span class="text-caption rounded-tag bg-primary/10 text-primary px-2 py-0.5">{{ item.subject }}</span>
              <span class="font-medium text-body flex-1 truncate">{{ item.knowledge_point }}</span>
              <span class="text-caption text-warning">{{ item.recommended_count }} 题</span>
              <ChevronRight :size="16" class="text-textTertiary" />
            </div>
            <p class="mt-1 text-caption text-textSecondary">{{ item.action }} · 主因：{{ item.error_type }}</p>
          </button>
        </div>
        <p v-else class="py-6 text-center text-body text-textSecondary">继续收录和复习后，这里会给出最需要处理的知识点。</p>
        <div v-if="alerts.length" class="mt-3 flex flex-wrap gap-2">
          <span v-for="alert in alerts" :key="alert.title" class="inline-flex items-center gap-1 rounded-tag bg-warning/10 px-2 py-1 text-caption text-warning">
            <AlertTriangle :size="13" /> {{ alert.title }}
          </span>
        </div>
      </section>
      <section class="bg-card border border-border rounded-card p-5">
        <div class="flex items-center gap-2 mb-2">
          <CalendarDays :size="18" class="text-primary" />
          <h2 class="text-h2">本月复习</h2>
        </div>
        <p class="text-caption text-textSecondary">{{ calendarSummary() }}</p>
        <div class="mt-4 grid grid-cols-7 gap-1.5" aria-label="本月复习完成情况">
          <span v-for="offset in (calendar.length ? new Date(`${calendar[0].date}T00:00:00`).getDay() : 0)" :key="`pad-${offset}`" aria-hidden="true" />
          <button v-for="day in calendar" :key="day.date" type="button" :title="`${day.date}: 到期 ${day.due}，完成 ${day.completed}`"
                  class="h-6 rounded-sm border border-border text-center text-[10px] leading-6"
                  :class="day.completed ? 'bg-success/15 text-success' : day.due ? 'bg-warning/15 text-warning hover:border-warning' : 'bg-bg text-textTertiary'"
                  :disabled="!day.due" @click="startCalendarDay(day)">{{ day.date.slice(-2) }}</button>
        </div>
        <button class="mt-4 text-caption text-primary inline-flex items-center gap-1" @click="startDailyReview">
          <Play :size="13" fill="currentColor" /> 去完成今日计划
        </button>
      </section>
    </div>

    <!-- 快捷入口 -->
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
      <div class="bg-card border border-border rounded-card p-5 text-center cursor-pointer hover:border-primary/50 hover:-translate-y-0.5 transition-all duration-200" @click="router.push('/capture')">
        <Camera :size="26" stroke-width="1.7" class="mx-auto mb-2 text-primary" />
        <div class="font-medium">识图录入</div>
        <div class="text-caption text-textSecondary mt-1">拍照 / 截图 / 粘贴</div>
      </div>
      <div class="bg-card border border-border rounded-card p-5 text-center cursor-pointer hover:border-primary/50 hover:-translate-y-0.5 transition-all duration-200" @click="router.push('/input')">
        <PenLine :size="26" stroke-width="1.7" class="mx-auto mb-2 text-primary" />
        <div class="font-medium">文本录入</div>
        <div class="text-caption text-textSecondary mt-1">手动输入 + AI 归类</div>
      </div>
      <div class="bg-card border border-border rounded-card p-5 text-center cursor-pointer hover:border-primary/50 hover:-translate-y-0.5 transition-all duration-200" @click="router.push('/chat')">
        <MessageCircle :size="26" stroke-width="1.7" class="mx-auto mb-2 text-primary" />
        <div class="font-medium">AI 答疑</div>
        <div class="text-caption text-textSecondary mt-1">拍题 / 提问 / 加入错题本</div>
      </div>
    </div>

    <!-- 数据摘要 + 最近动态 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-card border border-border rounded-card p-5">
        <h2 class="text-h2 mb-4">本周概况</h2>
        <div class="grid grid-cols-2 gap-4 text-center">
          <div><div class="text-2xl font-semibold">{{ overview.total }}</div><div class="text-caption text-textSecondary">错题总数</div></div>
          <div><div class="text-2xl font-semibold text-warning">{{ overview.due_today }}</div><div class="text-caption text-textSecondary">待复习</div></div>
          <div><div class="text-2xl font-semibold text-success">{{ overview.week_accuracy }}%</div><div class="text-caption text-textSecondary">本周正确率</div></div>
          <div><div class="text-2xl font-semibold">{{ overview.streak }} 天</div><div class="text-caption text-textSecondary">连续打卡</div></div>
        </div>
        <button v-if="!store.notebooks.length" class="mt-4 w-full border border-primary/40 text-primary rounded-btn py-2 text-sm" @click="quickAdd">
          创建第一个错题本
        </button>
      </div>
      <div class="bg-card border border-border rounded-card p-5">
        <h2 class="text-h2 mb-4">最近收录</h2>
        <div v-if="recent.length === 0" class="text-textSecondary text-body text-center py-8">还没有错题，去收录吧</div>
        <div v-for="q in recent" :key="q.id" class="flex items-center gap-2 py-2 border-b border-border/60 last:border-0">
          <span class="text-caption px-2 py-0.5 rounded-tag bg-primary/10 text-primary">{{ q.subject }}</span>
          <div class="flex-1 min-w-0 line-clamp-2 text-body"><MarkdownView :content="q.question_text" /></div>
        </div>
      </div>
    </div>
  </div>
</template>
