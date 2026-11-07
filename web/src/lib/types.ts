export type JobStatus = 'pending' | 'running' | 'done' | 'failed'

export interface CrawlJob {
  id: number
  seed_url: string
  max_images: number
  status: JobStatus
  stats: Partial<Record<'found' | 'downloaded' | 'saved' | 'duplicates' | 'skipped_robots' | 'failed', number>>
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface ImageRow {
  id: number
  job_id: number
  source_url: string
  page_url: string
  thumb_path: string
  width: number
  height: number
  bytes: number
  format: string | null
  blur_score: number
  brightness: number
  colors: { hex: string; ratio: number }[]
  dup_of: number | null
  created_at: string
}
