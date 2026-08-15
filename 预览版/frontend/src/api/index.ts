import http from './request'
import type { Notebook, Question, Page, VariantQuestion, ReviewResult, CaptureQuestion, Conversation, ChatMessage } from '../types'

// 错题本
export const notebookApi = {
  list: () => http.get<never, Notebook[]>('/notebooks'),
  create: (name: string, color: string) => http.post<never, Notebook>('/notebooks', { name, color }),
  update: (id: number, data: Partial<Pick<Notebook, 'name' | 'color'>>) => http.patch<never, Notebook>(`/notebooks/${id}`, data),
  remove: (id: number) => http.delete(`/notebooks/${id}`),
}

// 错题
export const questionApi = {
  create: (data: Partial<Question>, autoClassify = true) => http.post<never, Question>('/questions', data, { params: { auto_classify: autoClassify } }),
  classifyPreview: (questionText: string) => http.post<never, Pick<Question, 'subject' | 'knowledge_point' | 'error_type' | 'error_detail' | 'difficulty'>>('/questions/classify-preview', { question_text: questionText }),
  list: (params: Record<string, unknown>) => http.get<never, Page<Question>>('/questions', { params }),
  search: (q: string) => http.get<never, Question[]>('/questions/search', { params: { q } }),
  update: (id: number, data: Partial<Question>) => http.patch<never, Question>(`/questions/${id}`, data),
  bulkUpdate: (ids: number[], data: Pick<Partial<Question>, 'subject' | 'knowledge_point' | 'error_type' | 'difficulty'>) => http.patch<never, { updated: number; skipped_ids: number[] }>('/questions/bulk', { ids, ...data }),
  similar: (id: number, limit = 5) => http.get<never, (Question & { similarity: number; reasons: string[] })[]>(`/questions/${id}/similar`, { params: { limit } }),
  mergeDuplicate: (primaryId: number, duplicateId: number) => http.post<never, { primary: Question; merged_question_id: number; migrated_review_logs: number }>('/questions/merge-duplicate', { primary_id: primaryId, duplicate_id: duplicateId }),
  remove: (id: number) => http.delete(`/questions/${id}`),
  deleteBySubject: (subject: string) => http.delete<never, { deleted: number }>(`/questions/by-subject/${encodeURIComponent(subject)}`),
  uploadQuestionImage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<never, { image_path: string; url: string }>('/questions/image', fd)
  },
}

// 识图录入
export const captureApi = {
  upload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<never, { task_id: string }>('/capture/upload', fd)
  },
  task: (taskId: string) => http.get<never, { status: string; message: string; progress: string; stage?: 'prepare' | 'ocr' | 'split' | 'classify' | 'done' | 'failed'; elapsed_hint?: string; questions: CaptureQuestion[] }>(`/capture/tasks/${taskId}`),
  importSelected: (taskId: string, questionIds: number[]) => http.post<never, { imported: number; skipped: number }>('/capture/import', { task_id: taskId, question_ids: questionIds }),
}

// 复习
export const reviewApi = {
  // 出题接口 AI 生成较慢，单独放宽超时（120s）
  generate: (data: { notebook_id?: number | null; subject?: string | null; count: number }) =>
    http.post<never, { review_id: string; questions: VariantQuestion[]; source: string }>('/reviews/generate', data, { timeout: 120000 }),
  generateExam: (data: { exam_date: string; subject?: string | null; count: number }) =>
    http.post<never, { review_id: string; questions: VariantQuestion[]; source: string; exam_date: string; recommended_minutes: number; knowledge_distribution: Record<string, number> }>('/reviews/exam/generate', data, { timeout: 120000 }),
  submit: (reviewId: string, answers: { question_id: number; answer: string }[]) =>
    http.post<never, { total: number; correct: number; score: number; results: ReviewResult[] }>(`/reviews/${reviewId}/submit`, { answers }, { timeout: 120000 }),
  history: (page = 1) => http.get<never, Page<Record<string, unknown>>>('/reviews/history', { params: { page } }),
  addQuestion: (reviewId: string, questionId: number) => http.post<never, Question>(`/reviews/${reviewId}/add-question`, { question_id: questionId }),
}

export const redoApi = {
  // AI 判断/批改较慢，放宽超时（120s）
  judgeType: (questionId: number) => http.post<never, { type: 'choice' | 'fill' | 'essay'; options: string[] }>('/redo/type', { question_id: questionId }, { timeout: 120000 }),
  grade: (questionId: number, answer: string, imagePath?: string, type?: string, subject?: string, reviewType: 'redo' | 'daily' | 'exam' = 'redo') => http.post<never, { correct: boolean; score: number; feedback: string; first_error_step: string; next_hint: string }>('/redo/grade', { question_id: questionId, answer, image_path: imagePath, type, subject, review_type: reviewType }, { timeout: 120000 }),
}

