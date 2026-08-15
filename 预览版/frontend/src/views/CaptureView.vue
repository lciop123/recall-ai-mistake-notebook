<script setup lang="ts">
import { onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { captureApi, chatApi } from '../api'
import { toast } from '../api/request'
import { useNotebookStore } from '../stores/notebook'
import MarkdownView from '../components/MarkdownView.vue'
import type { CaptureQuestion } from '../types'

const router = useRouter()
const store = useNotebookStore()

const phase = ref<'upload' | 'processing' | 'result' | 'failed'>('upload')
const progress = ref('')
const stage = ref<'prepare' | 'ocr' | 'split' | 'classify' | 'done' | 'failed'>('prepare')
const elapsedHint = ref('通常约 30-60 秒')
const taskId = ref('')
const questions = ref<CaptureQuestion[]>([])
const selected = ref<Set<number>>(new Set())
const errorMsg = ref('')
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let timer: number | null = null

// 编辑状态
const editing = ref<Set<number>>(new Set())
const editDraft = ref<Record<number, { question_text: string; subject: string; error_type: string; type: string; customError: string }>>({})
const SUBJECT_OPTS = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理', '专业课', '其他']
const ERROR_OPTS = ['概念不清', '审题失误', '粗心', '计算错误', '方法不当', '超纲', '其他']
const TYPE_OPTS = [
  { v: 'choice', l: '📝 选择题' },
  { v: 'fill', l: '📄 填空题' },
  { v: 'essay', l: '✍️ 大题' },
]

function applyEdit(q: CaptureQuestion) {
  const d = editDraft.value[q.temp_id]
  if (!d) return
  q.question_text = d.question_text.trim()
  q.subject = d.subject
  q.error_type = d.error_type
  q.error_detail = d.error_type === '其他' ? d.customError.trim() : ''
  q.type = d.type
}

function toggleEdit(q: CaptureQuestion) {
  const s = new Set(editing.value)
  if (s.has(q.temp_id)) {
    applyEdit(q)
    s.delete(q.temp_id)
  } else {
    s.add(q.temp_id)
    editDraft.value = { ...editDraft.value, [q.temp_id]: { question_text: q.question_text, subject: q.subject, error_type: q.error_type, type: q.type || 'fill', customError: q.error_detail || '' } }
  }
  editing.value = s
}

function saveEdit(q: CaptureQuestion) {
  const s = new Set(editing.value)
  s.delete(q.temp_id)
  editing.value = s
  applyEdit(q)
  toast('✅ 已更新题目，导入时将按修正后的内容保存')
}

async function chatAsk(q: CaptureQuestion) {
  try {
    const c = await chatApi.create()
    router.push({ path: '/chat', query: { conv: c.id, q: `请帮我分析这道题：\n\n${q.question_text}` } })
  } catch {
    errorMsg.value = '创建对话失败，请重试'
  }
}

onMounted(() => { store.load() })
// 视图被 KeepAlive 缓存时，离开识图页必须解除全局粘贴监听，避免在其他页面误触发上传。
onActivated(() => window.addEventListener('paste', onPaste))
onDeactivated(() => window.removeEventListener('paste', onPaste))
onUnmounted(() => { window.removeEventListener('paste', onPaste); if (timer) clearInterval(timer) })

async function upload(file: File) {
  if (!file.type.startsWith('image/')) { errorMsg.value = '仅支持 jpg/png/webp 图片'; phase.value = 'failed'; return }
  if (file.size > 2 * 1024 * 1024) { errorMsg.value = '图片超过 2MB，请压缩后上传'; phase.value = 'failed'; return }
  errorMsg.value = ''
  phase.value = 'processing'
  stage.value = 'prepare'
  progress.value = '正在上传图片…'
  elapsedHint.value = '上传完成后将并行识别题干与公式'
  try {
    const { task_id } = await captureApi.upload(file)
    taskId.value = task_id
    poll()
  } catch { phase.value = 'failed' }
}

function poll() {
  if (timer) clearInterval(timer)
  const t0 = Date.now()
  let failCount = 0
  timer = window.setInterval(async () => {
    try {
      const t = await captureApi.task(taskId.value)
      failCount = 0
      progress.value = t.progress || t.message
      stage.value = t.stage || (t.status === 'done' ? 'done' : 'ocr')
      elapsedHint.value = t.elapsed_hint || '通常约 30-60 秒'
      if (t.status === 'done') {
        if (timer) clearInterval(timer)
        questions.value = t.questions
        // 已存在于错题本的题默认不勾选
        selected.value = new Set(t.questions.filter(q => !q.exists).map(q => q.temp_id))
        phase.value = 'result'
      } else if (t.status === 'failed') {
        if (timer) clearInterval(timer)
        errorMsg.value = t.message
        phase.value = 'failed'
      }
    } catch {
      // 任务不存在/网络异常：连续 3 次失败则停止轮询（避免后端重启后无限转圈）
      failCount += 1
      if (failCount >= 3) {
        if (timer) clearInterval(timer)
        errorMsg.value = '识别任务不存在或已过期（可能服务刚重启），请重新上传'
        phase.value = 'failed'
      }
    }
    // 总超时保护：识别超过 150 秒仍未完成则停止（避免一直转圈）
    if (Date.now() - t0 > 150000) {
      if (timer) clearInterval(timer)
      errorMsg.value = '识别超时，请重试'
      phase.value = 'failed'
    }
  }, 2000)
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) upload(file)
}
function onPaste(e: ClipboardEvent) {
  const item = Array.from(e.clipboardData?.items || []).find(i => i.type.startsWith('image/'))
  const file = item?.getAsFile()
  if (file) upload(file)
}

