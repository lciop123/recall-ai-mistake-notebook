import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/questions', name: 'questions', component: () => import('../views/QuestionsView.vue') },
  { path: '/capture', name: 'capture', component: () => import('../views/CaptureView.vue') },
  { path: '/input', name: 'input', component: () => import('../views/InputView.vue') },
  { path: '/review', name: 'review', component: () => import('../views/ReviewView.vue') },
  { path: '/redo', name: 'redo', component: () => import('../views/RedoView.vue') },
  { path: '/flashcards', name: 'flashcards', component: () => import('../views/FlashcardsView.vue') },
  { path: '/stats', name: 'stats', component: () => import('../views/StatsView.vue') },
  { path: '/chat', name: 'chat', component: () => import('../views/ChatView.vue') },
  { path: '/help', name: 'help', component: () => import('../views/HelpView.vue') },
]

export default createRouter({ history: createWebHistory(), routes })
