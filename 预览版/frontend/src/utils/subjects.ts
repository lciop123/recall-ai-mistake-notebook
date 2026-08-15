// 学科 → 颜色映射（不同学科不同颜色）
export const SUBJECT_COLORS: Record<string, string> = {
  '数学': '#007AFF',
  '英语': '#34C759',
  '物理': '#FF9500',
  '化学': '#AF52DE',
  '语文': '#FF2D55',
  '生物': '#5AC8FA',
  '政治': '#FFD60A',
  '历史': '#5856D6',
  '地理': '#FF9500',
  '专业课': '#007AFF',
  '其他': '#AEAEB2',
}

export const SUBJECTS = ['数学', '英语', '物理', '化学', '语文', '生物', '政治', '历史', '地理', '专业课', '其他']

export function subjectColor(s: string): string {
  return SUBJECT_COLORS[s] || '#AEAEB2'
}

// 难度 → 颜色
export function difficultyColor(d: string): string {
  if (d === '易') return '#34C759'
  if (d === '难') return '#FF3B30'
  return '#FF9500'
}

// 动态学科列表（与错题本侧栏同源：有题学科 + 空学科错题本，含数量）
export interface SubjectOption { name: string; count: number }

import { dashboardApi, notebookApi } from '../api'

export async function loadSubjectOptions(): Promise<SubjectOption[]> {
  try {
    const [d, nbs] = await Promise.all([dashboardApi.distributions(), notebookApi.list()])
    const rows: SubjectOption[] = (d.subjects || []).map((s: { name: string; count: number }) => ({ name: s.name, count: s.count }))
    const names = new Set(rows.map(r => r.name))
    for (const nb of nbs) {
      const nm = nb.name.replace(/错题本$/, '')
      if (!names.has(nm) && nm) { rows.push({ name: nm, count: 0 }); names.add(nm) }
    }
    rows.sort((a, b) => b.count - a.count)
    return rows
  } catch {
    return []
  }
}
