<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { reviewApi, dashboardApi, notebookApi } from '../api'
import { toast } from '../api/request'
import { useNotebookStore } from '../stores/notebook'
import MarkdownView from '../components/MarkdownView.vue'
import FormulaToolbar from '../components/FormulaToolbar.vue'
import type { VariantQuestion, ReviewResult } from '../types'

const router = useRouter()
const store = useNotebookStore()
const stage = ref<'pick' | 'answer' | 'result'>('pick')
const count = ref(5)
const subject = ref('')
const mode = ref<'variant' | 'exam'>('variant')
const examDate = ref(new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10))
const examMinutes = ref(0)
// 学科列表：与错题本页侧栏同源（有题学科 + 空学科错题本），保持同步
const subjects = ref<{ name: string; count: number }[]>([])
const reviewId = ref('')
const questions = ref<VariantQuestion[]>([])
const answers = ref<Record<number, string>>({})
const current = ref(0)
const generating = ref(false)
const submitting = ref(false)
const result = ref<{ total: number; correct: number; score: number; results: ReviewResult[] } | null>(null)
const source = ref('')

function appendFormula(formula: string) {
  const id = questions.value[current.value]?.id
  if (id === undefined) return
  const currentAnswer = answers.value[id] || ''
  answers.value[id] = `${currentAnswer}${currentAnswer && !currentAnswer.endsWith('\n') ? '\n' : ''}${formula}`
}

onMounted(async () => { store.load(); await loadSubjects() })

async function loadSubjects() {
  try {
    const [d, nbs] = await Promise.all([dashboardApi.distributions(), notebookApi.list()])
    const rows = (d.subjects || []).map(s => ({ name: s.name, count: s.count }))
    const names = new Set(rows.map(r => r.name))
    for (const nb of nbs) {
      const nm = nb.name.replace(/错题本$/, '')
      if (!names.has(nm) && nm) { rows.push({ name: nm, count: 0 }); names.add(nm) }
    }
    rows.sort((a, b) => b.count - a.count)
    subjects.value = rows
  } catch { subjects.value = [] }
}

async function start() {
  generating.value = true
  try {
    if (mode.value === 'exam') {
      const res = await reviewApi.generateExam({ exam_date: examDate.value, subject: subject.value || null, count: count.value })
      examMinutes.value = res.recommended_minutes
      reviewId.value = res.review_id
      questions.value = res.questions
      source.value = res.source
    } else {
      const res = await reviewApi.generate({ notebook_id: null, subject: subject.value || null, count: count.value })
      examMinutes.value = 0
      reviewId.value = res.review_id
      questions.value = res.questions
      source.value = res.source
    }
    answers.value = {}
    addedQuestions.value = new Set()
    current.value = 0
    stage.value = 'answer'
  } finally { generating.value = false }
}

function reset() {
  if (!confirm('确定重置？将回到初始选择界面，当前进度会丢失')) return
  stage.value = 'pick'
  questions.value = []
  answers.value = {}
  current.value = 0
  reviewId.value = ''
  result.value = null
  addedQuestions.value = new Set()
  subject.value = ''
  mode.value = 'variant'
  examMinutes.value = 0
}

// 变体题加入错题本
const addingToBook = ref(false)
const addedQuestions = ref<Set<number>>(new Set())
async function addToBook() {
  if (addingToBook.value || !reviewId.value) return
  const q = questions.value[current.value]
  if (addedQuestions.value.has(q.id)) { toast('该题已加入错题本', 'error'); return }
  addingToBook.value = true
  try {
    await reviewApi.addQuestion(reviewId.value, q.id)
    addedQuestions.value.add(q.id)
    toast('✅ 已加入错题本')
  } catch {
    toast('加入失败，请重试', 'error')
  } finally { addingToBook.value = false }
}

