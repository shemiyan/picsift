import { describe, expect, it } from 'vitest'
import { applyFilter, defaultFilter, duplicateCounts, formatBytes, mergeById, sharpnessLabel } from './gallery'
import type { ImageRow } from './types'

function img(id: number, over: Partial<ImageRow> = {}): ImageRow {
  return {
    id,
    job_id: 1,
    source_url: `https://e.test/${id}.jpg`,
    page_url: 'https://e.test/',
    thumb_path: `u/1/${id}.jpg`,
    width: 100,
    height: 100,
    bytes: 1000,
    format: 'jpeg',
    blur_score: 100,
    brightness: 0.5,
    colors: [],
    dup_of: null,
    created_at: `2026-11-07T00:00:0${id}Z`,
    ...over,
  }
}

describe('applyFilter', () => {
  const rows = [
    img(1, { blur_score: 500 }),
    img(2, { blur_score: 20 }),
    img(3, { dup_of: 1, blur_score: 450 }),
    img(4, { job_id: 2, width: 1000, height: 800 }),
  ]

  it('默认隐藏重复图并按时间倒序', () => {
    expect(applyFilter(rows, defaultFilter).map((r) => r.id)).toEqual([4, 2, 1])
  })

  it('按清晰度下限、任务、排序组合筛选', () => {
    const f = { minBlur: 50, hideDuplicates: false, jobId: 1, sort: 'sharpest' as const }
    expect(applyFilter(rows, f).map((r) => r.id)).toEqual([1, 3])
  })

  it('不修改原数组', () => {
    const before = rows.map((r) => r.id)
    applyFilter(rows, { ...defaultFilter, sort: 'largest' })
    expect(rows.map((r) => r.id)).toEqual(before)
  })
})

it('duplicateCounts 统计每组重复数', () => {
  const counts = duplicateCounts([img(1), img(2, { dup_of: 1 }), img(3, { dup_of: 1 }), img(4)])
  expect(counts.get(1)).toBe(2)
  expect(counts.has(4)).toBe(false)
})

it('sharpnessLabel 分档', () => {
  expect([sharpnessLabel(500), sharpnessLabel(100), sharpnessLabel(10)]).toEqual(['清晰', '一般', '模糊'])
})

it('formatBytes', () => {
  expect(formatBytes(512)).toBe('512 B')
  expect(formatBytes(2048)).toBe('2.0 KB')
  expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
})

it('mergeById 新增放最前、已有则替换', () => {
  const list = [img(1), img(2)]
  expect(mergeById(list, img(3)).map((r) => r.id)).toEqual([3, 1, 2])
  expect(mergeById(list, img(2, { blur_score: 999 }))[1].blur_score).toBe(999)
})
