import { defineStore } from 'pinia'
import { ref } from 'vue'
import { notebookApi } from '../api'
import type { Notebook } from '../types'

export const useNotebookStore = defineStore('notebook', () => {
  const notebooks = ref<Notebook[]>([])
  const currentId = ref<number | null>(null)

  async function load() {
    notebooks.value = await notebookApi.list()
    // currentId 保持 null（= 全部错题），不自动选中第一个错题本
  }

  async function create(name: string, color: string) {
    const nb = await notebookApi.create(name, color)
    await load()
    currentId.value = nb.id
    return nb
  }

  return { notebooks, currentId, load, create }
})
