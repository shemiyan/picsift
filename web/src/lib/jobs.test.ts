import { expect, it } from 'vitest'
import { jobSummary } from './jobs'

it('全部已存在时说明原因', () => {
  expect(jobSummary({ found: 20, saved: 0, skipped_existing: 20 })).toBe('保存 0 · 已存在 20 · 找到 20')
})

it('为 0 的跳过原因不显示，按固定顺序排列', () => {
  expect(jobSummary({ found: 6, saved: 3, failed: 1, duplicates: 1, skipped_robots: 0 })).toBe(
    '保存 3 · 重复 1 · 失败 1 · 找到 6',
  )
})

it('统计为空时不报错', () => {
  expect(jobSummary({})).toBe('保存 0 · 找到 0')
})
