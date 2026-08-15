<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { questionApi, aiApi } from '../api'
import { useNotebookStore } from '../stores/notebook'
import MarkdownView from '../components/MarkdownView.vue'
import FormulaToolbar from '../components/FormulaToolbar.vue'

const router = useRouter()
const store = useNotebookStore()

const form = ref({
  notebook_id: null as number | null,
  question_text: '',
  answer: '',
  analysis: '',
  subject: '其他',
  knowledge_point: '',
  error_type: '其他',
  error_detail: '',
  difficulty: '中',
  image_path: '' as string,
  image_url: '' as string,
})
const imgInput = ref<HTMLInputElement | null>(null)

function appendFormula(field: 'question_text' | 'answer' | 'analysis', formula: string) {
  const current = form.value[field]
  form.value[field] = `${current}${current && !current.endsWith('\n') ? '\n' : ''}${formula}`
}

async function pickImage(e: Event) {
  const el = e.target as HTMLInputElement
  const file = el.files?.[0]
  el.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) { alert('仅支持图片'); return }
  if (file.size > 4 * 1024 * 1024) { alert('图片超过 4MB'); return }
  const fd = new FormData()
  fd.append('file', file)
  try {
    const up = await questionApi.uploadQuestionImage(file)
    form.value.image_path = up.image_path
    form.value.image_url = up.url
  } catch { alert('图片上传失败') }
}
const aiSuggestion = ref<Record<string, string> | null>(null)
const classifying = ref(false)
const genAnswering = ref(false)
const answerStream = ref('')  // 答案流式实时输出
const subjects = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理', '专业课', '其他']
const errorTypes = ['概念不清', '审题失误', '粗心', '计算错误', '方法不当', '超纲', '其他']

onMounted(() => { store.load() })

async function aiGenerateAnswer() {
  if (!form.value.question_text.trim()) { alert('请先填写题干'); return }
  genAnswering.value = true
  answerStream.value = ''
  try {
    // 流式生成：答案 + 解析实时输出，完成后拆分填入
    const resp = await fetch('/api/ai/answer-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_text: form.value.question_text, subject: form.value.subject }),
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
        answerStream.value = full
      }
    }
    // 拆分答案/解析
    const ansM = full.match(/答案\s*[:：]\s*/)
    const anlM = full.match(/解析\s*[:：]\s*/)
    if (ansM && anlM && (anlM.index ?? 0) > (ansM.index ?? 0)) {
      const aEnd = (ansM.index ?? 0) + ansM[0].length
      form.value.answer = full.slice(aEnd, anlM.index).trim()
      form.value.analysis = full.slice((anlM.index ?? 0) + anlM[0].length).trim()
    } else {
      form.value.analysis = full
    }
  } catch {
    answerStream.value = '⚠️ AI 生成失败，请重试'
  } finally { genAnswering.value = false }
}

// 解析 AI 生成（流式实时输出）
const genAnalysis = ref(false)
const analysisStream = ref('')
async function aiGenerateAnalysis() {
  if (!form.value.question_text.trim()) { alert('请先填写题干'); return }
  genAnalysis.value = true
  analysisStream.value = ''
  try {
    const resp = await fetch('/api/ai/answer-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_text: form.value.question_text, subject: form.value.subject }),
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
        analysisStream.value = full
      }
    }
    // 提取解析部分（去掉“答案：”前缀段）
    const aIdx = full.indexOf('解析：')
    form.value.analysis = aIdx > 0 ? full.slice(aIdx + 3).trim() : full
  } catch {
    analysisStream.value = '⚠️ AI 生成失败，请重试'
  } finally {
    genAnalysis.value = false
  }
}

async function autoClassify() {
  if (!form.value.question_text.trim()) return
  classifying.value = true
  try {
    const q = await questionApi.classifyPreview(form.value.question_text)
    aiSuggestion.value = {
      subject: q.subject, knowledge_point: q.knowledge_point,
      error_type: q.error_type, difficulty: q.difficulty,
    }
    form.value.subject = q.subject
    form.value.knowledge_point = q.knowledge_point
    form.value.error_type = q.error_type
    form.value.error_detail = q.error_detail || ''
    form.value.difficulty = q.difficulty
  } catch {
    alert('AI 自动归类失败，请稍后重试或手动填写')
  } finally { classifying.value = false }
}

async function save() {
  if (!form.value.question_text.trim()) { alert('请填写题干'); return }
  try {
    await questionApi.create(form.value, false)
    alert('保存成功')
    router.push('/questions')
  } catch {
    // 请求层已展示服务端错误；留在当前表单以便用户修改后重试。
  }
}
</script>

