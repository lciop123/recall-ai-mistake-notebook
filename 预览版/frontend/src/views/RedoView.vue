<script setup lang="ts">
import { onActivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { questionApi, dashboardApi, notebookApi, chatApi, planApi, redoApi } from '../api'
import { toast } from '../api/request'
import MarkdownView from '../components/MarkdownView.vue'
import FormulaToolbar from '../components/FormulaToolbar.vue'
import type { Question } from '../types'

const route = useRoute()
const router = useRouter()

const stage = ref<'pick' | 'doing' | 'done'>('pick')
const dailyMode = ref(false)
const planUpdating = ref(false)
const stepMode = ref(false)
const steps = ref<string[]>([''])
const subjects = ref<{ name: string; count: number }[]>([])
const subject = ref('')
const knowledgePoint = ref('')
const reviewDate = ref('')
const questions = ref<Question[]>([])
const current = ref(0)
const loadingList = ref(false)

// 题型（AI 判断）
const qtype = ref<'choice' | 'fill' | 'essay'>('fill')
const options = ref<string[]>([])
const judging = ref(false)

// 作答
const answer = ref('')
const answerImage = ref<string | null>(null)
const answerImagePath = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

// 批改
const grading = ref(false)
type GradeResult = { correct: boolean; score: number; feedback: string; first_error_step: string; next_hint: string }
const gradeResult = ref<GradeResult | null>(null)
const gradedResults = ref<Record<number, GradeResult>>({})
const doneCount = ref(0)
const correctCount = ref(0)

onMounted(async () => {
  await loadSubjects()
  await startFromRoute()
})
onActivated(startFromRoute)
watch(() => route.fullPath, () => { startFromRoute() })

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
  dailyMode.value = false
  loadingList.value = true
  try {
    const res = await questionApi.list({ subject: subject.value || undefined, page: 1, page_size: 100, sort_by: 'created_at', order: 'desc' })
    questions.value = res.items
    if (!questions.value.length) { toast('该范围暂无错题', 'error'); return }
    current.value = 0
    stage.value = 'doing'
    await loadQuestion(0)
  } finally { loadingList.value = false }
}

async function startDaily() {
  if (loadingList.value) return
  dailyMode.value = true
  loadingList.value = true
  try {
    const res = await planApi.daily(subject.value || undefined, undefined, reviewDate.value || undefined, knowledgePoint.value || undefined)
    questions.value = res.due
    if (!questions.value.length) {
      toast('今天没有待复习错题', 'error')
      router.replace({ path: '/redo' })
      dailyMode.value = false
      return
    }
    current.value = 0
    doneCount.value = 0
    correctCount.value = 0
    gradedResults.value = {}
    stage.value = 'doing'
    await loadQuestion(0)
  } finally { loadingList.value = false }
}

async function startFromRoute() {
  if (route.query.mode !== 'daily' || stage.value !== 'pick' || loadingList.value) return
  subject.value = typeof route.query.subject === 'string' ? route.query.subject : ''
  knowledgePoint.value = typeof route.query.knowledge_point === 'string' ? route.query.knowledge_point : ''
  reviewDate.value = typeof route.query.date === 'string' ? route.query.date : ''
  await startDaily()
}

async function loadQuestion(idx: number) {
  current.value = idx
  answer.value = ''
  answerImage.value = null
  answerImagePath.value = null
  gradeResult.value = gradedResults.value[questions.value[idx].id] || null
  stepMode.value = false
  steps.value = ['']
  judging.value = true
  options.value = []
  qtype.value = 'fill'
  try {
    const t = await redoApi.judgeType(questions.value[idx].id)
    qtype.value = t.type
    options.value = t.options || []
  } catch {
    qtype.value = 'fill'
  } finally { judging.value = false }
}

