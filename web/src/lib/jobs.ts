import type { CrawlJob, JobStatKey } from './types'

const SKIP_LABELS: [JobStatKey, string][] = [
  ['duplicates', '重复'],
  ['skipped_existing', '已存在'],
  ['skipped_robots', 'robots 禁止'],
  ['skipped_not_allowed', '不在允许范围'],
  ['skipped_not_image', '非图片'],
  ['skipped_undecodable', '无法解码'],
  ['failed', '失败'],
]

/** 任务卡片上的一行统计：保存数在前，为 0 的跳过原因不显示，最后是找到的总数。 */
export function jobSummary(stats: CrawlJob['stats']): string {
  const parts = [`保存 ${stats.saved ?? 0}`]
  for (const [key, label] of SKIP_LABELS) {
    const n = stats[key] ?? 0
    if (n > 0) parts.push(`${label} ${n}`)
  }
  parts.push(`找到 ${stats.found ?? 0}`)
  return parts.join(' · ')
}
