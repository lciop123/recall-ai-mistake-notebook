export interface Notebook {
  id: number
  name: string
  color: string
  count: number
  created_at: string
}

export interface Question {
  id: number
  notebook_id: number | null
  subject: string
  knowledge_point: string
  error_type: string
  error_detail?: string
  difficulty: string
  question_text: string
  answer: string
  analysis: string
  mastery_level: number
  image_path?: string | null
  image_url?: string | null
  next_review_at: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface VariantQuestion {
  id: number
  question_text: string
  options: string[]
  answer: string
  analysis: string
  knowledge_point?: string
  image_url?: string | null
  is_variant: boolean
}

export interface ReviewResult {
  id: number
  correct: boolean
  score: number
  analysis: string
  answer: string
  first_error_step: string
  next_hint: string
}

export interface CaptureQuestion {
  temp_id: number
  question_text: string
  answer: string
  analysis: string
  subject: string
  knowledge_point: string
  error_type: string
  error_detail?: string
  difficulty: string
  type?: string
  exists?: boolean
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  image_url?: string | null
}

export interface Conversation {
  id: number
  title: string
  last: string
  updated_at: string
}
