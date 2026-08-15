<script setup lang="ts">
import { ref } from 'vue'

const active = ref('guide-capture')
const sections: Record<string, { title: string; steps: string[] }[]> = {
  'guide-capture': [
    { title: '📷 识图录入', steps: ['打开「录入」→ 上传图片或 Ctrl+V 粘贴截图', '双模型会依次完成图像识别、题目拆分与结构化，通常需要 30-60 秒', '勾选要导入的题目 → 点击「导入 N 道题」', '识别失败时可用「文本录入」兜底'] },
    { title: '✍️ 文本录入', steps: ['粘贴/输入题干、答案、解析', '点击「AI 自动归类」自动识别学科/知识点/错因', '确认分类后保存'] },
  ],
  'guide-review': [
    { title: '📚 举一反三', steps: ['选择学科/错题本/题数', 'AI 基于你的错题生成变体题', '逐题作答后提交，AI 批改评分', '批改结果自动更新 SM-2 复习计划'] },
    { title: '🗓️ 每日队列', steps: ['首页「今日复习队列」展示到期错题', '完成后打卡，间隔重复自动排期'] },
  ],
  'guide-dashboard': [
    { title: '📊 数据看板', steps: ['查看学习趋势、知识图谱', '图谱默认显示学科、薄弱知识点和重点知识点；其他节点可悬浮查看详情', '点击知识点节点可跳转至错题本，并按该知识点筛选错题', '错因 TOP 榜提示高频错误类型'] },
  ],
  'guide-export': [
    { title: '📄 导出', steps: ['错题本页右上角「导出 MD / PDF」', '可发给老师、家长或打印成册'] },
  ],
  'faq': [
    { title: '识别失败怎么办？', steps: ['确保图片清晰、光线充足；手写体识别率有限，可改用文本录入', '图片需 jpg/png/webp 且 ≤2MB'] },
    { title: '数据存在哪里？', steps: ['所有数据存储在本地 backend/data/ 目录（SQLite + 图片 + 向量库），图片不出本机', '仅题目文本会发送给 DeepSeek API 用于归类/答疑'] },
    { title: 'AI 功能不可用？', steps: ['检查 backend/.env 是否配置 DEEPSEEK_API_KEY', '未配置时，手动录入与复习仍可正常使用'] },
    { title: '如何重置数据？', steps: ['删除 backend/data/recall.db 与 data/chroma 目录后重启后端'] },
  ],
}
</script>

<template>
  <div class="flex max-w-5xl mx-auto px-6 py-8 gap-6">
    <aside class="w-[220px] shrink-0">
      <div class="bg-card border border-border rounded-card p-3 space-y-1">
        <div class="text-caption text-textTertiary px-2 py-1">使用指南</div>
        <button v-for="k in ['guide-capture', 'guide-review', 'guide-dashboard', 'guide-export']" :key="k"
                class="w-full text-left px-3 py-2 rounded-btn text-body"
                :class="active === k ? 'bg-primary/10 text-primary font-medium' : 'text-textSecondary hover:bg-bg'"
                @click="active = k">
          {{ { 'guide-capture': '错题录入', 'guide-review': '复习计划', 'guide-dashboard': '数据看板', 'guide-export': '导出' }[k] }}
        </button>
        <div class="text-caption text-textTertiary px-2 py-1 pt-3">常见问题</div>
        <button class="w-full text-left px-3 py-2 rounded-btn text-body"
                :class="active === 'faq' ? 'bg-primary/10 text-primary font-medium' : 'text-textSecondary hover:bg-bg'"
                @click="active = 'faq'">FAQ</button>
      </div>
    </aside>
    <main class="flex-1">
      <div v-for="sec in sections[active]" :key="sec.title" class="bg-card border border-border rounded-card p-5 mb-4">
        <h2 class="text-h2 mb-3">{{ sec.title }}</h2>
        <ol class="space-y-2">
          <li v-for="(s, i) in sec.steps" :key="i" class="flex gap-3 text-body">
            <span class="w-5 h-5 shrink-0 rounded-full bg-primary/10 text-primary text-xs flex items-center justify-center font-medium">{{ i + 1 }}</span>
            <span>{{ s }}</span>
          </li>
        </ol>
      </div>
    </main>
  </div>
</template>
