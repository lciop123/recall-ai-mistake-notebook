<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { GitBranch, ImagePlus, MessageSquare, Plus, Search, Send, Square, Trash2, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { chatApi } from '../api'
import { toast } from '../api/request'
import MarkdownView from '../components/MarkdownView.vue'
import { formatTime } from '../utils/format'
import type { Conversation, ChatMessage } from '../types'

const route = useRoute()
const router = useRouter()

const conversations = ref<Conversation[]>([])
const conversationQuery = ref('')
const streamStage = ref('')
const messages = ref<ChatMessage[]>([])
const currentId = ref<number | null>(null)
const input = ref('')
// 正在生成 AI 回复的会话 id（按会话隔离：切到其他会话可自由发消息/操作，互不影响）
const generatingConv = ref<number | null>(null)
const addingQuestion = ref(false)
const addedIds = ref<Set<number>>(new Set())
const regenerating = ref(false)
// 数学题检测：命中则走一次性 solve 接口（后端完成工具+复核）
const mathRe = /[∫√∑∂π∞]|\\frac|\\int|\\sqrt|方程|函数|积分|导数|极限|证明|计算|求解|求值|不等式|数列|三角|几何|概率|矩阵|向量|椭圆|定积分|曲线/
type ThinkingLevel = 'off' | 'standard' | 'deep'
const thinkingLevel = ref<ThinkingLevel>('standard')  // 🧠 思考强度：off 关 / standard 标准 / deep 深度
const thinkingNow = ref(false)   // 当前请求思考中（无输出前显示状态）
const reviewNow = ref(0)       // 0=无复核 1=复核中 2=复核未过重答中
const toolNow = ref('')        // 工具计算中（显示表达式）
const solvingNow = ref(false)   // 求解中（统一状态）
const abortCtrl = ref<AbortController | null>(null)  // 求解中可停止
const lastOcrText = ref('')     // 图片题识别文本（供核对）
const lastOcrConfident = ref(true)   // OCR 交叉验证是否通过
const lastOcrSources = ref<string[]>([])  // 参与交叉验证的模型
const ocrEditing = ref('')      // 编辑中的识别文本
const models = ref<{ key: string; name: string }[]>([])
const cfgModel = ref('main')        // 模型
const cfgTemp = ref(0.3)            // 温度
const cfgDetail = ref<'brief' | 'standard' | 'detailed'>('standard')  // 详细度
const cfgMyQ = ref(true)            // 错题本上下文
const pendingImage = ref<string | null>(null)   // 待发送图片的 data URL
const pendingImagePath = ref<string | null>(null)  // 上传后的 image_path
const fileInput = ref<HTMLInputElement | null>(null)
const dragOverChat = ref(false)
const quoted = ref<string | null>(null)   // 引用内容（下一条消息基于它回答）
const quotedMeta = ref('')

const groupedConversations = computed(() => {
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startWeek = startToday - 6 * 24 * 60 * 60 * 1000
  const groups: { label: string; items: Conversation[] }[] = [
    { label: '今天', items: [] },
    { label: '近 7 天', items: [] },
    { label: '更早', items: [] },
  ]
  const q = conversationQuery.value.trim().toLowerCase()
  for (const c of conversations.value) {
    if (q && !`${c.title} ${c.last}`.toLowerCase().includes(q)) continue
    const time = new Date(c.updated_at).getTime()
    groups[time >= startToday ? 0 : time >= startWeek ? 1 : 2].items.push(c)
  }
  return groups.filter(g => g.items.length)
})

function onPickImage(e: Event) {
  const el = e.target as HTMLInputElement
  const file = el.files?.[0]
  if (file) acceptImageFile(file)
  el.value = ''
}

function acceptImageFile(file: File) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { toast('仅支持 jpg/png/webp', 'error'); return }
  if (file.size > 4 * 1024 * 1024) { toast('图片超过 4MB', 'error'); return }
  const reader = new FileReader()
  reader.onload = () => { pendingImage.value = reader.result as string }
  reader.readAsDataURL(file)
}

function onDropChat(e: DragEvent) {
  dragOverChat.value = false
  const file = Array.from(e.dataTransfer?.files || []).find(f => f.type.startsWith('image/'))
  if (file) acceptImageFile(file)
}

