<script setup lang="ts">
import { ref, watch } from 'vue'
import { Link2, Trash2 } from '@lucide/vue'
import { aiApi, questionApi } from '../api'
import MarkdownView from './MarkdownView.vue'
import FormulaToolbar from './FormulaToolbar.vue'
import KnowledgeModal from './KnowledgeModal.vue'
import GeoGebraPanel from './GeoGebraPanel.vue'
import { subjectColor, difficultyColor } from '../utils/subjects'
import { formatTime } from '../utils/format'
import type { Question } from '../types'

const props = defineProps<{ q: Question }>()
const emit = defineEmits<{ (e: 'delete', id: number): void; (e: 'saved', q: Question): void; (e: 'changed'): void }>()

const expanded = ref(false)
const editing = ref(false)
const aiLoading = ref(false)
const aiStream = ref('')  // AI 流式输出实时内容
const reviewing = ref(false)  // AI 审核中
const fixing = ref(false)     // 一键修正公式中
const review = ref<{ correct: boolean; issue: string; suggested_answer: string; suggested_analysis: string } | null>(null)
const draft = ref<Question>({ ...props.q })
const customError = ref(props.q.error_detail || '')
watch(() => props.q, (question) => {
  draft.value = { ...question }
  customError.value = question.error_detail || ''
}, { deep: true })
const kpOpen = ref(false)  // 知识点学习弹窗
const ggbOpen = ref(false)  // 几何画板
const similarOpen = ref(false)
const similarLoading = ref(false)
const similar = ref<(Question & { similarity: number; reasons: string[] })[]>([])

function appendFormula(field: 'question_text' | 'answer' | 'analysis', formula: string) {
  const current = draft.value[field] || ''
  draft.value[field] = `${current}${current && !current.endsWith('\n') ? '\n' : ''}${formula}`
}

const masteryLabel = (m: number) => (m === 0 ? '未复习' : m <= 2 ? '学习中' : '已掌握')

const isGeometric = (t: string) => /三角形|圆|几何|坐标|平行|垂直|梯形|椭圆|双曲线|抛物线|棱|锥|柱|正方|矩形|角|直线|线段|中点|切线|相切|勾股/.test(t)

function splitAnswer(s: string): { answer: string; analysis: string } {
  const ansM = s.match(/答案\s*[:：]\s*/)
  const anlM = s.match(/解析\s*[:：]\s*/)
  if (ansM && anlM && (anlM.index ?? 0) > (ansM.index ?? 0)) {
    const aEnd = (ansM.index ?? 0) + ansM[0].length
    const lEnd = (anlM.index ?? 0) + anlM[0].length
    return { answer: s.slice(aEnd, anlM.index).trim(), analysis: s.slice(lEnd).trim() }
  }
  return { answer: '', analysis: s }
}

async function aiGenerate() {
  if (!draft.value.question_text.trim()) { alert('请先填写题干'); return }
  aiLoading.value = true
  aiStream.value = ''
  try {
    const resp = await fetch('/api/ai/answer-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_text: draft.value.question_text, subject: draft.value.subject }),
    })
    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let full = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const event = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        const lines = event.split('\n')
        if (lines.find(l => l.startsWith('event: done'))) break
        const dataLines = lines.filter(l => l.startsWith('data: '))
        if (!dataLines.length) continue
        full += dataLines.map(l => l.slice(6)).join('\n')
        aiStream.value = full  // 实时显示
      }
    }
    const { answer, analysis } = splitAnswer(full)
    if (answer) draft.value.answer = answer
    if (analysis) draft.value.analysis = analysis
  } catch {
    aiStream.value = '⚠️ AI 生成失败，请重试'
  } finally {
    aiLoading.value = false
  }
}

async function fixFormulas() {
  if (fixing.value) return
  fixing.value = true
  try {
    const r = await fetch('/api/ai/fix-formulas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question_text: draft.value.question_text,
        answer: draft.value.answer,
        analysis: draft.value.analysis,
      }),
    })
    const j = await r.json()
    const d = j?.data
    if (d) {
      if (d.question_text) draft.value.question_text = d.question_text
      if (d.answer) draft.value.answer = d.answer
      if (d.analysis) draft.value.analysis = d.analysis
    }
  } catch {
    // 静默：修正失败不打断编辑
  } finally {
    fixing.value = false
  }
}