async function submit() {
  if (submitting.value) return
  if (!confirm('确定提交？未作答的题将按答错计')) return
  submitting.value = true
  try {
    const res = await reviewApi.submit(reviewId.value, questions.value.map(q => ({ question_id: q.id, answer: answers.value[q.id] || '' })))
    result.value = res
    stage.value = 'result'
  } catch (e) {
    // 会话失效（后端重启等）→ 提示并回到选题页
    if (String((e as Error)?.message || '').includes('复习会话')) {
      stage.value = 'pick'
    }
  } finally {
    submitting.value = false
  }
}

async function quickComplete() {
  // 批改提交（SM-2 更新由后端在 submit 中统一完成）
  await submit()
}
</script>

<template>
  <div class="max-w-3xl mx-auto px-6 py-8">
    <div class="flex items-center mb-6">
      <h1 class="text-h1">举一反三</h1>
      <button v-if="stage !== 'pick'" class="ml-auto border border-border rounded-btn px-4 py-1.5 text-caption text-textSecondary hover:border-borderStrong"
              @click="reset">↺ 重置</button>
    </div>

    <!-- 步骤条 -->
    <div class="flex items-center gap-2 mb-6 text-caption">
      <span :class="stage === 'pick' ? 'text-primary font-medium' : 'text-success'">① 选题范围</span>
      <span class="w-8 h-px bg-border" />
      <span :class="stage === 'answer' ? 'text-primary font-medium' : stage === 'result' ? 'text-success' : 'text-textTertiary'">② 逐题作答</span>
      <span class="w-8 h-px bg-border" />
      <span :class="stage === 'result' ? 'text-primary font-medium' : 'text-textTertiary'">③ 批改结果</span>
    </div>

    <!-- 阶段 1 -->
    <div v-if="stage === 'pick'" class="bg-card border border-border rounded-card p-6 space-y-5">
      <div>
        <label class="text-caption text-textSecondary block mb-2">练习模式</label>
        <div class="flex gap-2">
          <button class="px-4 py-2 rounded-btn border text-body" :class="mode === 'variant' ? 'bg-primary text-white border-primary' : 'border-border text-textSecondary'" @click="mode = 'variant'">日常变式</button>
          <button class="px-4 py-2 rounded-btn border text-body" :class="mode === 'exam' ? 'bg-primary text-white border-primary' : 'border-border text-textSecondary'" @click="mode = 'exam'">考前专题卷</button>
        </div>
      </div>
      <div v-if="mode === 'exam'">
        <label class="text-caption text-textSecondary block mb-2" for="exam-date">考试日期</label>
        <input id="exam-date" v-model="examDate" type="date" :min="new Date().toISOString().slice(0, 10)" class="border border-border rounded-btn px-3 py-2 text-body" />
        <p class="mt-1 text-caption text-textTertiary">按逾期、掌握度和历史错误次数优先组卷。</p>
      </div>
      <div>
        <label class="text-caption text-textSecondary block mb-2">学科（与错题本同步）</label>
        <div class="flex gap-2 flex-wrap">
          <button class="px-4 py-1.5 rounded-tag border text-caption"
                  :class="subject === '' ? 'bg-primary border-primary text-white' : 'bg-white border-border text-textSecondary'"
                  @click="subject = ''">全部学科</button>
          <button v-for="s in subjects" :key="s.name" class="px-4 py-1.5 rounded-tag border text-caption"
                  :class="subject === s.name ? 'bg-primary border-primary text-white' : 'bg-white border-border text-textSecondary'"
                  @click="subject = s.name">{{ s.name }}<span v-if="s.count > 0" class="opacity-70"> ({{ s.count }})</span></button>
        </div>
        <div v-if="subjects.length === 0" class="text-caption text-textTertiary mt-1">暂无错题，先去收录吧</div>
      </div>
      <div>
        <label class="text-caption text-textSecondary block mb-2">题数</label>
        <div class="flex gap-2">
          <button v-for="n in [5, 10, 20]" :key="n" class="px-5 py-2 rounded-btn border text-body"
                  :class="count === n ? 'bg-primary text-white border-primary' : 'bg-white border-border text-textSecondary'"
                  @click="count = n">{{ n }} 题</button>
        </div>
      </div>
      <button class="w-full bg-primary text-white rounded-btn py-2.5 font-medium disabled:opacity-40"
              :disabled="generating" @click="start">
        {{ generating ? 'AI 正在出题…（举一反三生成+审核，约需 30-60 秒）' : '开始出题' }}
      </button>
      <div v-if="generating" class="text-center py-3">
        <div class="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2" />
        <div class="text-caption text-textSecondary">正在基于你的错题生成变体题…</div>
      </div>
    </div>

    <!-- 阶段 2：作答 -->
    <div v-if="stage === 'answer'">
      <div class="flex items-center justify-between mb-4">
        <span class="text-caption text-textSecondary">第 {{ current + 1 }} / {{ questions.length }} 题</span>
        <div class="w-40 h-1.5 bg-bg rounded-full overflow-hidden">
          <div class="h-full bg-primary transition-all" :style="{ width: ((current + 1) / questions.length * 100) + '%' }" />
        </div>
        <span class="text-caption" :class="source === 'ai' ? 'text-primary' : source === 'exam' ? 'text-warning' : 'text-warning'">{{ source === 'ai' ? 'AI 变体题' : source === 'exam' ? `考前专题卷 · 建议 ${examMinutes} 分钟` : '原题（AI 降级）' }}</span>
      </div>
      <div class="bg-card border border-border rounded-card p-6">
        <div class="border-l-[3px] border-question pl-3 py-1 mb-3">
          <MarkdownView :content="questions[current].question_text" />
          <img v-if="questions[current].image_url" :src="questions[current].image_url || undefined" class="mt-2 max-h-64 rounded-lg border border-border/60" />
        </div>
        <!-- 仅 AI 变式题可以加入错题本；原题专题卷不提供重复收藏。 -->
        <div class="flex items-center gap-2 mb-3">
          <template v-if="source === 'ai'">
            <button class="text-caption border border-primary/40 text-primary rounded-btn px-3 py-1 disabled:opacity-40"
                    :disabled="addingToBook" @click="addToBook">
              {{ addedQuestions.has(questions[current].id) ? '已加入错题本' : (addingToBook ? '加入中…' : '加入错题本') }}
            </button>
            <span class="text-caption text-textTertiary">举一反三题 · 可自由选择收藏</span>
          </template>
          <span v-else-if="source === 'exam'" class="text-caption text-textTertiary">专题卷完成后将回写掌握度与后续复习计划</span>
        </div>
        <div v-if="questions[current].options.length" class="space-y-2 mb-4">
          <button v-for="opt in questions[current].options" :key="opt"
                  class="w-full text-left border rounded-btn px-4 py-2.5 text-body transition"
                  :class="answers[questions[current].id] === opt ? 'border-primary bg-primary/5 text-primary' : 'border-border hover:border-borderStrong'"
                  @click="answers[questions[current].id] = opt">
            <MarkdownView :content="opt" />
          </button>
        </div>
        <textarea v-else v-model="answers[questions[current].id]" rows="3" placeholder="输入你的答案…"
                  class="w-full border border-border rounded-btn p-3 text-body focus:border-primary outline-none mb-2" />
        <FormulaToolbar v-if="!questions[current].options.length" class="mb-4" @insert="appendFormula" />
        <div class="flex justify-between">
          <button class="border border-border rounded-btn px-5 py-2 text-sm text-textSecondary disabled:opacity-30"
                  :disabled="current === 0" @click="current--">上一题</button>
          <button v-if="current < questions.length - 1" class="bg-primary text-white rounded-btn px-6 py-2 text-sm"
                  @click="current++">下一题</button>
          <button v-else class="bg-success text-white rounded-btn px-6 py-2 text-sm disabled:opacity-40"
                  :disabled="submitting" @click="quickComplete">
            {{ submitting ? 'AI 批改中…（按学科标准严格批改）' : '提交批改' }}
          </button>
        </div>
        <div v-if="submitting" class="flex items-center gap-2 mt-4 text-caption text-textSecondary">
          <div class="w-4 h-4 border-2 border-success border-t-transparent rounded-full animate-spin" />
          AI 正在批改你的答案，请稍候…
        </div>
      </div>
    </div>

    <!-- 阶段 3：结果 -->
    <div v-if="stage === 'result' && result">
      <div class="bg-card border border-border rounded-card p-6 flex items-center gap-8 mb-6">
        <div class="w-24 h-24 rounded-full flex items-center justify-center shrink-0"
             :style="{ background: `conic-gradient(#34C759 0 ${result.score}%, #F5F5F7 ${result.score}% 100%)` }">
          <div class="w-[72px] h-[72px] rounded-full bg-card flex flex-col items-center justify-center">
            <span class="text-xl font-semibold">{{ result.score }}%</span>
            <span class="text-caption text-textTertiary">正确率</span>
          </div>
        </div>
        <div class="space-y-1">
          <div><span class="text-2xl font-semibold">{{ result.correct }} / {{ result.total }}</span><span class="text-caption text-textSecondary ml-2">答对题数</span></div>
          <div class="text-caption text-textSecondary">{{ result.total - result.correct }} 题待加强 · SM-2 复习状态已更新</div>
        </div>
        <div class="ml-auto flex gap-3">
          <button class="border border-border rounded-btn px-4 py-2 text-sm text-textSecondary" @click="router.push('/')">返回首页</button>
          <button class="bg-primary text-white rounded-btn px-4 py-2 text-sm" @click="stage = 'pick'">再来一组</button>
        </div>
      </div>
      <h2 class="text-h2 mb-4">逐题详情</h2>
      <div v-for="(r, i) in result.results" :key="i" class="bg-card border rounded-card p-4 mb-3"
           :class="r.correct ? 'border-success' : 'border-error'">
        <div class="flex items-center gap-2 mb-2">
          <span class="w-5 h-5 rounded-full text-white text-xs flex items-center justify-center font-semibold"
                :class="r.correct ? 'bg-success' : 'bg-error'">{{ r.correct ? '✓' : '✗' }}</span>
          <b class="text-sm">第 {{ i + 1 }} 题</b>
          <span class="text-caption ml-auto" :class="r.correct ? 'text-success' : 'text-error'">
            你的答案：{{ answers[questions[i].id] || '（未作答）' }}
          </span>
        </div>
        <div class="mb-2"><MarkdownView :content="questions[i].question_text" /></div>
        <!-- 无论对错都展示：考察知识点 / 答案 / 解析 -->
        <div class="mb-2 text-body">📌 <b>考察知识点：</b><span class="text-textSecondary">{{ questions[i].knowledge_point || '—' }}</span></div>
        <div class="text-caption text-textSecondary mb-1">参考答案：</div>
        <div class="mb-2"><MarkdownView :content="r.answer || questions[i].answer || '—'" /></div>
        <div class="text-caption text-textSecondary mb-1">解析：</div>
        <div class="mb-2 border-l-[3px] border-border pl-3"><MarkdownView :content="questions[i].analysis || '（无）'" /></div>
        <div class="text-caption text-textSecondary mb-1">AI 批改反馈：</div>
        <div class="border-l-[3px] border-analysis bg-[#F9FFFB] rounded-r-btn px-3 py-2">
          <MarkdownView :content="r.analysis" />
        </div>
        <div v-if="r.first_error_step" class="mt-2 text-body text-error"><b>首处错误：</b>{{ r.first_error_step }}</div>
        <div class="mt-1 text-body text-primary"><b>下一步提示：</b>{{ r.next_hint }}</div>
      </div>
    </div>
  </div>
</template>
