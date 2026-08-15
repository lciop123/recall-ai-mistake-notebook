<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import MarkdownView from './MarkdownView.vue'

const props = defineProps<{
  open: boolean
  questionText: string
  knowledgePoint: string
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const loading = ref(false)
const content = ref('')
const cacheKey = computed(() => `kp:${props.knowledgePoint || props.questionText.slice(0, 20)}`)

watch(() => props.open, async (v) => {
  if (!v) return
  // 命中本地缓存直接显示
  try {
    const cached = localStorage.getItem(cacheKey.value)
    if (cached) { content.value = cached; return }
  } catch { /* 忽略 */ }
  content.value = ''
  loading.value = true
  try {
    const resp = await fetch('/api/ai/knowledge-point', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_text: props.questionText, knowledge_point: props.knowledgePoint }),
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
        content.value = full
      }
    }
    content.value = full
    if (full && !full.startsWith('⚠️')) {
      try { localStorage.setItem(cacheKey.value, full) } catch { /* 忽略 */ }
    }
  } catch {
    content.value = '⚠️ 生成失败，请重试'
  } finally {
    loading.value = false
  }
})

function onLearned() { emit('close') }
onUnmounted(() => { /* noop */ })
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/45" @click.self="emit('close')">
    <div class="bg-card rounded-card w-[680px] max-w-[92vw] max-h-[85vh] flex flex-col shadow-xl">
      <div class="flex items-center px-5 py-3 border-b border-border">
        <span class="w-6 h-6 rounded-btn bg-primary/10 text-primary flex items-center justify-center text-sm">📖</span>
        <b class="ml-2 text-body">知识点系统学习</b>
        <span class="ml-auto text-caption text-textTertiary max-w-[45%] truncate">{{ knowledgePoint || '当前知识点' }}</span>
        <button class="ml-3 text-textTertiary hover:text-error" @click="emit('close')">✕</button>
      </div>
      <div class="flex-1 overflow-y-auto p-5 bg-bg/40">
        <div v-if="loading && !content" class="text-center py-10">
          <div class="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <div class="text-caption text-textTertiary">AI 正在讲解知识点…</div>
        </div>
        <div v-else class="bg-card border border-border rounded-card p-5">
          <div v-if="loading" class="text-caption text-primary mb-2">🤖 生成中…（实时输出）</div>
          <MarkdownView :content="content" />
        </div>
      </div>
      <div class="px-5 py-3 border-t border-border flex items-center justify-end gap-2">
        <button class="text-caption border border-border rounded-btn px-4 py-2 text-textSecondary hover:border-borderStrong" @click="emit('close')">关闭</button>
        <button class="text-caption bg-success text-white rounded-btn px-5 py-2 font-medium" @click="onLearned">✅ 我学会了</button>
      </div>
    </div>
  </div>
</template>