function onPickImage(e: Event) {
  const el = e.target as HTMLInputElement
  const file = el.files?.[0]
  if (file) acceptImage(file)
  el.value = ''
}
function acceptImage(file: File) {
  if (!file.type.startsWith('image/')) { toast('仅支持图片', 'error'); return }
  if (file.size > 4 * 1024 * 1024) { toast('图片超过 4MB', 'error'); return }
  const reader = new FileReader()
  reader.onload = () => { answerImage.value = reader.result as string }
  reader.readAsDataURL(file)
}
function onDrop(e: DragEvent) {
  dragOver.value = false
  const file = Array.from(e.dataTransfer?.files || []).find(f => f.type.startsWith('image/'))
  if (file) acceptImage(file)
}

function appendFormula(formula: string) {
  if (stepMode.value) {
    const index = steps.value.length - 1
    steps.value[index] = `${steps.value[index]}${steps.value[index] && !steps.value[index].endsWith('\n') ? '\n' : ''}${formula}`
  } else {
    answer.value = `${answer.value}${answer.value && !answer.value.endsWith('\n') ? '\n' : ''}${formula}`
  }
}

function addStep() { steps.value.push('') }
function removeStep(index: number) { if (steps.value.length > 1) steps.value.splice(index, 1) }

async function submit() {
  if (grading.value || gradeResult.value) return
  const stepAnswer = steps.value.some(step => step.trim())
  if ((qtype.value === 'fill' || (qtype.value === 'choice' && !options.value.length)) && !answer.value.trim()) { toast('请先填写答案', 'error'); return }
  if (qtype.value === 'choice' && options.value.length && !answer.value.trim()) { toast('请选择一个答案', 'error'); return }
  if (qtype.value === 'essay' && !answer.value.trim() && !stepAnswer && !answerImage.value) { toast('请作答或上传手写图片', 'error'); return }
  grading.value = true
  try {
    // 大题图片：先上传拿 image_path
    let imagePath: string | undefined
    if (answerImage.value) {
      const blob = await (await fetch(answerImage.value)).blob()
      const up = await chatApi.uploadImage(new File([blob], 'answer.png', { type: blob.type || 'image/png' }))
      imagePath = up.image_path
    }
    const q = questions.value[current.value]
    const submitted = stepMode.value ? steps.value.filter(Boolean).map((step, index) => `步骤 ${index + 1}：${step}`).join('\n') : answer.value.trim()
    const r = await redoApi.grade(q.id, submitted, imagePath, qtype.value, q.subject, dailyMode.value ? 'daily' : 'redo')
    gradeResult.value = r
    gradedResults.value[q.id] = r
    doneCount.value++
    if (r.correct) correctCount.value++
  } catch {
    toast('批改失败，请重试', 'error')
  } finally { grading.value = false }
}

function next() {
  if (current.value + 1 < questions.value.length) {
    loadQuestion(current.value + 1)
  } else {
    stage.value = 'done'
  }
}

function exitToQuestions() { router.push('/questions') }

function reset() {
  if (!confirm('确定重置？将回到初始选择界面，当前进度会丢失')) return
  stage.value = 'pick'
  questions.value = []
  current.value = 0
  answer.value = ''
  answerImage.value = null
  answerImagePath.value = null
  gradeResult.value = null
  doneCount.value = 0
  correctCount.value = 0
  subject.value = ''
  knowledgePoint.value = ''
  reviewDate.value = ''
  gradedResults.value = {}
  dailyMode.value = false
  router.replace({ path: '/redo' })
  loadSubjects()
}
</script>

