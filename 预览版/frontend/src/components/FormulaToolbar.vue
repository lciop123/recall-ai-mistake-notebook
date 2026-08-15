<script setup lang="ts">
const emit = defineEmits<{ (e: 'insert', value: string): void }>()

const formulas = [
  { label: '分数', value: '$\\frac{分子}{分母}$' },
  { label: '根号', value: '$\\sqrt{内容}$' },
  { label: '上标', value: '$x^{2}$' },
  { label: '下标', value: '$a_{n}$' },
  { label: '积分', value: '$∫_{a}^{b}$' },
  { label: '求和', value: '$∑_{i=1}^{n}$' },
]
</script>

<template>
  <div class="flex items-center gap-1.5 flex-wrap text-caption">
    <span class="text-textTertiary mr-1">插入公式</span>
    <button v-for="item in formulas" :key="item.label" type="button"
            class="border border-border rounded-btn px-2 py-1 text-textSecondary hover:border-primary hover:text-primary transition-colors"
            @click="emit('insert', item.value)">
      {{ item.label }}
    </button>
  </div>
</template>