<template>
  <div class="max-w-3xl mx-auto px-6 py-8">
    <h1 class="text-h1 mb-6">文本录入</h1>
    <div class="bg-card border border-border rounded-card p-4 sm:p-6 space-y-4">
      <div>
        <label class="text-caption text-textSecondary block mb-1">题干 *
          <span class="ml-2 text-caption text-textTertiary">立体几何等带图题可添加配图</span>
        </label>
        <textarea v-model="form.question_text" rows="4" placeholder="输入或粘贴题目内容…"
                  class="w-full border border-border rounded-btn p-3 text-body focus:border-primary outline-none" />
        <FormulaToolbar class="mt-2" @insert="appendFormula('question_text', $event)" />
        <div class="mt-2 flex items-center gap-3">
          <button class="text-caption border border-border rounded-btn px-3 py-1.5 text-textSecondary hover:border-borderStrong"
                  @click="imgInput?.click()">📷 添加配图</button>
          <input ref="imgInput" type="file" accept="image/*" class="hidden" @change="pickImage" />
          <img v-if="form.image_url" :src="form.image_url" class="max-h-40 rounded-lg border border-border" />
          <button v-if="form.image_url" class="text-caption text-error" @click="form.image_path = ''; form.image_url = ''">✕ 移除</button>
        </div>
        <div v-if="form.question_text.trim()" class="mt-2 bg-bg border border-border/60 rounded-btn px-3 py-2 max-h-48 overflow-y-auto">
          <div class="text-caption text-textTertiary mb-1">👁 预览（公式自动渲染）</div>
          <MarkdownView :content="form.question_text" />
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="text-caption text-textSecondary block mb-1">答案
            <button class="ml-2 text-caption text-primary disabled:opacity-40" :disabled="genAnswering" @click="aiGenerateAnswer">
              {{ genAnswering ? 'AI 生成中…' : '✨ AI 生成' }}
            </button>
          </label>
          <textarea v-model="form.answer" rows="2" placeholder="手动输入或 AI 生成" class="w-full border border-border rounded-btn p-3 text-body focus:border-primary outline-none" />
          <FormulaToolbar class="mt-2" @insert="appendFormula('answer', $event)" />
          <div v-if="answerStream" class="mt-2 bg-bg border border-primary/30 rounded-btn px-3 py-2 max-h-40 overflow-y-auto">
            <div class="text-caption text-primary mb-1">🤖 AI 生成中…（实时输出）</div>
            <MarkdownView :content="answerStream" />
          </div>
          <div v-if="form.answer.trim()" class="mt-2 bg-bg border border-border/60 rounded-btn px-3 py-2 max-h-48 overflow-y-auto">
            <div class="text-caption text-textTertiary mb-1">👁 预览（公式自动渲染）</div>
            <MarkdownView :content="form.answer" />
          </div>
        </div>
        <div>
          <label class="text-caption text-textSecondary block mb-1">解析
            <button class="ml-2 text-caption text-primary disabled:opacity-40" :disabled="genAnalysis" @click="aiGenerateAnalysis">
              {{ genAnalysis ? 'AI 生成中…' : '✨ AI 生成' }}
            </button>
          </label>
          <textarea v-model="form.analysis" rows="2" placeholder="手动输入或 AI 生成" class="w-full border border-border rounded-btn p-3 text-body focus:border-primary outline-none" />
          <FormulaToolbar class="mt-2" @insert="appendFormula('analysis', $event)" />
          <div v-if="analysisStream" class="mt-2 bg-bg border border-primary/30 rounded-btn px-3 py-2 max-h-40 overflow-y-auto">
            <div class="text-caption text-primary mb-1">🤖 AI 生成中…（实时输出）</div>
            <MarkdownView :content="analysisStream" />
          </div>
          <div v-if="form.analysis.trim()" class="mt-2 bg-bg border border-border/60 rounded-btn px-3 py-2 max-h-48 overflow-y-auto">
            <div class="text-caption text-textTertiary mb-1">👁 预览（公式自动渲染）</div>
            <MarkdownView :content="form.analysis" />
          </div>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <button class="border border-primary/40 text-primary rounded-btn px-4 py-1.5 text-sm disabled:opacity-40"
                :disabled="classifying || !form.question_text.trim()" @click="autoClassify">
          {{ classifying ? 'AI 识别中…' : '✨ AI 自动归类' }}
        </button>
        <div v-if="aiSuggestion" class="flex gap-2 flex-wrap">
          <span class="text-caption px-2 py-0.5 rounded-tag bg-primary/10 text-primary">{{ aiSuggestion.subject }}</span>
          <span class="text-caption px-2 py-0.5 rounded-tag bg-success/10 text-success">{{ aiSuggestion.knowledge_point }}</span>
          <span class="text-caption px-2 py-0.5 rounded-tag bg-warning/10 text-warning">{{ aiSuggestion.error_type }}</span>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="text-caption text-textSecondary block mb-1">学科</label>
          <select v-model="form.subject" class="w-full border border-border rounded-btn p-2.5 text-body">
            <option v-for="s in subjects" :key="s">{{ s }}</option>
          </select>
        </div>
        <div>
          <label class="text-caption text-textSecondary block mb-1">知识点</label>
          <input v-model="form.knowledge_point" placeholder="如：函数单调性"
                 class="w-full border border-border rounded-btn p-2.5 text-body focus:border-primary outline-none" />
        </div>
        <div>
          <label class="text-caption text-textSecondary block mb-1">错因</label>
          <select v-model="form.error_type" class="w-full border border-border rounded-btn p-2.5 text-body">
            <option v-for="e in errorTypes" :key="e">{{ e }}</option>
          </select>
        </div>
        <div v-if="form.error_type === '其他'">
          <label class="text-caption text-textSecondary block mb-1">具体错因</label>
          <input v-model="form.error_detail" placeholder="如：把定义域条件漏掉" class="w-full border border-border rounded-btn p-2.5 text-body focus:border-primary outline-none" />
        </div>
        <div>
          <label class="text-caption text-textSecondary block mb-1">难度</label>
          <div class="flex gap-2">
            <button v-for="d in ['易', '中', '难']" :key="d" class="flex-1 border rounded-btn py-2 text-sm"
                    :class="form.difficulty === d ? 'bg-primary text-white border-primary' : 'border-border text-textSecondary'"
                    @click="form.difficulty = d">{{ d }}</button>
          </div>
        </div>
        <div class="text-caption text-textTertiary">学科已作为错题本分类（与错题本页一致）</div>
      </div>

      <button class="w-full bg-primary text-white rounded-btn py-2.5 font-medium disabled:opacity-40"
              :disabled="!form.question_text.trim()" @click="save">保存错题</button>
    </div>
  </div>
</template>