function removePendingImage() { pendingImage.value = null; pendingImagePath.value = null }

// 输入框高度自适应：多行输入自动增高，最高 40vh
function autoResize(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, window.innerHeight * 0.4) + 'px'
}

// 键盘：Enter 发送；Shift+Enter / Ctrl+Enter 换行
function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  if (!e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault()
    send()
  } else if (e.ctrlKey) {
    // Ctrl+Enter 插入换行
    e.preventDefault()
    const el = e.target as HTMLTextAreaElement
    const start = el.selectionStart ?? input.value.length
    const end = el.selectionEnd ?? input.value.length
    input.value = input.value.slice(0, start) + '\n' + input.value.slice(end)
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + 1 })
  }
}

let handlingRoutePrompt = false

async function consumeRoutePrompt() {
  if (handlingRoutePrompt) return
  handlingRoutePrompt = true
  try {
    const conv = route.query.conv
    if (conv) {
      const id = Number(conv)
      if (conversations.value.some(c => c.id === id) && currentId.value !== id) await openConversation(id)
    }
    // 识图录入页会带 q 参数跳转；ChatView 已被 KeepAlive 缓存时也需要消费它。
    if (route.query.q) {
      const q = String(route.query.q)
      await router.replace({ query: { conv: currentId.value ?? undefined } })
      await send(q)
    }
  } finally { handlingRoutePrompt = false }
}

onMounted(async () => {
  await loadConversations()
  try { const r = await fetch('/api/chat/models'); const j = await r.json(); models.value = j?.data || [] } catch { /* ignore */ }
  await consumeRoutePrompt()
})
watch(() => [route.query.conv, route.query.q], () => { consumeRoutePrompt() })

async function loadConversations() {
  conversations.value = await chatApi.conversations()
}

function parseSse(raw: string) {
  const event = raw.match(/^event:\s*(.+)$/m)?.[1]?.trim() || 'message'
  const data = raw.match(/^data:\s*([\s\S]*)$/m)?.[1] || ''
  try { return { event, data: JSON.parse(data) } } catch { return { event, data } }
}

async function openConversation(id: number) {
  currentId.value = id
  messages.value = await chatApi.messages(id)
  const added = await chatApi.addedQuestions(id)
  addedIds.value = new Set(added.map(a => a.message_id))
}

async function send(text?: string, imagePathOverride?: string) {
  return solveSend(text, imagePathOverride)
}