function toggle(id: number) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
const importing = ref(false)
async function doImport() {
  if (selected.value.size === 0) { errorMsg.value = '请至少选择一道题'; return }
  if (importing.value) return
  importing.value = true
  // 即使用户忘记点击“保存编辑”，导入前也应用当前草稿，避免人工修正丢失。
  for (const q of questions.value) if (editing.value.has(q.temp_id)) applyEdit(q)
  try {
    const { imported, skipped } = await captureApi.importSelected(taskId.value, [...selected.value])
    toast(skipped ? `已导入 ${imported} 道，跳过 ${skipped} 道重复题` : `已导入 ${imported} 道错题`)
    router.push('/questions')
  } catch {
    errorMsg.value = '导入失败，请检查题目后重试'
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="max-w-3xl mx-auto px-6 py-8">
    <h1 class="text-h1 mb-6">识图录入</h1>

    <!-- 上传区 -->
    <div v-if="phase === 'upload'"
         class="border-2 border-dashed rounded-card p-10 text-center transition cursor-pointer"
         :class="dragOver ? 'border-primary bg-primary/5' : 'border-border'"
         @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="onDrop"
         @click="fileInput?.click()">
      <div class="text-4xl mb-3">📷</div>
      <div class="text-body mb-1"><b>拖拽图片到此处</b>，或 <span class="text-primary">点击选择</span></div>
      <div class="text-caption text-textSecondary">支持 jpg / png / webp，≤2MB · 也可直接 <b class="text-primary">Ctrl+V 粘贴</b> 截图</div>
      <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="e => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) upload(f) }" />
    </div>

    <!-- 识别中 -->
    <div v-if="phase === 'processing'" class="bg-card border border-border rounded-card p-8">
      <div class="flex items-center justify-center gap-3 mb-5">
        <div class="w-9 h-9 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <div>
          <div class="text-body font-medium">AI 正在处理题目</div>
          <div class="text-caption text-textSecondary">{{ elapsedHint }}</div>
        </div>
      </div>
      <div class="grid grid-cols-4 gap-2">
        <div v-for="step in [
          { key: 'prepare', label: '准备图片' },
          { key: 'ocr', label: '双模型识别' },
          { key: 'split', label: '拆分题目' },
          { key: 'classify', label: '归类去重' },
        ]" :key="step.key" class="rounded-btn border px-2 py-2 text-center text-caption transition-colors"
             :class="stage === step.key ? 'border-primary bg-primary/5 text-primary font-medium' : ['split', 'classify'].indexOf(stage) > ['prepare', 'ocr', 'split', 'classify'].indexOf(step.key) ? 'border-success/30 bg-success/5 text-success' : 'border-border text-textTertiary'">
          {{ step.label }}
        </div>
      </div>
      <div class="mt-4 rounded-btn bg-bg px-3 py-2 text-center text-caption text-textSecondary">{{ progress }}</div>
    </div>

    <!-- 失败 -->
    <div v-if="phase === 'failed'" class="bg-card border border-border rounded-card p-8 text-center">
      <div class="text-4xl mb-3">😕</div>
      <div class="text-body mb-4 text-error">{{ errorMsg }}</div>
      <div class="flex gap-3 justify-center">
        <button class="bg-primary text-white rounded-btn px-4 py-2 text-sm" @click="phase = 'upload'">重新上传</button>
        <router-link to="/input" class="border border-border rounded-btn px-4 py-2 text-sm text-textSecondary">改用文本录入</router-link>
      </div>
    </div>

    <!-- 结果勾选 -->
    <div v-if="phase === 'result'">
      <div class="flex items-center mb-4">
        <h2 class="text-h2">识别结果（{{ questions.length }} 道题）</h2>
        <button class="ml-auto text-caption text-primary" @click="selected = new Set(questions.map(q => q.temp_id))">全选</button>
      </div>
      <div v-for="q in questions" :key="q.temp_id" class="bg-card border border-border rounded-card p-4 mb-3"
           :class="selected.has(q.temp_id) ? '!border-primary/60' : ''">
        <label class="flex gap-3 cursor-pointer">
          <input type="checkbox" :checked="selected.has(q.temp_id)" :disabled="q.exists" class="mt-1 accent-[#007AFF]" @change="toggle(q.temp_id)" />
          <div class="flex-1">
            <div v-if="editing.has(q.temp_id)" class="mb-2" @click.stop>
              <textarea v-model="editDraft[q.temp_id].question_text" rows="5"
                        placeholder="请检查并修正识别出的题目…"
                        class="w-full border border-primary/40 rounded-btn p-3 text-body bg-white outline-none focus:border-primary" />
              <div v-if="editDraft[q.temp_id].question_text.trim()" class="mt-2 bg-white/70 border border-border/60 rounded-btn px-3 py-2 max-h-40 overflow-y-auto">
                <div class="text-caption text-textTertiary mb-1">题目预览</div>
                <MarkdownView :content="editDraft[q.temp_id].question_text" />
              </div>
            </div>
            <div v-else class="text-body mb-2"><MarkdownView :content="q.question_text" /></div>
            <div v-if="q.exists" class="text-caption text-warning mb-1">⚠️ 该题已在错题本中（已默认取消勾选，可跳过）</div>
            <div class="text-caption text-warning mb-2">请检查题目文字、公式和上下标；识别不准时可直接编辑。</div>
            <div class="flex gap-2 flex-wrap">
              <span class="text-caption px-2 py-0.5 rounded-tag bg-primary/10 text-primary">{{ q.subject }}</span>
              <span class="text-caption px-2 py-0.5 rounded-tag bg-bg text-textSecondary">{{ q.knowledge_point || '未分类' }}</span>
              <span class="text-caption px-2 py-0.5 rounded-tag bg-bg text-textSecondary">{{ q.error_type }}</span>
              <span class="text-caption px-2 py-0.5 rounded-tag bg-bg text-textSecondary">{{ TYPE_OPTS.find(t => t.v === q.type)?.l || '📄 填空题' }}</span>
            </div>
            <!-- 编辑区：用户可自行修改学科/题型/错因 -->
            <div v-if="editing.has(q.temp_id)" class="mt-3 bg-bg border border-border/60 rounded-btn p-3 space-y-2" @click.stop>
              <div class="grid grid-cols-3 gap-2">
                <div>
                  <div class="text-caption text-textTertiary mb-1">学科</div>
                  <select v-model="editDraft[q.temp_id].subject" class="w-full border border-border rounded-btn p-1.5 text-caption bg-white">
                    <option v-for="s in SUBJECT_OPTS" :key="s">{{ s }}</option>
                  </select>
                </div>
                <div>
                  <div class="text-caption text-textTertiary mb-1">题型</div>
                  <select v-model="editDraft[q.temp_id].type" class="w-full border border-border rounded-btn p-1.5 text-caption bg-white">
                    <option v-for="t in TYPE_OPTS" :key="t.v" :value="t.v">{{ t.l }}</option>
                  </select>
                </div>
                <div>
                  <div class="text-caption text-textTertiary mb-1">错因</div>
                  <select v-model="editDraft[q.temp_id].error_type" class="w-full border border-border rounded-btn p-1.5 text-caption bg-white">
                    <option v-for="e in ERROR_OPTS" :key="e">{{ e }}</option>
                  </select>
                </div>
              </div>
              <input v-if="editDraft[q.temp_id].error_type === '其他'" v-model="editDraft[q.temp_id].customError"
                     placeholder="请输入自定义错因…" class="w-full border border-border rounded-btn p-2 text-caption bg-white outline-none focus:border-primary" />
              <div class="flex justify-end gap-2">
                <button class="text-caption border border-border rounded-btn px-3 py-1 text-textSecondary" @click="toggleEdit(q)">取消</button>
                <button class="text-caption bg-primary text-white rounded-btn px-3 py-1" @click="saveEdit(q)">保存</button>
              </div>
            </div>
            <div class="mt-3 flex items-center gap-2 flex-wrap">
              <button class="text-caption bg-primary text-white rounded-btn px-3 py-1.5 font-medium"
                      @click="chatAsk(q)">对话提问</button>
              <button class="text-caption bg-card border border-border text-textSecondary rounded-btn px-3 py-1.5 font-medium"
                      @click="toggleEdit(q)">{{ editing.has(q.temp_id) ? '取消编辑' : '编辑' }}</button>
            </div>
          </div>
        </label>
      </div>
      <div class="flex items-center gap-3">
        <button class="bg-primary text-white rounded-btn px-6 py-2 text-sm disabled:opacity-40"
                :disabled="selected.size === 0 || importing" @click="doImport">
          {{ importing ? '导入中…' : `导入 ${selected.size} 道题` }}
        </button>
        <button class="border border-border rounded-btn px-4 py-2 text-sm text-textSecondary" @click="phase = 'upload'">重新上传</button>
      </div>
    </div>
  </div>
</template>
