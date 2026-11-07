<script setup lang="ts">
import type { RealtimeChannel } from '@supabase/supabase-js'
import { onMounted, onUnmounted, ref } from 'vue'
import { mergeById } from '../lib/gallery'
import { supabase } from '../lib/supabase'
import type { CrawlJob } from '../lib/types'

const props = defineProps<{ userId: string; selected: number | null }>()
const emit = defineEmits<{ select: [jobId: number | null] }>()

const jobs = ref<CrawlJob[]>([])
const url = ref('https://books.toscrape.com/')
const maxImages = ref(20)
const busy = ref(false)
const error = ref('')
let channel: RealtimeChannel | null = null

const statusText: Record<CrawlJob['status'], string> = {
  pending: '排队中',
  running: '处理中',
  done: '完成',
  failed: '失败',
}

async function load() {
  const { data, error: err } = await supabase
    .from('crawl_jobs')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(50)
  if (err) error.value = err.message
  else jobs.value = data as CrawlJob[]
}

async function submit() {
  busy.value = true
  error.value = ''
  // user_id 由数据库默认值 auth.uid() 填，RLS 也会校验，前端不用传
  const { error: err } = await supabase
    .from('crawl_jobs')
    .insert({ seed_url: url.value.trim(), max_images: maxImages.value })
  busy.value = false
  if (err) error.value = err.message
}

onMounted(async () => {
  await load()
  channel = supabase
    .channel(`jobs-${props.userId}`)
    .on(
      'postgres_changes',
      { event: '*', schema: 'public', table: 'crawl_jobs', filter: `user_id=eq.${props.userId}` },
      (payload) => {
        if (payload.eventType === 'DELETE') return
        jobs.value = mergeById(jobs.value, payload.new as CrawlJob)
      },
    )
    .subscribe()
})
onUnmounted(() => {
  if (channel) supabase.removeChannel(channel)
})
</script>

<template>
  <aside class="card jobs">
    <form class="new-job" @submit.prevent="submit">
      <h2>新建采集任务</h2>
      <label>页面网址 <input v-model="url" type="url" required /></label>
      <label>最多保存 <input v-model.number="maxImages" type="number" min="1" max="200" /> 张</label>
      <button :disabled="busy">{{ busy ? '提交中…' : '开始采集' }}</button>
      <p class="muted small">只抓 robots.txt 允许的公开页面，同一站点每秒最多一次请求。</p>
      <p v-if="error" class="error">{{ error }}</p>
    </form>

    <h2>任务</h2>
    <button class="ghost small" :class="{ active: selected === null }" @click="emit('select', null)">
      全部图片
    </button>
    <ul>
      <li
        v-for="job in jobs"
        :key="job.id"
        :class="{ active: selected === job.id }"
        @click="emit('select', job.id)"
      >
        <span class="badge" :class="job.status">{{ statusText[job.status] }}</span>
        <span class="url" :title="job.seed_url">{{ job.seed_url }}</span>
        <span v-if="job.status === 'done'" class="muted small">
          保存 {{ job.stats.saved ?? 0 }} · 重复 {{ job.stats.duplicates ?? 0 }} · 找到 {{ job.stats.found ?? 0 }}
        </span>
        <span v-if="job.error" class="error small">{{ job.error }}</span>
      </li>
    </ul>
  </aside>
</template>