async function solveSend(text?: string, imagePathOverride?: string) {
  let content = (text ?? input.value).trim()
  const quotedContent = quoted.value
  if (quotedContent) {
    content = `（引用以下内容：
${quotedContent}
）

${content}`
    quoted.value = null
    quotedMeta.value = ''
  }
  if (imagePathOverride) pendingImagePath.value = imagePathOverride
  if (!content && !pendingImage.value && !imagePathOverride) return
  if (generatingConv.value !== null) return
  if (currentId.value === null) await newChat()
  const genConvId = currentId.value
  if (genConvId === null) return
  // 图片上传
  let imagePath: string | undefined
  if (pendingImage.value) {
    try {
      const blob = await (await fetch(pendingImage.value)).blob()
      const f = new File([blob], 'chat.png', { type: blob.type || 'image/png' })
      const up = await chatApi.uploadImage(f)
      imagePath = up.image_path
    } catch { toast('图片上传失败', 'error'); return }
  }
  imagePath = imagePathOverride || imagePath
  input.value = ''
  pendingImage.value = null
  pendingImagePath.value = null
  const imageUrl = imagePath ? `/images/${imagePath}` : undefined
  messages.value.push({ id: Date.now(), role: 'user', content, created_at: '', image_url: imageUrl })
  const placeholder: ChatMessage = { id: Date.now() + 1, role: 'assistant', content: '', created_at: '' }
  messages.value.push(placeholder)
  generatingConv.value = genConvId
  thinkingNow.value = true
  solvingNow.value = true
  streamStage.value = imagePath ? '正在上传并识别图片中的题目…' : '正在分析题意…'
  abortCtrl.value = new AbortController()
  try {
    const r = await fetch('/api/chat/solve-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      signal: abortCtrl.value.signal,
      body: JSON.stringify({
        conversation_id: genConvId, message: content, image_path: imagePath,
        thinking: thinkingLevel.value,
        model: cfgModel.value, temperature: cfgTemp.value,
        detail: cfgDetail.value, use_my_questions: cfgMyQ.value,
      }),
    })
    if (!r.ok || !r.body) throw new Error('求解服务不可用')
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let split = buffer.indexOf('\n\n')
      while (split >= 0) {
        const packet = parseSse(buffer.slice(0, split))
        buffer = buffer.slice(split + 2)
        if (packet.event === 'stage') streamStage.value = packet.data.text || ''
        else if (packet.event === 'delta') {
          thinkingNow.value = false
          streamStage.value = '正在呈现已复核的解答…'
          placeholder.content += packet.data.text || ''
        } else if (packet.event === 'meta') {
          if (packet.data.conv_id) currentId.value = packet.data.conv_id
          if (packet.data.message_id) placeholder.id = packet.data.message_id
          lastOcrText.value = packet.data.ocr_text || ''
          lastOcrConfident.value = !!packet.data.ocr_confident
          lastOcrSources.value = packet.data.ocr_sources || []
          ocrEditing.value = lastOcrText.value
        } else if (packet.event === 'error') {
          placeholder.content = '⚠️ 求解失败：' + (packet.data.message || '未知错误')
        }
        split = buffer.indexOf('\n\n')
      }
    }
    if (!placeholder.content) placeholder.content = '（未生成回答，请重试）'
    await loadConversations()
  } catch (e: any) {
    placeholder.content = e?.name === 'AbortError' ? '⏹ 已停止生成（可重新发送）' : '⚠️ 求解失败，请重试'
  } finally {
    thinkingNow.value = false
    reviewNow.value = 0
    toolNow.value = ''
    solvingNow.value = false
    streamStage.value = ''
    abortCtrl.value = null
    if (generatingConv.value === genConvId) generatingConv.value = null
  }
}

function stopSolve() {
  if (abortCtrl.value) abortCtrl.value.abort()
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'assistant' && !last.content) last.content = '⏹ 已停止生成（可重新发送）'
  thinkingNow.value = false
  reviewNow.value = 0
  toolNow.value = ''
  solvingNow.value = false
  abortCtrl.value = null
  if (generatingConv.value === currentId.value) generatingConv.value = null
}

async function resolveWithOcr() {
  if (!ocrEditing.value.trim() || solvingNow.value || currentId.value === null) return
  const text = ocrEditing.value.trim()
  const genConvId = currentId.value
  const placeholder: ChatMessage = { id: Date.now(), role: 'assistant', content: '', created_at: '' }
  messages.value.push(placeholder)
  generatingConv.value = genConvId
  solvingNow.value = true
  thinkingNow.value = true
  streamStage.value = '正在根据你确认的题面重新推导…'
  abortCtrl.value = new AbortController()
  try {
    const r = await fetch('/api/chat/solve-stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      signal: abortCtrl.value.signal,
      body: JSON.stringify({
        conversation_id: genConvId, message: '请根据以下确认题面重新完整求解：\n' + text,
        question_text: text, thinking: thinkingLevel.value, model: cfgModel.value,
        temperature: cfgTemp.value, detail: cfgDetail.value, use_my_questions: cfgMyQ.value,
      }),
    })
    if (!r.ok || !r.body) throw new Error('求解服务不可用')
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let split = buffer.indexOf('\n\n')
      while (split >= 0) {
        const packet = parseSse(buffer.slice(0, split))
        buffer = buffer.slice(split + 2)
        if (packet.event === 'stage') streamStage.value = packet.data.text || ''
        else if (packet.event === 'delta') { thinkingNow.value = false; placeholder.content += packet.data.text || '' }
        else if (packet.event === 'meta') { if (packet.data.message_id) placeholder.id = packet.data.message_id }
        else if (packet.event === 'error') placeholder.content = '⚠️ 求解失败：' + (packet.data.message || '未知错误')
        split = buffer.indexOf('\n\n')
      }
    }
    if (!placeholder.content) placeholder.content = '（未生成回答，请重试）'
    lastOcrText.value = ''
    ocrEditing.value = ''
    await loadConversations()
  } catch (e: any) {
    placeholder.content = e?.name === 'AbortError' ? '⏹ 已停止生成（可重新发送）' : '⚠️ 求解失败，请重试'
  } finally {
    thinkingNow.value = false
    reviewNow.value = 0
    toolNow.value = ''
    solvingNow.value = false
    streamStage.value = ''
    abortCtrl.value = null
    if (generatingConv.value === genConvId) generatingConv.value = null
  }
}