// 复习计划
export const planApi = {
  daily: (subject?: string, limit?: number, date?: string, knowledgePoint?: string) => http.get<never, { date: string; due: Question[]; overdue_count: number; total_due: number; remaining_count: number; daily_limit: number }>('/review-plan/daily', { params: { subject, limit, d: date, knowledge_point: knowledgePoint } }),
  calendar: (month?: string, subject?: string) => http.get<never, { month: string; days: { date: string; due: number; completed: number }[] }>('/review-plan/calendar', { params: { month, subject } }),
  complete: (questionId: number, quality: number) => http.post('/review-plan/complete', { question_id: questionId, quality }),
  exam: (examDate: string) => http.post<never, { days: number; plan: { date: string; count: number }[]; total: number }>('/review-plan/exam', { exam_date: examDate }),
  weekly: () => http.get<never, Record<string, unknown>>('/review-plan/weekly'),
}

// 看板
export const dashboardApi = {
  overview: (subject?: string) => http.get<never, { total: number; due_today: number; week_accuracy: number; streak: number }>('/dashboard/overview', { params: { subject } }),
  trend: (days = 7, subject?: string) => http.get<never, { date: string; collected: number; reviewed: number; accuracy: number }[]>('/dashboard/trend', { params: { days, subject } }),
  graph: (subject?: string) => http.get<never, { nodes: { id: string; name: string; group: string; count: number; mastery: number }[]; links: { source: string; target: string; kind?: 'belongs' | 'related'; keywords?: string[] }[] }>('/dashboard/knowledge-graph', { params: { subject } }),
  distributions: (subject?: string) => http.get<never, { subjects: { name: string; count: number }[]; error_types: { name: string; count: number }[] }>('/dashboard/distributions', { params: { subject } }),
  learningPlan: (subject?: string) => http.get<never, { subject: string; knowledge_point: string; question_count: number; wrong_count: number; overdue_count: number; mastery: number; error_type: string; recommended_count: number; action: string; priority: number }[]>('/dashboard/learning-plan', { params: { subject } }),
  alerts: (subject?: string) => http.get<never, { type: 'overdue' | 'weak'; title: string; item: { subject: string; knowledge_point: string; recommended_count: number } }[]>('/dashboard/alerts', { params: { subject } }),
}

// 对话
export const chatApi = {
  conversations: () => http.get<never, Conversation[]>('/chat/conversations'),
  create: () => http.post<never, Conversation>('/chat/conversations'),
  createInherited: (fromId: number, lastCount = 20) => http.post<never, Conversation & { inherit_from_id?: number; inherit_last_count?: number }>('/chat/conversations/inherit', { from_id: fromId, last_count: lastCount }),
  messages: (id: number) => http.get<never, ChatMessage[]>(`/chat/conversations/${id}/messages`),
  remove: (id: number) => http.delete(`/chat/conversations/${id}`),
  regenerate: (id: number, messageId: number) => http.post<never, { last_user_content: string; last_user_image?: string | null }>(`/chat/conversations/${id}/regenerate`, { message_id: messageId }),
  stream: (conversationId: number | null, message: string, imagePath?: string) => http.post('/chat/stream', { conversation_id: conversationId, message, image_path: imagePath }),
  uploadImage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<never, { image_path: string; url: string }>('/chat/images', fd)
  },
  addQuestion: (id: number, messageId: number) => http.post<never, Question>(`/chat/conversations/${id}/add-question`, { message_id: messageId }),
  addedQuestions: (id: number) => http.get<never, { message_id: number; question_id: number }[]>(`/chat/conversations/${id}/added-questions`),
}

export const aiApi = {
  answer: (questionText: string, subject?: string) => http.post<never, { answer: string; analysis: string }>('/ai/answer', { question_text: questionText, subject }),
}

// 导出
export const exportApi = {
  markdown: (params: Record<string, unknown> = {}) => http.get<never, Blob>('/export/markdown', { params, responseType: 'blob' }),
  pdf: (params: Record<string, unknown> = {}) => http.get<never, Blob>('/export/pdf', { params, responseType: 'blob' }),
  weeklyMarkdown: (params: Record<string, unknown> = {}) => http.get<never, Blob>('/export/weekly/markdown', { params, responseType: 'blob' }),
  weeklyPdf: (params: Record<string, unknown> = {}) => http.get<never, Blob>('/export/weekly/pdf', { params, responseType: 'blob' }),
}
