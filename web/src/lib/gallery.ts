import type { ImageRow } from './types'

export type SortKey = 'newest' | 'sharpest' | 'largest' | 'brightest'

export interface GalleryFilter {
  minBlur: number
  hideDuplicates: boolean
  jobId: number | null
  sort: SortKey
}

export const defaultFilter: GalleryFilter = { minBlur: 0, hideDuplicates: true, jobId: null, sort: 'newest' }

const comparators: Record<SortKey, (a: ImageRow, b: ImageRow) => number> = {
  newest: (a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id,
  sharpest: (a, b) => b.blur_score - a.blur_score,
  largest: (a, b) => b.width * b.height - a.width * a.height,
  brightest: (a, b) => b.brightness - a.brightness,
}

export function applyFilter(images: ImageRow[], f: GalleryFilter): ImageRow[] {
  return images
    .filter((img) => img.blur_score >= f.minBlur)
    .filter((img) => !f.hideDuplicates || img.dup_of === null)
    .filter((img) => f.jobId === null || img.job_id === f.jobId)
    .sort(comparators[f.sort])
}

/** 每张"组首图"有几张近似重复的图挂在它下面。 */
export function duplicateCounts(images: ImageRow[]): Map<number, number> {
  const counts = new Map<number, number>()
  for (const img of images) {
    if (img.dup_of !== null) counts.set(img.dup_of, (counts.get(img.dup_of) ?? 0) + 1)
  }
  return counts
}

/** 清晰度分档：拉普拉斯方差没有绝对单位，阈值是初始值，用真实图片跑过后再校准。 */
export function sharpnessLabel(blur: number): '清晰' | '一般' | '模糊' {
  if (blur >= 300) return '清晰'
  if (blur >= 80) return '一般'
  return '模糊'
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** 新图到达时（Realtime 推送）按 id 去重合并，避免和首次加载的数据重复。 */
export function mergeById<T extends { id: number }>(list: T[], incoming: T): T[] {
  const idx = list.findIndex((x) => x.id === incoming.id)
  if (idx === -1) return [incoming, ...list]
  const copy = list.slice()
  copy[idx] = incoming
  return copy
}
