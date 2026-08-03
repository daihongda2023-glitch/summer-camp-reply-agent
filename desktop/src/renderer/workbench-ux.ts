import type { OperationProfile, WeChatBridgeSettings, WorkbenchItem } from '../shared/types'

export type ConfidenceLevel = 'high' | 'medium' | 'low'
export type PrimaryAction = 'paste' | 'confirm_sent' | 'escalate' | 'none'

export const OPERATION_PROFILE_OPTIONS: Array<{
  value: OperationProfile
  label: string
  description: string
}> = [
  {
    value: 'safe_review',
    label: '安全试运行',
    description: '所有消息都进入待处理，适合调试规则和检查回复。'
  },
  {
    value: 'assisted',
    label: '人工辅助',
    description: '系统生成草稿，由你确认后发送。'
  },
  {
    value: 'automatic',
    label: '自动回复',
    description: 'FAQ 或 RAG 任一命中即发送，均未命中时转入待处理。'
  }
]

export function resolveOperationProfile(settings: Pick<WeChatBridgeSettings, 'send_mode' | 'debug_review_mode'>): OperationProfile {
  if (settings.debug_review_mode) return 'safe_review'
  if (settings.send_mode === 'auto_send') return 'automatic'
  return 'assisted'
}

export function applyOperationProfile(
  settings: WeChatBridgeSettings,
  operationProfile: OperationProfile
): WeChatBridgeSettings {
  return {
    ...settings,
    send_mode: operationProfile === 'automatic' ? 'auto_send' : 'manual_confirm',
    debug_review_mode: operationProfile === 'safe_review'
  }
}

export function operationProfileLabel(profile: OperationProfile): string {
  return OPERATION_PROFILE_OPTIONS.find((option) => option.value === profile)?.label ?? '人工辅助'
}

export function confidenceLevel(score: number): ConfidenceLevel {
  if (score >= 0.8) return 'high'
  if (score >= 0.5) return 'medium'
  return 'low'
}

export function confidenceLabel(score: number): string {
  return { high: '高', medium: '中', low: '低' }[confidenceLevel(score)]
}

export function recommendedPrimaryAction(
  operationProfile: OperationProfile,
  item: WorkbenchItem | undefined,
  pasted: boolean
): PrimaryAction {
  if (!item || item.review_status !== 'pending_review') return 'none'
  if (pasted) return 'confirm_sent'
  if (operationProfile === 'automatic') return 'escalate'
  return 'paste'
}

export function filterWorkbenchItems(items: WorkbenchItem[], query: string): WorkbenchItem[] {
  const keyword = query.trim().toLocaleLowerCase('zh-CN')
  const matched = keyword ? items.filter((item) => [
    item.question,
    item.sender,
    item.group_name,
    item.reply,
    item.answer_source,
    item.review_status_label
  ].some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(keyword))) : items
  return prioritizeWorkbenchItems(matched)
}

export function prioritizeWorkbenchItems(items: WorkbenchItem[]): WorkbenchItem[] {
  return [...items].sort((left, right) => {
    const pendingDifference = Number(left.review_status !== 'pending_review') - Number(right.review_status !== 'pending_review')
    if (pendingDifference) return pendingDifference
    const matchDifference = Number(left.match_status !== 'unmatched') - Number(right.match_status !== 'unmatched')
    if (matchDifference) return matchDifference
    const confidenceDifference = left.confidence - right.confidence
    if (confidenceDifference) return confidenceDifference
    return String(left.created_at).localeCompare(String(right.created_at))
  })
}

export function extractSafeSourceUrl(source: string): string {
  const match = source.match(/https?:\/\/[^\s，。；、)\]}]+/i)
  return match?.[0] ?? ''
}

export function answerSourceLabel(item: WorkbenchItem): string {
  if (item.faq_confidence > 0 && item.rag_confidence > 0) return 'FAQ + RAG'
  if (item.faq_confidence > 0) return 'FAQ'
  if (item.rag_confidence > 0) return 'RAG'
  return item.generation_mode === 'ai' ? 'AI 语义判断' : '资料未命中'
}

export function decisionSummary(item: WorkbenchItem): string {
  if (item.review_status !== 'pending_review') return '这条消息已经完成处理。'
  if (item.faq_confidence > 0 || item.rag_confidence > 0) return '已找到可用资料，请检查回复内容。'
  return item.reason || item.unmatched_reason_labels.join('、') || '现有资料不足，建议人工确认。'
}
