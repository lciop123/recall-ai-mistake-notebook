<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { planApi } from '../api'
import { toast } from '../api/request'
import MarkdownView from '../components/MarkdownView.vue'
import type { Question } from '../types'

const router = useRouter()
const cards = ref<Question[]>([])
const index = ref(0)
const flipped = ref(false)
const loading = ref(true)
const saving = ref(false)
const completed = ref(0)
const current = computed(() => cards.value[index.value])

async function load() {
  loading.value = true
  try {
    const result = await planApi.daily(undefined, 8)
    cards.value = result.due
  } catch {
    toast('卡片队列加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
  }
}

function flip() { if (!saving.value && current.value) flipped.value = !flipped.value }
async function grade(quality: number) {
  if (!current.value || saving.value) return
  saving.value = true
  try {
    await planApi.complete(current.value.id, quality)
    completed.value++
    index.value++
    flipped.value = false
  } catch {
    toast('复习结果保存失败，请稍后重试', 'error')
  } finally {
    saving.value = false
  }
}
function skip() { if (current.value) { index.value++; flipped.value = false } }
function onKey(event: KeyboardEvent) {
  const element = event.target as HTMLElement
  if (['INPUT', 'TEXTAREA'].includes(element?.tagName)) return
  if (event.code === 'Space') { event.preventDefault(); flip() }
  if (flipped.value && ['1', '2', '3', '4'].includes(event.key)) grade([0, 3, 4, 5][Number(event.key) - 1])
}
onMounted(() => { load(); window.addEventListener('keydown', onKey) })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <main class="max-w-2xl mx-auto px-6 py-8">
    <div class="flex items-center mb-6">
      <div>
        <h1 class="text-h1">卡片复习</h1>
        <p class="mt-1 text-caption text-textSecondary">先回忆，再翻面判断掌握程度</p>
      </div>
      <button class="ml-auto text-caption border border-border rounded-btn px-3 py-1.5 text-textSecondary" @click="router.push('/')">返回首页</button>
    </div>

    <div v-if="loading" class="h-72 bg-bg border border-border rounded-card animate-pulse" />
    <div v-else-if="!cards.length" class="bg-card border border-border rounded-card p-12 text-center text-textSecondary">暂无待复习错题</div>
    <section v-else-if="current" class="bg-card border border-border rounded-card p-6 min-h-[360px] flex flex-col">
      <div class="flex items-center text-caption text-textSecondary"><span>第 {{ index + 1 }} / {{ cards.length }} 题</span><span class="ml-auto">已完成 {{ completed }}</span></div>
      <button type="button" class="my-5 flex-1 text-left border-l-[3px] border-question px-4 py-3 focus:outline-none" :aria-label="flipped ? '隐藏答案' : '显示答案'" @click="flip">
        <div class="text-caption text-textTertiary mb-2">{{ flipped ? '答案与解析' : '题目' }}</div>
        <MarkdownView :content="flipped ? `${current.answer || '（未填写答案）'}${current.analysis ? '\n\n' + current.analysis : ''}` : current.question_text" />
      </button>
      <div v-if="!flipped" class="flex justify-center"><button class="bg-primary text-white rounded-btn px-6 py-2 text-sm" @click="flip">显示答案</button></div>
      <div v-else class="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <button class="border border-error/40 text-error rounded-btn px-2 py-2 text-caption" :disabled="saving" @click="grade(0)">1 重新学习</button>
        <button class="border border-warning/40 text-warning rounded-btn px-2 py-2 text-caption" :disabled="saving" @click="grade(3)">2 有点难</button>
        <button class="border border-primary/40 text-primary rounded-btn px-2 py-2 text-caption" :disabled="saving" @click="grade(4)">3 记得</button>
        <button class="border border-success/40 text-success rounded-btn px-2 py-2 text-caption" :disabled="saving" @click="grade(5)">4 很简单</button>
      </div>
      <button class="mt-3 mx-auto text-caption text-textTertiary hover:text-textSecondary" @click="skip">跳过本题</button>
    </section>
    <section v-else class="bg-card border border-border rounded-card p-12 text-center">
      <div class="text-h2">本轮完成</div>
      <p class="mt-2 text-textSecondary">已完成 {{ completed }} 道卡片复习。</p>
      <button class="mt-5 bg-primary text-white rounded-btn px-5 py-2 text-sm" @click="router.push('/')">查看学习计划</button>
    </section>
  </main>
</template>