async function aiReview() {
  if (reviewing.value) return
  reviewing.value = true
  review.value = null
  try {
    const r = await fetch('/api/ai/review-question', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question_text: draft.value.question_text,
        answer: draft.value.answer,
        analysis: draft.value.analysis,
      }),
    })
    const j = await r.json()
    review.value = j?.data || { correct: true, issue: '审核失败', suggested_answer: '', suggested_analysis: '' }
  } catch {
    review.value = { correct: false, issue: '⚠️ 审核服务不可用，请稍后重试', suggested_answer: '', suggested_analysis: '' }
  } finally {
    reviewing.value = false
  }
}

function applyReview() {
  if (!review.value) return
  if (review.value.suggested_answer) draft.value.answer = review.value.suggested_answer
  if (review.value.suggested_analysis) draft.value.analysis = review.value.suggested_analysis
  review.value = null
}

async function loadSimilar() {
  similarOpen.value = !similarOpen.value
  if (!similarOpen.value || similar.value.length || similarLoading.value) return
  similarLoading.value = true
  try {
    similar.value = await questionApi.similar(props.q.id)
  } finally {
    similarLoading.value = false
  }
}

async function mergeDuplicate(duplicate: Question) {
  if (!confirm(`确认将这道相似题合并到当前题目？会迁移它的复习记录，并删除重复题。`)) return
  try {
    await questionApi.mergeDuplicate(props.q.id, duplicate.id)
    similar.value = similar.value.filter(item => item.id !== duplicate.id)
    emit('changed')
  } catch {
    // 请求模块会显示具体错误提示。
  }
}

function save() {
  // 统计只保存受控标签；自定义具体描述保留在详情字段。
  draft.value.error_detail = draft.value.error_type === '其他' ? customError.value.trim() : (draft.value.error_detail || '')
  editing.value = false
  emit('saved', draft.value)
}
</script>