async function addQuestion(m: ChatMessage) {
  if (addingQuestion.value) return
  if (!currentId.value) { toast('请先发起一次对话', 'error'); return }
  if (addedIds.value.has(m.id)) { toast('该内容已加入错题本', 'error'); return }
  addingQuestion.value = true
  try {
    const q = await chatApi.addQuestion(currentId.value, m.id)
    addedIds.value.add(m.id)
    toast(`✅ 已加入错题本：${q.question_text.slice(0, 30)}${q.question_text.length > 30 ? '…' : ''}`)
  } catch (e) {
    const msg = (e as Error)?.message || ''
    if (msg.includes('已在错题本')) {
      // 题目已存在：标记为已加入，按钮消失，不重复添加
      addedIds.value.add(m.id)
      toast('该题已在错题本中，已跳过')
    } else {
      toast('未能生成错题，请重试或手动录入', 'error')
    }
  } finally {
    addingQuestion.value = false
  }
}

async function newChat() {
  const c = await chatApi.create()
  await loadConversations()
  currentId.value = c.id
  messages.value = []
}

async function newChatInherit() {
  if (!currentId.value) { toast('请先打开一个会话再继承上下文', 'error'); return }
  try {
    const c = await chatApi.createInherited(currentId.value, 20)
    await loadConversations()
    currentId.value = c.id
    messages.value = []
    toast('✅ 已开启新会话，AI 保留最近 20 条上下文')
  } catch { toast('创建失败，请重试', 'error') }
}

async function followUp(m: ChatMessage) {
  // 追问：基于当前回答继续深入（自动发送）
  await solveSend('🔍 追问：请针对你刚才的回答，把关键方法讲得更深入一些，并补充一个类似例子巩固')
}

async function quizMe(m: ChatMessage) {
  // 考考我：AI 基于当前题目知识点出道变式题
  await solveSend('🎯 考考我：请基于这道题的知识点出一道变式题（带难度梯度），我先作答，你最后批改并讲解')
}

async function regenerate(m: ChatMessage) {
  if (!currentId.value || regenerating.value) return
  regenerating.value = true
  try {
    const r = await chatApi.regenerate(currentId.value, m.id)
    // 移除本地该消息及其后消息
    const idx = messages.value.findIndex(x => x.id === m.id)
    if (idx >= 0) messages.value = messages.value.slice(0, idx)
    await send(r.last_user_content, r.last_user_image || undefined)
  } catch {
    toast('重新生成失败，请重试', 'error')
  } finally {
    regenerating.value = false
  }
}

function quote(m: ChatMessage) {
  quoted.value = m.content.slice(0, 600)
  quotedMeta.value = m.content.replace(/\s+/g, ' ').slice(0, 60)
  toast('📎 已引用，下一条消息将基于此内容回答')
}

async function removeChat(id: number) {
  if (!confirm('删除该会话？')) return
  await chatApi.remove(id)
  if (currentId.value === id) { currentId.value = null; messages.value = [] }
  await loadConversations()
}
</script>