<template>
  <div class="max-w-3xl mx-auto px-4 sm:px-6 py-8">
    <div class="flex items-center mb-6 gap-2 flex-wrap">
      <h1 class="text-h1">{{ dailyMode ? '今日复习' : '错题重做' }}</h1>
      <button v-if="stage !== 'pick'" class="ml-auto border border-border rounded-btn px-4 py-1.5 text-caption text-textSecondary hover:border-borderStrong"
              @click="reset">↺ 重置</button>
    </div>

    <div v-if="dailyMode && stage === 'doing'" class="mb-4 flex items-center gap-2 flex-wrap rounded-btn border border-primary/20 bg-primary/5 px-3 py-2 text-caption text-primary">
      <span class="font-medium">今日复习模式</span>
      <span class="text-textSecondary">{{ reviewDate ? `${reviewDate} · ` : '' }}{{ knowledgePoint ? `当前专项：${knowledgePoint} · ` : '' }}每题批改后会自动更新掌握度与下次复习日期</span>
    </div>

    <!-- 选择学科 -->
    <div v-if="stage === 'pick'" class="bg-card border border-border rounded-card p-6 space-y-5">
      <div>
        <label class="text-caption text-textSecondary block mb-2">选择学科（与错题本同步）</label>
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
      <button class="w-full bg-primary text-white rounded-btn py-2.5 font-medium disabled:opacity-40"
              :disabled="loadingList" @click="start">
        {{ loadingList ? '加载中…' : '开始重做' }}
      </button>
    </div>

    <!-- 逐题重做 -->
    <div v-if="stage === 'doing'">
      <div class="flex items-center mb-4">
        <span class="text-caption text-textSecondary">第 {{ current + 1 }} / {{ questions.length }} 题</span>
        <span class="ml-auto text-caption" :class="qtype === 'choice' ? 'text-primary' : qtype === 'essay' ? 'text-warning' : 'text-success'">
          {{ judging ? 'AI 判断题型中…' : qtype === 'choice' ? '📝 选择题' : qtype === 'essay' ? '✍️ 大题（可拍照作答）' : '📄 填空题' }}
        </span>
      </div>
      <div class="bg-card border border-border rounded-card p-6">
        <div class="border-l-[3px] border-question pl-3 py-1 mb-4">
          <MarkdownView :content="questions[current].question_text" />
          <img v-if="questions[current].image_url" :src="questions[current].image_url || undefined" class="mt-2 max-h-64 rounded-lg border border-border/60" />
        </div>

        <!-- 选择题 -->
        <div v-if="qtype === 'choice' && options.length" class="space-y-2 mb-4">
          <button v-for="opt in options" :key="opt"
                  class="w-full text-left border rounded-btn px-4 py-2.5 text-body transition"
                  :class="answer === opt ? 'border-primary bg-primary/5 text-primary' : 'border-border hover:border-borderStrong'"
                  @click="answer = opt">
            <MarkdownView :content="opt" />
          </button>
        </div>

        <!-- 填空题，以及 AI 未返回选项的选择题降级为文本输入 -->
        <textarea v-if="qtype === 'fill' || (qtype === 'choice' && !options.length)" v-model="answer" rows="2" placeholder="输入你的答案…"
                  class="w-full border border-border rounded-btn p-3 text-body focus:border-primary outline-none mb-4" />

        <!-- 大题：文本 + 拍照/拖拽上传 -->
        <div v-if="qtype === 'essay'">
          <div class="mb-2 flex items-center gap-2">
            <button type="button" class="text-caption border rounded-btn px-3 py-1" :class="stepMode ? 'border-primary text-primary bg-primary/5' : 'border-border text-textSecondary'" @click="stepMode = !stepMode">分步骤作答</button>
            <span class="text-caption text-textTertiary">可输入过程或上传手写作答</span>
          </div>
          <template v-if="stepMode">
            <div v-for="(_, index) in steps" :key="index" class="mb-2 flex gap-2">
              <textarea v-model="steps[index]" rows="2" :aria-label="`第 ${index + 1} 步作答`" :placeholder="`步骤 ${index + 1}`" class="flex-1 border border-border rounded-btn p-3 text-body focus:border-primary outline-none" />
              <button type="button" class="text-caption text-error px-2" :disabled="steps.length === 1" @click="removeStep(index)">删除</button>
            </div>
            <button type="button" class="text-caption text-primary mb-2" @click="addStep">+ 添加步骤</button>
          </template>
          <textarea v-else v-model="answer" rows="4" placeholder="输入你的解答过程…（也可拍照/拖拽上传手写作答）"
                    class="w-full border border-border rounded-btn p-3 text-body focus:border-primary outline-none mb-2" />
          <FormulaToolbar class="mb-3" @insert="appendFormula" />
          <div class="relative border-2 border-dashed rounded-btn p-6 text-center cursor-pointer transition"
               :class="dragOver ? 'border-primary bg-primary/5' : 'border-border'"
               @dragover.prevent="dragOver = true" @dragleave.prevent="dragOver = false" @drop.prevent="onDrop"
               @click="fileInput?.click()">
            <div class="text-2xl mb-2">📷</div>
            <div class="text-caption text-textSecondary">拖拽手写图片到此处，或 <span class="text-primary">点击选择</span>（jpg/png ≤4MB）</div>
            <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onPickImage" />
            <div v-if="answerImage" class="mt-3 flex items-center justify-center gap-3">
              <img :src="answerImage" class="max-h-52 rounded-lg border border-border" />
              <button class="text-caption text-error" @click.stop="answerImage = null; answerImagePath = null">✕ 移除</button>
            </div>
          </div>
        </div>

        <!-- 批改结果：无论对错都展示考察知识点 / 答案 / 解析 -->
        <div v-if="gradeResult" class="mt-4 border rounded-card p-4"
             :class="gradeResult.correct ? 'border-success bg-[#F7FFF9]' : 'border-error bg-[#FFF7F6]'">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-lg">{{ gradeResult.correct ? '✅' : '❌' }}</span>
            <b :class="gradeResult.correct ? 'text-success' : 'text-error'">{{ gradeResult.correct ? '回答正确' : '回答错误' }}</b>
            <span class="ml-auto text-caption text-textSecondary">得分 {{ gradeResult.score }} 分</span>
          </div>
          <div class="mb-2 text-body">📌 <b>考察知识点：</b><span class="text-textSecondary">{{ questions[current].knowledge_point || '—' }}</span></div>
          <div class="text-caption text-textSecondary mb-1">答案与完整过程：</div>
          <div class="mb-2 border-l-[3px] border-border pl-3"><MarkdownView :content="(questions[current].answer || '—') + (questions[current].analysis ? '\n\n' + questions[current].analysis : '')" /></div>
          <div class="text-caption text-textSecondary mb-1">AI 批改反馈：</div>
          <div class="text-body text-textSecondary border-l-[3px] border-analysis bg-[#F9FFFB] rounded-r-btn px-3 py-2">{{ gradeResult.feedback }}</div>
          <div v-if="gradeResult.first_error_step" class="mt-2 text-body text-error"><b>首处错误：</b>{{ gradeResult.first_error_step }}</div>
          <div class="mt-1 text-body text-primary"><b>下一步提示：</b>{{ gradeResult.next_hint }}</div>
        </div>

        <div class="flex justify-between mt-4">
          <button class="border border-border rounded-btn px-5 py-2 text-sm text-textSecondary disabled:opacity-30"
                  :disabled="current === 0 || grading" @click="loadQuestion(current - 1)">上一题</button>
          <div class="flex gap-2">
            <button v-if="!gradeResult" class="bg-primary text-white rounded-btn px-6 py-2 text-sm disabled:opacity-40"
                    :disabled="grading || judging || planUpdating" @click="submit">
              {{ grading ? 'AI 严格批改中…（检查过程与逻辑）' : planUpdating ? '正在更新复习计划…' : '提交批改' }}
            </button>
            <button v-else class="bg-success text-white rounded-btn px-6 py-2 text-sm" @click="next">
              {{ current + 1 < questions.length ? '下一题' : '完成' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 完成 -->
    <div v-if="stage === 'done'" class="bg-card border border-border rounded-card p-10 text-center">
      <div class="text-5xl mb-4">{{ correctCount === doneCount && doneCount > 0 ? '🏆' : '📚' }}</div>
      <div class="text-h2 mb-2">重做完成！</div>
      <div class="text-body text-textSecondary mb-1">共重做 {{ doneCount }} 题，答对 {{ correctCount }} 题</div>
      <div class="text-caption text-textTertiary mb-6">正确率 {{ doneCount ? Math.round(correctCount / doneCount * 100) : 0 }}%</div>
      <div class="flex gap-3 justify-center">
        <button class="bg-primary text-white rounded-btn px-6 py-2 text-sm" @click="reset">再练一次</button>
        <button class="border border-border rounded-btn px-6 py-2 text-sm text-textSecondary" @click="exitToQuestions">去错题本看看</button>
      </div>
    </div>
  </div>
</template>
