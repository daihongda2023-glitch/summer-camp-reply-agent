import assert from 'node:assert/strict'
import test from 'node:test'
import type { WorkbenchItem } from '../src/shared/types.ts'
import {
  applyOperationProfile,
  confidenceLabel,
  extractSafeSourceUrl,
  filterWorkbenchItems,
  prioritizeWorkbenchItems,
  recommendedPrimaryAction,
  resolveOperationProfile
} from '../src/renderer/workbench-ux.ts'

function item(overrides: Partial<WorkbenchItem> = {}): WorkbenchItem {
  return {
    message_id: 'message-1',
    event_id: 'event-1',
    group_name: '测试群',
    sender: '学生甲',
    message_time: '2026-08-03 10:00:00',
    question: '报名入口在哪里？',
    source: 'weflow_live',
    summary: '',
    status: '待审核',
    replied: false,
    mode: 'draft',
    reply: '请查看群公告。',
    trigger_reasons: [],
    matched_keywords: [],
    recommendation: '人工确认',
    engine_action: 'review',
    intent: 'signup',
    answer_source: '资料：https://example.com/guide',
    confidence: 0.75,
    generation_mode: 'ai',
    generation_model: 'deepseek-v4-pro',
    generation_error: '',
    semantic_status: 'ok',
    semantic_intent: 'signup',
    semantic_question: '报名入口在哪里',
    semantic_confidence: 0.8,
    semantic_model: 'deepseek-v4-pro',
    semantic_error: '',
    faq_confidence: 0.7,
    rag_confidence: 0.4,
    rag_query: '',
    reason: '',
    review_status: 'pending_review',
    review_status_label: '待审核',
    match_status: 'matched',
    match_status_label: '已触发',
    unmatched_reasons: [],
    unmatched_reason_labels: [],
    review_action: '',
    review_note: '',
    created_at: '2026-08-03T10:00:00+08:00',
    updated_at: '2026-08-03T10:00:00+08:00',
    completed_at: '',
    ...overrides
  }
}

test('三种业务模式与底层开关双向一致', () => {
  const settings = {
    base_url: '', token_env: '', group_name: '', session_id: '', keywords: [],
    poll_interval_seconds: 5, enabled: true, show_debug_config: false,
    send_mode: 'manual_confirm', debug_review_mode: true
  }

  assert.equal(resolveOperationProfile(settings), 'safe_review')
  assert.equal(resolveOperationProfile({ ...settings, debug_review_mode: false }), 'assisted')
  assert.equal(resolveOperationProfile({ ...settings, send_mode: 'auto_send', debug_review_mode: false }), 'automatic')
  assert.deepEqual(
    applyOperationProfile(settings, 'automatic'),
    { ...settings, send_mode: 'auto_send', debug_review_mode: false }
  )
})

test('置信度等级在边界值上稳定', () => {
  assert.equal(confidenceLabel(0.8), '高')
  assert.equal(confidenceLabel(0.5), '中')
  assert.equal(confidenceLabel(0.49), '低')
})

test('推荐主操作随模式和填入状态变化', () => {
  const pending = item()
  assert.equal(recommendedPrimaryAction('assisted', pending, false), 'paste')
  assert.equal(recommendedPrimaryAction('assisted', pending, true), 'confirm_sent')
  assert.equal(recommendedPrimaryAction('automatic', pending, false), 'escalate')
  assert.equal(recommendedPrimaryAction('automatic', item({ review_status: 'sent' }), false), 'none')
})

test('搜索覆盖问题、发送人、回复和来源', () => {
  const items = [item(), item({ message_id: 'message-2', sender: '老师乙', question: '住宿怎么安排？' })]
  assert.deepEqual(filterWorkbenchItems(items, '老师').map((row) => row.message_id), ['message-2'])
  assert.deepEqual(filterWorkbenchItems(items, '群公告').map((row) => row.message_id), ['message-1', 'message-2'])
  assert.deepEqual(filterWorkbenchItems(items, 'example.com').map((row) => row.message_id), ['message-1', 'message-2'])
})

test('只提取 http 与 https 来源链接', () => {
  assert.equal(extractSafeSourceUrl('来源：https://example.com/a?b=1。'), 'https://example.com/a?b=1')
  assert.equal(extractSafeSourceUrl('javascript:alert(1)'), '')
})

test('队列优先展示未命中、低置信度和较早到达的待处理消息', () => {
  const rows = [
    item({ message_id: 'sent', review_status: 'sent', confidence: 0.1 }),
    item({ message_id: 'high', confidence: 0.9 }),
    item({ message_id: 'later-low', confidence: 0.2, match_status: 'unmatched', created_at: '2026-08-03T11:00:00+08:00' }),
    item({ message_id: 'earlier-low', confidence: 0.2, match_status: 'unmatched', created_at: '2026-08-03T09:00:00+08:00' })
  ]

  assert.deepEqual(
    prioritizeWorkbenchItems(rows).map((row) => row.message_id),
    ['earlier-low', 'later-low', 'high', 'sent']
  )
})
