import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const configured = Boolean(url && anonKey)

// 没配置时给个占位地址，页面照样能打开并提示去填 .env.local
export const supabase = createClient(url || 'http://localhost:54321', anonKey || 'missing-key')

export const THUMB_BUCKET = 'thumbs'

/** 私有桶的缩略图要换成带签名的临时地址才能显示，一次批量换，减少请求。 */
export async function signThumbs(paths: string[], expiresIn = 3600): Promise<Map<string, string>> {
  const result = new Map<string, string>()
  if (paths.length === 0) return result
  const { data, error } = await supabase.storage.from(THUMB_BUCKET).createSignedUrls(paths, expiresIn)
  if (error) throw error
  for (const item of data) {
    if (item.signedUrl && item.path) result.set(item.path, item.signedUrl)
  }
  return result
}
