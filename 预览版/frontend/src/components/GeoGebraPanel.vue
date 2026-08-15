<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  questionText: string
  subject?: string
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const containerId = `ggb-${Math.random().toString(36).slice(2, 8)}`
const loadingLib = ref(false)
const drawing = ref(false)
const error = ref('')
const libLoaded = ref(false)
const cmdList = ref<string[]>([])  // AI 绘图命令清单（侧边栏显示）
let applet: any = null
let app: any = null

declare global {
  interface Window { GGBApplet?: any }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`)
    if (existing?.dataset.loaded === 'true') { resolve(); return }
    if (existing) existing.remove()
    const el = document.createElement('script')
    el.src = src
    el.onload = () => { el.dataset.loaded = 'true'; resolve() }
    el.onerror = () => { el.remove(); reject(new Error('加载失败')) }
    document.head.appendChild(el)
  })
}

async function loadGeoGebraScript(): Promise<boolean> {
  try {
    await loadScript('/geogebra/deployggb.js')
    if (typeof window.GGBApplet === 'function') return true
    // Vite 开发服务器可能将不存在的静态文件回退为 index.html；此时 load 事件会触发但库没有初始化。
    document.querySelector('script[src="/geogebra/deployggb.js"]')?.remove()
  } catch {
    // 继续尝试官方脚本。
  }
  // 发布版不携带庞大的离线 vendor bundle，克隆后使用 GeoGebra 官方脚本。
  await loadScript('https://www.geogebra.org/apps/deployggb.js')
  if (typeof window.GGBApplet !== 'function') throw new Error('GeoGebra 初始化失败')
  return false
}

function isGeometric(text: string): boolean {
  return /三角形|圆|几何|坐标|平行|垂直|梯形|椭圆|双曲线|抛物线|棱|锥|柱|正方|矩形|角|直线|线段|中点|切线|相切|勾股/.test(text)
}

async function initApplet() {
  if (libLoaded.value && applet) return
  loadingLib.value = true
  error.value = ''
  try {
    const useLocalAssets = await loadGeoGebraScript()
    libLoaded.value = true
    const params = {
      appName: 'geometry',  // geometry 模式：无代数区/对象列表，画板最干净
      width: 720,
      height: 480,
      showToolBar: true,
      showAlgebraInput: false,
      showMenuBar: false,
      showResetIcon: true,
      enableRightClick: false,
      enableLabelDrags: false,
      language: 'zh_CN',
      showToolBarHelp: false,
      showInputField: false,
      showAlgebraView: false,
    }
    applet = new (window as any).GGBApplet(params, true)
    // 本机存在 vendor bundle 时离线加载；公开仓库克隆后由官方脚本使用默认在线资源。
    if (useLocalAssets) applet.setHTML5Codebase && applet.setHTML5Codebase('/geogebra/web3d/')
    const ready = () => {
      try {
        // 新版 deployggb：getAppletObject()；旧版：getAppletAPI()
        const a = applet.getAppletObject ? applet.getAppletObject() : applet.getAppletAPI()
        if (a && typeof a.evalCommand === 'function') { app = a; return true }
      } catch { /* not ready */ }
      return false
    }
    // 官方回调 + 轮询兜底（首次加载约 10-40 秒，视网络而定）
    applet.inject(containerId, () => { ready() })
    for (let i = 0; i < 100; i++) {  // 最长约 60s
      await new Promise(r => setTimeout(r, 600))
      if (ready()) break
    }
    if (!app) {
      error.value = '画板加载超时（首次加载需联网下载 GeoGebra 资源，可能需 10-40 秒）。请稍后重试，或检查网络。'
    }
  } catch (e) {
    error.value = 'GeoGebra 画板加载失败，请重试'
  } finally {
    loadingLib.value = false
  }
}

async function aiDraw() {
  if (!app || drawing.value) return
  if (!isGeometric(props.questionText)) {
    error.value = '这道题看起来不是几何题，可能无法绘图'
  }
  drawing.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/ai/geogebra', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_text: props.questionText, subject: props.subject || '' }),
    })
    const r = await resp.json()
    const commands: string[] = (r.data?.commands) || []
    cmdList.value = commands
    if (!commands.length) {
      error.value = 'AI 未能生成绘图命令'
      return
    }
    app.newConstruction()
    let fail = 0
    for (const cmd of commands) {
      try {
        app.evalCommand(cmd)
      } catch { fail++ }
    }
    if (fail > 0) error.value = `有 ${fail} 条命令执行失败（已忽略），其余绘图完成`
    else error.value = ''
  } catch {
    error.value = 'AI 绘图失败，请重试'
  } finally {
    drawing.value = false
  }
}

function clearBoard() {
  cmdList.value = []
  if (app) { try { app.newConstruction() } catch { /* ignore */ } }
}

watch(() => props.open, async (v) => {
  if (v) {
    await initApplet()
    // 打开时若题目是几何题，自动 AI 绘图
    if (app && isGeometric(props.questionText)) aiDraw()
  }
})

onUnmounted(() => {
  try { applet?.remove() } catch { /* ignore */ }
})
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/45" @click.self="emit('close')">
    <div class="bg-card rounded-card w-[760px] max-w-[94vw] flex flex-col shadow-xl">
      <div class="flex items-center px-5 py-3 border-b border-border">
        <span class="text-lg">📐</span>
        <b class="ml-2 text-body">几何画板</b>
        <span class="ml-auto text-caption text-textTertiary max-w-[40%] truncate">{{ questionText }}</span>
        <button class="ml-3 text-textTertiary hover:text-error" @click="emit('close')">✕</button>
      </div>
      <div class="p-3 flex items-center gap-2 border-b border-border/60">
        <button class="text-caption bg-primary text-white rounded-btn px-3 py-1.5 disabled:opacity-50"
                :disabled="drawing || loadingLib || !libLoaded" @click="aiDraw">
          {{ drawing ? 'AI 绘图中…' : '🎨 AI 自动绘图' }}
        </button>
        <button class="text-caption border border-border rounded-btn px-3 py-1.5 text-textSecondary hover:border-borderStrong" @click="clearBoard">🗑️ 清空画板</button>
        <span class="text-caption text-textTertiary">也可用上方工具栏手动绘制</span>
      </div>
      <div class="flex" style="min-height: 520px">
        <!-- 左栏：题目与绘图信息（文字都在这里，画板保持干净） -->
        <aside class="w-[240px] shrink-0 border-r border-border/60 p-4 overflow-y-auto bg-bg/30">
          <div class="text-caption text-textTertiary mb-1">📝 题目</div>
          <div class="text-body text-textSecondary mb-4" style="font-size:13px;line-height:1.6">{{ questionText }}</div>
          <div class="text-caption text-textTertiary mb-1">🎨 AI 绘图命令（{{ cmdList.length }}）</div>
          <div v-if="cmdList.length" class="space-y-1">
            <div v-for="(c, i) in cmdList" :key="i" class="text-caption bg-card border border-border/60 rounded-btn px-2 py-1" style="font-family:Consolas,monospace;font-size:11px">{{ c }}</div>
          </div>
          <div v-else class="text-caption text-textTertiary">点「AI 自动绘图」生成图形与命令说明</div>
          <div class="text-caption text-textTertiary mt-4">💡 提示：工具栏可手动添加点/线/圆/多边形</div>
        </aside>
        <!-- 右栏：画板（无代数区，干净） -->
        <div class="flex-1 p-4 bg-bg/40 relative">
          <div :id="containerId" class="ggb-clean bg-white border border-border rounded-card overflow-hidden" />
          <div v-if="loadingLib" class="absolute inset-0 flex flex-col items-center justify-center bg-bg/80 rounded-card">
            <div class="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mb-3" />
            <div class="text-caption text-textTertiary">正在加载 GeoGebra 画板…（本地资源，很快）</div>
          </div>
          <div v-if="error" class="mt-2 text-caption text-warning">{{ error }}</div>
        </div>
      </div>
      <div class="px-5 py-3 border-t border-border flex items-center justify-end">
        <button class="text-caption border border-border rounded-btn px-4 py-2 text-textSecondary" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<style>
/* 该样式未 scoped，直接匹配 GeoGebra 注入的内部 DOM。 */
.ggb-clean .algebraPanel, .ggb-clean .algebraView,
.ggb-clean .gwt-Tree.algebraView { display: none !important; }
</style>
