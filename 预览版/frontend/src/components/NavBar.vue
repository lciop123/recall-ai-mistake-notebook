<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { PenLine, Plus, ScanLine } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const navs = [
  { path: '/', label: '仪表盘' },
  { path: '/questions', label: '错题本' },
  { path: '/review', label: '举一反三' },
  { path: '/redo', label: '重做' },
  { path: '/flashcards', label: '卡片复习' },
  { path: '/stats', label: '看板' },
  { path: '/chat', label: 'AI 对话' },
  { path: '/help', label: '帮助' },
]

function go(path: string) {
  if (route.path !== path) router.push(path)
}

// 录入方式选择菜单
const menuOpen = ref(false)
const menuRef = ref<HTMLDivElement | null>(null)

function toggleMenu() { menuOpen.value = !menuOpen.value }

function pick(path: string) {
  menuOpen.value = false
  go(path)
}

function onDocClick(e: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) {
    menuOpen.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <header class="h-[60px] bg-card border-b border-border flex items-center px-4 sm:px-8 gap-4 sm:gap-9 sticky top-0 z-40 overflow-hidden">
    <div class="flex items-center gap-2.5 cursor-pointer shrink-0" @click="go('/')">
      <span class="w-7 h-7 rounded-btn bg-primary text-white flex items-center justify-center text-sm font-semibold">R</span>
      <span class="text-2xl font-semibold">Recall</span>
    </div>
    <nav class="flex gap-2 flex-1 min-w-0 overflow-x-auto">
      <button
        v-for="n in navs" :key="n.path"
        class="px-5 py-2 rounded-btn text-body text-textSecondary hover:text-textPrimary hover:bg-bg transition whitespace-nowrap"
        :class="route.path === n.path ? '!bg-primary/10 !text-primary font-medium' : ''"
        @click="go(n.path)"
      >{{ n.label }}</button>
    </nav>
    <div class="relative" ref="menuRef">
      <button class="bg-primary text-white rounded-btn px-4 py-1.5 text-sm font-medium hover:opacity-90 inline-flex items-center gap-1.5" @click.stop="toggleMenu">
        <Plus :size="16" /> 录入
      </button>
      <!-- 录入方式选择 -->
      <div v-if="menuOpen" class="absolute right-0 top-[calc(100%+6px)] w-56 bg-card border border-border rounded-card shadow-lg py-1.5 z-50">
        <button class="w-full text-left px-4 py-2.5 hover:bg-bg flex items-center gap-3" @click="pick('/capture')">
          <ScanLine :size="21" class="text-primary shrink-0" />
          <span>
            <span class="block text-body font-medium">识图录入</span>
            <span class="block text-caption text-textTertiary">上传/截图识别题目，AI 拆题归类</span>
          </span>
        </button>
        <button class="w-full text-left px-4 py-2.5 hover:bg-bg flex items-center gap-3" @click="pick('/input')">
          <PenLine :size="21" class="text-primary shrink-0" />
          <span>
            <span class="block text-body font-medium">文本录入</span>
            <span class="block text-caption text-textTertiary">手敲错题，AI 自动归类、生成答案与解析</span>
          </span>
        </button>
      </div>
    </div>
  </header>
</template>