<template>
  <div class="group bg-card border border-border rounded-card p-4 mb-3 hover:border-borderStrong transition cursor-pointer"
       @click="expanded = !expanded">
    <div class="flex items-center gap-2 mb-2 flex-wrap">
      <span class="text-caption px-2 py-0.5 rounded-tag" :style="{ background: subjectColor(q.subject) + '1A', color: subjectColor(q.subject) }">{{ q.subject }}</span>
      <span v-if="q.knowledge_point" class="text-caption px-2 py-0.5 rounded-tag bg-bg text-textSecondary">{{ q.knowledge_point }}</span>
      <span class="text-caption px-2 py-0.5 rounded-tag bg-bg text-textSecondary" :title="q.error_detail || q.error_type">{{ q.error_type }}</span>
      <span class="text-caption px-2 py-0.5 rounded-tag" :style="{ background: difficultyColor(q.difficulty) + '1A', color: difficultyColor(q.difficulty) }">{{ q.difficulty }}</span>
      <span class="text-caption text-textTertiary">🕐 {{ formatTime(q.created_at) }}</span>
      <span class="text-caption px-2 py-0.5 rounded-tag ml-auto"
            :class="q.mastery_level >= 3 ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'">
        {{ masteryLabel(q.mastery_level) }}
      </span>
      <button type="button" title="删除这道错题" aria-label="删除这道错题"
              class="w-7 h-7 inline-flex items-center justify-center rounded-btn text-textTertiary hover:text-error hover:bg-error/5 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
              @click.stop="emit('delete', q.id)">
        <Trash2 :size="15" />
      </button>
    </div>

    <!-- 题目区（蓝左边框，Markdown+公式渲染；带图题显示配图） -->
    <div class="border-l-[3px] border-question pl-3 py-1">
      <!-- 编辑时，上方白色题目区与下方草稿预览始终使用同一份内容 -->
      <MarkdownView :content="editing ? draft.question_text : q.question_text" />
      <img v-if="q.image_url" :src="q.image_url" class="mt-2 max-h-64 rounded-lg border border-border/60" />
    </div>

    <!-- 展开区：考察知识点 + 解析 + 操作 -->
    <div v-if="expanded" class="mt-3">
      <div v-if="!editing">
        <div class="mb-2 text-body">📌 <b>考察知识点：</b><span class="text-textSecondary">{{ q.knowledge_point || '—' }}</span></div>
        <div v-if="q.error_detail" class="mb-2 text-caption text-textSecondary">具体错因：{{ q.error_detail }}</div>
        <div class="border-l-[3px] border-analysis pl-3 py-1 bg-[#F9FFFB] rounded-r-btn">
          <div class="text-caption text-textSecondary mb-1">答案</div><MarkdownView :content="q.answer || '（未填写）'" />
          <div v-if="q.analysis" class="text-caption text-textSecondary mt-2 mb-1">解析</div>
          <MarkdownView v-if="q.analysis" :content="q.analysis" />
        </div>
        <div class="flex gap-2 mt-3 flex-wrap">
          <button class="text-caption px-3 py-1 rounded-btn border border-border text-textSecondary hover:border-borderStrong"
                  @click.stop="editing = true">编辑</button>
          <button class="text-caption px-3 py-1 rounded-btn border border-border text-textSecondary hover:border-primary inline-flex items-center gap-1"
                  @click.stop="loadSimilar"><Link2 :size="13" /> {{ similarOpen ? '收起相似题' : '查看相似题' }}</button>
          <button class="text-caption px-3 py-1 rounded-btn border border-error/40 text-error hover:bg-error/5"
                  @click.stop="emit('delete', q.id)">删除</button>
        </div>
        <div v-if="similarOpen" class="mt-3 rounded-btn border border-border bg-bg/50 p-3" @click.stop>
          <div v-if="similarLoading" class="text-caption text-textTertiary">正在查找相似题…</div>
          <div v-else-if="!similar.length" class="text-caption text-textTertiary">暂无明显相似题</div>
          <div v-for="item in similar" :key="item.id" class="flex items-start gap-2 py-2 border-b border-border/60 last:border-0">
            <div class="flex-1 min-w-0">
              <div class="text-caption text-textSecondary">相似度 {{ Math.round(item.similarity * 100) }}% · {{ item.reasons.join('、') }}</div>
              <div class="line-clamp-2 text-body"><MarkdownView :content="item.question_text" /></div>
            </div>
            <button type="button" class="shrink-0 text-caption text-error border border-error/30 rounded-btn px-2 py-1" @click="mergeDuplicate(item)">合并</button>
          </div>
        </div>
      </div>
      <div v-else class="space-y-2" @click.stop>
        <textarea v-model="draft.question_text" rows="2"
                  class="w-full border border-border rounded-btn p-2 text-body focus:border-primary outline-none" />
        <FormulaToolbar class="mt-1" @insert="appendFormula('question_text', $event)" />
        <!-- 题干实时预览（LaTeX 自动渲染） -->
        <div v-if="draft.question_text.trim()" class="bg-bg border border-border/60 rounded-btn px-3 py-2 max-h-40 overflow-y-auto">
          <div class="text-caption text-textTertiary mb-1">👁 题干预览（公式自动渲染）</div>
          <MarkdownView :content="draft.question_text" />
        </div>
        <div class="flex gap-2 items-center">
          <input v-model="draft.answer" placeholder="答案（可手动输入或 AI 生成）"
                 class="flex-1 border border-border rounded-btn p-2 text-body focus:border-primary outline-none" />
          <button class="text-caption px-3 py-1.5 rounded-btn border border-primary/40 text-primary whitespace-nowrap disabled:opacity-40"
                  :disabled="aiLoading" @click="aiGenerate">{{ aiLoading ? '生成中…' : '✨ AI 生成' }}</button>
        </div>
        <FormulaToolbar class="mt-1" @insert="appendFormula('answer', $event)" />
        <!-- AI 流式生成实时预览 -->
        <div v-if="aiLoading || aiStream" class="bg-bg border border-primary/30 rounded-btn px-3 py-2 max-h-56 overflow-y-auto">
          <div class="text-caption text-primary mb-1">🤖 AI 生成中…（实时输出）</div>
          <MarkdownView :content="aiStream" />
        </div>
        <!-- 答案实时预览 -->
        <div v-if="draft.answer.trim()" class="bg-bg border border-border/60 rounded-btn px-3 py-2 max-h-40 overflow-y-auto">
          <div class="text-caption text-textTertiary mb-1">👁 答案预览（公式自动渲染）</div>
          <MarkdownView :content="draft.answer" />
        </div>
        <textarea v-model="draft.analysis" rows="2" placeholder="解析（可手动输入或 AI 生成）"
                  class="w-full border border-border rounded-btn p-2 text-body focus:border-primary outline-none" />
        <FormulaToolbar class="mt-1" @insert="appendFormula('analysis', $event)" />
        <!-- 解析实时预览 -->
        <div v-if="draft.analysis.trim()" class="bg-bg border border-border/60 rounded-btn px-3 py-2 max-h-40 overflow-y-auto">
          <div class="text-caption text-textTertiary mb-1">👁 解析预览（公式自动渲染）</div>
          <MarkdownView :content="draft.analysis" />
        </div>
        <!-- AI 审核 -->
        <div class="flex gap-2 items-center flex-wrap">
          <button class="text-caption px-3 py-1.5 rounded-btn border border-warning/50 text-warning whitespace-nowrap disabled:opacity-40"
                  :disabled="reviewing" @click="aiReview">{{ reviewing ? '审核中…' : '🤖 AI 审核' }}</button>
          <button class="text-caption px-3 py-1.5 rounded-btn border border-primary/50 text-primary whitespace-nowrap disabled:opacity-40"
                  :disabled="fixing" @click="fixFormulas">{{ fixing ? '修正中…' : '🔧 一键修正公式' }}</button>
          <span class="text-caption text-textTertiary">检查答案与解析是否正确；修正未正常转化的公式符号（如 \iint → ∬）</span>
        </div>
        <div v-if="review" class="rounded-btn border px-3 py-2.5"
             :class="review.correct ? 'border-success/40 bg-success/5' : 'border-warning/60 bg-warning/5'">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-sm font-medium" :class="review.correct ? 'text-success' : 'text-warning'">
              {{ review.correct ? '✅ 审核通过：答案与解析正确' : '⚠️ 发现疑似问题' }}
            </span>
          </div>
          <div v-if="review.issue" class="text-caption text-textSecondary mb-2">{{ review.issue }}</div>
          <div v-if="!review.correct && (review.suggested_answer || review.suggested_analysis)" class="flex items-center gap-2">
            <button class="text-caption px-3 py-1 rounded-btn bg-primary text-white disabled:opacity-40" @click="applyReview">✅ 应用修正</button>
            <span class="text-caption text-textTertiary">一键填入修正后的答案/解析（可再编辑）</span>
          </div>
        </div>
        <div class="flex gap-2">
          <select v-model="draft.subject" class="border border-border rounded-btn p-2 text-body">
            <option v-for="s in ['语文','数学','英语','物理','化学','生物','政治','历史','地理','专业课','其他']" :key="s">{{ s }}</option>
          </select>
          <select v-model="draft.error_type" class="border border-border rounded-btn p-2 text-body">
            <option v-for="e in ['概念不清','审题失误','粗心','计算错误','方法不当','超纲','其他']" :key="e">{{ e }}</option>
          </select>
          <input v-if="draft.error_type === '其他'" v-model="customError" aria-label="具体错因说明" placeholder="输入具体错因说明…"
                 class="border border-border rounded-btn p-2 text-body outline-none focus:border-primary" />
          <select v-model="draft.difficulty" class="border border-border rounded-btn p-2 text-body">
            <option v-for="d in ['易','中','难']" :key="d">{{ d }}</option>
          </select>
          <button class="ml-auto bg-primary text-white rounded-btn px-4 py-1.5 text-sm" @click="save">保存</button>
        </div>
      </div>
    </div>

    <div class="mt-2 flex items-center gap-3 flex-wrap">
      <button class="text-caption border border-primary/40 text-primary rounded-btn px-3 py-1 hover:bg-primary/5" @click.stop="kpOpen = true">📖 知识点学习</button>
      <button v-if="isGeometric(q.question_text)" class="text-caption border border-border text-textSecondary rounded-btn px-3 py-1 hover:border-borderStrong" @click.stop="ggbOpen = true">📐 几何画板</button>
      <span class="text-caption text-primary cursor-pointer">{{ expanded ? '收起' : '查看答案与解析' }}</span>
    </div>

    <!-- 知识点系统学习弹窗 -->
    <KnowledgeModal :open="kpOpen" :question-text="q.question_text" :knowledge-point="q.knowledge_point || ''" @close="kpOpen = false" />
    <!-- 几何画板 -->
    <GeoGebraPanel :open="ggbOpen" :question-text="q.question_text" :subject="q.subject" @close="ggbOpen = false" />
  </div>
</template>
