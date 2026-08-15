<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import NavBar from './components/NavBar.vue'

// 后端断连检测：每 30s 检查 health，连续 2 次失败才显示横幅（避免 OCR/长请求期间的瞬时误报）
const backendDown = ref(false)
let healthFailCount = 0
let healthTimer: number | undefined

async function checkHealth() {
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(4000) })
    const j = await r.json()
    if (j && j.code === 0) {
      healthFailCount = 0
      backendDown.value = false
    } else {
      healthFailCount += 1
    }
  } catch {
    healthFailCount += 1
  }
  backendDown.value = healthFailCount >= 2
}

onMounted(() => {
  checkHealth()
  healthTimer = window.setInterval(checkHealth, 30000)
})
onUnmounted(() => {
  if (healthTimer) window.clearInterval(healthTimer)
})
</script>

<template>
  <div class="min-h-screen bg-bg">
    <div v-if="backendDown" class="fixed top-0 left-0 right-0 z-[999] bg-red-500 text-white text-center text-sm py-1.5 px-4">
      ⚠️ 后端未连接（服务可能已停止），数据可能加载失败 —— 请双击运行「启动后端.bat」后刷新页面
    </div>
    <NavBar />
    <!-- KeepAlive：所有页面切换路由后保持当前状态/进度（数据页在 onActivated 中刷新） -->
    <router-view v-slot="{ Component }">
      <transition name="page-fade" mode="out-in">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </transition>
    </router-view>
  </div>
</template>

<style>
.page-fade-enter-active,
.page-fade-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.page-fade-enter-from { opacity: 0; transform: translateY(4px); }
.page-fade-leave-to { opacity: 0; transform: translateY(-2px); }
</style>