<template>
  <div class="flex" style="height: calc(100vh - 60px)">
    <!-- 左栏会话 -->
    <aside class="w-[280px] shrink-0 bg-card border-r border-border p-4 flex flex-col overflow-hidden">
      <div class="flex items-center px-1 pb-3">
        <span class="text-caption text-textTertiary">会话历史</span>
        <button class="w-8 h-8 rounded-btn text-textSecondary hover:text-primary hover:bg-primary/10 inline-flex items-center justify-center" title="新会话（继承当前会话上下文，界面从空白开始）" @click="newChatInherit">
          <GitBranch :size="17" />
        </button>
        <button class="ml-1 w-8 h-8 rounded-btn text-primary hover:bg-primary/10 inline-flex items-center justify-center" title="新建空白对话" @click="newChat">
          <Plus :size="18" />
        </button>
      </div>
      <label class="relative mb-3 block">
        <Search :size="15" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-textTertiary" />
        <input v-model="conversationQuery" class="w-full rounded-btn border border-border bg-bg py-2 pl-8 pr-8 text-caption outline-none focus:border-primary"
               placeholder="搜索会话" />
        <button v-if="conversationQuery" class="absolute right-2 top-1/2 -translate-y-1/2 text-textTertiary hover:text-textPrimary" title="清空搜索" @click.prevent="conversationQuery = ''">
          <X :size="14" />
        </button>
      </label>
      <div class="flex-1 overflow-y-auto pr-1">
        <div v-if="!groupedConversations.length" class="py-8 text-center text-caption text-textTertiary">没有匹配的会话</div>
        <section v-for="group in groupedConversations" :key="group.label" class="mb-4">
          <div class="px-2 pb-1 text-caption text-textTertiary">{{ group.label }}</div>
          <div v-for="c in group.items" :key="c.id"
               class="px-2.5 py-2 rounded-btn cursor-pointer mb-1 group relative transition-colors"
               :class="currentId === c.id ? 'bg-primary/10' : 'hover:bg-bg'"
               @click="openConversation(c.id)">
            <div class="text-body truncate pr-7" :class="currentId === c.id ? 'text-primary font-medium' : ''">{{ c.title }}</div>
            <div class="text-caption text-textTertiary truncate pr-7">{{ c.last || '暂无消息' }}</div>
            <button class="absolute top-3 right-2 w-5 h-5 rounded text-textTertiary hover:text-error hover:bg-card inline-flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
                    title="删除会话" @click.stop="removeChat(c.id)"><Trash2 :size="14" /></button>
          </div>
        </section>
      </div>
      <button class="mt-3 border-t border-border pt-3 text-primary text-sm font-medium inline-flex items-center gap-1.5" @click="newChat"><Plus :size="16" /> 新建空白对话</button>
      <button class="mt-1 text-textSecondary text-xs font-medium inline-flex items-center gap-1.5 hover:text-primary" title="继承当前会话最近 20 条消息，新界面从空白开始" @click="newChatInherit"><GitBranch :size="14" /> 新会话（继承上下文）</button>
    </aside>

    <!-- 右栏对话 -->
    <main class="flex-1 flex flex-col p-6 relative"
          @dragover.prevent="dragOverChat = true"
          @dragleave.prevent="dragOverChat = false"
          @drop.prevent="onDropChat">
      <!-- 拖拽图片遮罩提示 -->
      <div v-if="dragOverChat" class="absolute inset-0 z-10 flex items-center justify-center bg-primary/10 rounded-xl border-2 border-dashed border-primary pointer-events-none">
        <div class="text-primary font-medium bg-card px-6 py-3 rounded-btn shadow">🖼️ 松开即可添加图片给 AI 看</div>
      </div>
      <div class="flex-1 overflow-y-auto space-y-4 pb-4">
          <div v-if="messages.length === 0" class="text-center text-textTertiary py-16">
          <MessageSquare :size="34" stroke-width="1.4" class="mx-auto mb-3 text-primary/70" />
          <div>向 AI 提问任何学习问题，例如：<br /><span class="text-primary">“函数单调性怎么求？”</span></div>
        </div>
        <div v-for="m in messages" :key="m.id" class="flex flex-col" :class="m.role === 'user' ? 'items-end' : 'items-start'">
          <div v-if="m.role === 'user'" class="max-w-[70%] bg-primary text-white rounded-card rounded-br-sm px-4 py-2.5" style="font-size:15px;line-height:1.7">
            <img v-if="m.image_url" :src="m.image_url" class="rounded-lg max-h-56 mb-2 border border-white/20" />
            <span v-if="m.content" class="whitespace-pre-wrap">{{ m.content }}</span>
            <span v-else class="text-white/70 text-caption">📷 图片提问</span>
          </div>
          <div v-else class="max-w-[70%] bg-card border border-border border-l-[3px] border-l-error rounded-card rounded-bl-sm px-4 py-2.5" style="font-size:15px">
            <div v-if="generatingConv === currentId && m.id === messages[messages.length - 1].id && !m.content" class="text-caption text-textTertiary flex items-center gap-2">
              <span class="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin inline-block" />{{ streamStage || 'AI 正在准备回答…' }}
            </div>
            <div v-if="toolNow && generatingConv === currentId && m.id === messages[messages.length - 1].id" class="text-caption text-primary flex items-center gap-2 mt-1">
              <span class="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin inline-block" />🧮 AI 正在计算验证：{{ toolNow.length > 40 ? toolNow.slice(0, 40) + '…' : toolNow }}
            </div>
            <div v-if="reviewNow === 1 && generatingConv === currentId && m.id === messages[messages.length - 1].id" class="text-caption text-primary flex items-center gap-2 mt-1">
              <span class="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin inline-block" />🔍 AI 复核中…（检查解题方法与计算）
            </div>
            <div v-if="reviewNow === 2 && generatingConv === currentId && m.id === messages[messages.length - 1].id" class="text-caption text-warning flex items-center gap-2 mt-1">
              <span class="w-3 h-3 border-2 border-warning border-t-transparent rounded-full animate-spin inline-block" />⚠️ 检测到问题，AI 正在重新生成…
            </div>
            <MarkdownView :content="m.content" />
            <div v-if="lastOcrText && m.id === messages[messages.length - 1].id" class="mt-2 text-caption bg-bg border border-border/60 rounded-btn px-2 py-1.5">
              <div class="flex items-center justify-between mb-1">
                <b>📷 识别的题目（可编辑）</b>
                <span v-if="lastOcrConfident" class="text-emerald-500 text-xs">✅ 多模型交叉验证通过（{{ lastOcrSources.length }} 个模型一致）</span>
                <span v-else class="text-amber-500 text-xs">⚠️ 模型识别有分歧，请务必核对下方题面</span>
                <button class="text-primary border border-primary/40 rounded-btn px-2 py-0.5 hover:bg-primary/10"
                        :disabled="solvingNow || !ocrEditing.trim()" @click="resolveWithOcr">🔄 以此题面重新求解</button>
              </div>
              <textarea v-model="ocrEditing" rows="3" class="w-full bg-card border border-border rounded-btn p-2 text-caption outline-none focus:border-primary resize-y" style="font-size:12px" />
              <div class="text-textTertiary mt-1">✏️ 识别错了直接改（如负号/上下标），点"重新求解"按你改后的题面计算</div>
            </div>
            <span v-if="generatingConv === currentId && m.id === messages[messages.length - 1].id && m.content" class="typing-cursor" style="color:#007AFF">▍</span>
            <div v-if="addedIds.has(m.id)" class="flex gap-2 mt-2">
              <span class="text-caption text-success">✅ 已加入错题本</span>
            </div>
            <div v-else-if="generatingConv !== currentId && m.id === messages[messages.length - 1].id && m.content" class="flex gap-2 mt-2">
              <button class="text-caption border border-primary/40 text-primary rounded-btn px-3 py-1 disabled:opacity-40"
                      :disabled="addingQuestion" @click="addQuestion(m)">
                {{ addingQuestion ? '处理中…' : '＋ 加入错题本' }}
              </button>
            </div>
            <div v-if="generatingConv !== currentId && m.content" class="flex gap-2 mt-2 flex-wrap">
              <button class="text-caption border border-border text-textSecondary rounded-btn px-3 py-1 hover:border-borderStrong disabled:opacity-40"
                      :disabled="regenerating" @click="regenerate(m)">
                {{ regenerating && m.id === messages[messages.length - 1].id ? '重新生成中…' : '↻ 重新生成' }}
              </button>
              <button class="text-caption border border-border text-textSecondary rounded-btn px-3 py-1 hover:border-borderStrong"
                      @click="quote(m)">📎 引用</button>
              <button class="text-caption border border-border text-textSecondary rounded-btn px-3 py-1 hover:border-primary/50 hover:text-primary"
                      @click="followUp(m)">💡 追问</button>
              <button class="text-caption border border-border text-textSecondary rounded-btn px-3 py-1 hover:border-warning/60 hover:text-warning"
                      @click="quizMe(m)">🎯 考考我</button>
            </div>
          </div>
          <span class="text-caption text-textTertiary mt-1" style="font-size:11px">🕐 {{ formatTime(m.created_at) }}</span>
        </div>
      </div>
      <!-- 引用条：显示引用成功，下一条消息基于它回答 -->
      <div v-if="quoted" class="flex items-center gap-2 bg-primary/5 border border-primary/30 rounded-btn px-3 py-2 mb-2 text-caption">
        <span class="text-primary font-medium shrink-0">📎 已引用</span>
        <span class="text-textSecondary truncate flex-1">{{ quotedMeta }}</span>
        <button class="text-textTertiary hover:text-error shrink-0" @click="quoted = null; quotedMeta = ''">✕</button>
      </div>
      <!-- 配置栏（精简）：模型切换 + 思考强度；温度/详细度/错题本上下文由系统自动调配 -->
      <div class="flex flex-wrap items-center gap-2 mb-2 text-caption text-textTertiary">
        <select v-model="cfgModel" class="px-2 py-1 rounded-btn border border-border bg-card outline-none focus:border-primary" title="对话模型">
          <option v-for="m in models" :key="m.key" :value="m.key">🤖 {{ m.name }}</option>
        </select>
        <span class="text-textTertiary">思考：</span>
        <button class="px-1.5 py-0.5 rounded-full border transition-colors"
                :class="thinkingLevel === 'off' ? 'bg-primary/10 border-primary/40 text-primary' : 'border-border text-textTertiary hover:border-borderStrong'"
                title="快速回答" @click="thinkingLevel = 'off'">⚡快</button>
        <button class="px-1.5 py-0.5 rounded-full border transition-colors"
                :class="thinkingLevel === 'standard' ? 'bg-primary/10 border-primary/40 text-primary' : 'border-border text-textTertiary hover:border-borderStrong'"
                title="标准思考（推荐）" @click="thinkingLevel = 'standard'">🧠标准</button>
        <button class="px-1.5 py-0.5 rounded-full border transition-colors"
                :class="thinkingLevel === 'deep' ? 'bg-error/10 border-error/50 text-error' : 'border-border text-textTertiary hover:border-borderStrong'"
                title="深度思考（难题）" @click="thinkingLevel = 'deep'">🧠深度</button>
      </div>
      <div class="flex items-end gap-2 bg-card border border-border rounded-card p-3">
        <!-- 待发送图片预览 -->
        <div v-if="pendingImage" class="relative shrink-0">
          <img :src="pendingImage" class="w-14 h-14 object-cover rounded-lg border border-border" />
          <button class="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-error text-white text-xs leading-5" @click="removePendingImage">✕</button>
        </div>
        <!-- 拍照/上传图片 -->
        <button class="w-9 h-9 rounded-btn border border-border text-textSecondary hover:bg-bg shrink-0 inline-flex items-center justify-center"
                title="拍照/上传图片，让 AI 看图回答" :disabled="generatingConv !== null" @click="fileInput?.click()"><ImagePlus :size="18" /></button>
        <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" class="hidden" @change="onPickImage" />
        <textarea v-model="input" rows="1" placeholder="输入问题，Enter 发送；Ctrl+Enter 换行…（可先拍照让 AI 看图答题）"
                  class="flex-1 resize-none outline-none bg-transparent" style="font-size:15px; min-height:36px; max-height:40vh; overflow-y:auto"
                  @input="autoResize" @keydown="onKeydown" />
        <button v-if="solvingNow" class="w-9 h-9 rounded-btn bg-error text-white shrink-0 inline-flex items-center justify-center" title="停止生成" @click="stopSolve()"><Square :size="15" fill="currentColor" /></button>
        <button v-else class="w-9 h-9 rounded-btn bg-primary text-white disabled:opacity-40 inline-flex items-center justify-center" :disabled="generatingConv !== null || (!input.trim() && !pendingImage)" title="发送" @click="send()"><Send :size="17" /></button>
      </div>
      <!-- 输入实时预览：LaTeX 公式自动渲染，不显示源码符号 -->
      <div v-if="input.trim()" class="mt-2 bg-bg border border-border/60 rounded-card px-3 py-2 max-h-48 overflow-y-auto">
        <div class="text-caption text-textTertiary mb-1">👁 发送预览（公式自动渲染）</div>
        <MarkdownView :content="input" />
      </div>
    </main>
  </div>
</template>

<style scoped>
.typing-cursor { animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0; } }
</style>
