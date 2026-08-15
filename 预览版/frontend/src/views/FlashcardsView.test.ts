import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FlashcardsView from './FlashcardsView.vue'

const apiMocks = vi.hoisted(() => ({
  daily: vi.fn(),
  complete: vi.fn(),
}))

vi.mock('../api', () => ({
  planApi: apiMocks,
}))
vi.mock('../api/request', () => ({ toast: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const card = {
  id: 9, notebook_id: null, subject: '数学', knowledge_point: '函数', error_type: '概念不清',
  difficulty: '中', question_text: '求导数', answer: '2x', analysis: '使用幂函数求导法则', mastery_level: 0,
  next_review_at: null, created_at: '2026-08-15T00:00:00',
}

describe('FlashcardsView', () => {
  beforeEach(() => {
    apiMocks.daily.mockResolvedValue({ due: [card] })
    apiMocks.complete.mockResolvedValue({})
  })

  it('先显示题目，翻面后才显示答案和质量按钮', async () => {
    const wrapper = mount(FlashcardsView, {
      global: { stubs: { MarkdownView: { props: ['content'], template: '<div>{{ content }}</div>' } } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('求导数')
    expect(wrapper.text()).not.toContain('使用幂函数求导法则')
    await wrapper.get('button[aria-label="显示答案"]').trigger('click')
    expect(wrapper.text()).toContain('使用幂函数求导法则')
    expect(wrapper.text()).toContain('重新学习')
  })

  it('质量按钮写入对应的 SM-2 质量并进入下一张', async () => {
    const wrapper = mount(FlashcardsView, {
      global: { stubs: { MarkdownView: { props: ['content'], template: '<div>{{ content }}</div>' } } },
    })
    await flushPromises()
    await wrapper.get('button[aria-label="显示答案"]').trigger('click')
    const rememberButton = wrapper.findAll('button').find(button => button.text().includes('记得'))
    expect(rememberButton).toBeDefined()
    await rememberButton!.trigger('click')
    await flushPromises()
    expect(apiMocks.complete).toHaveBeenCalledWith(9, 4)
    expect(wrapper.text()).toContain('本轮完成')
  })
})
