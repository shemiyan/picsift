<script setup lang="ts">
import type { RealtimeChannel } from '@supabase/supabase-js'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  applyFilter,
  defaultFilter,
  duplicateCounts,
  formatBytes,
  mergeById,
  sharpnessLabel,
  type GalleryFilter,
} from '../lib/gallery'
import { signThumbs, supabase } from '../lib/supabase'
import type { ImageRow } from '../lib/types'

const props = defineProps<{ userId: string; jobId: number | null }>()

const images = ref<ImageRow[]>([])
const thumbUrls = ref(new Map<string, string>())
const filter = reactive<GalleryFilter>({ ...defaultFilter })
const error = ref('')
let channel: RealtimeChannel | null = null

watch(
  () => props.jobId,
  (id) => (filter.jobId = id),
  { immediate: true },
)

const visible = computed(() => applyFilter(images.value, filter))
const dupCounts = computed(() => duplicateCounts(images.value))

async function ensureThumbs(rows: ImageRow[]) {
  const missing = rows.map((r) => r.thumb_path).filter((p) => !thumbUrls.value.has(p))
  if (missing.length === 0) return
  try {
    const signed = await signThumbs(missing)
    thumbUrls.value = new Map([...thumbUrls.value, ...signed])
  } catch (e) {
    error.value = (e as Error).message
  }
}

// 签名地址 1 小时过期，网络抖动也可能让某张图加载失败：失败时重签一次再试，只试一次避免死循环
const retried = new Set<string>()
async function onThumbError(img: ImageRow) {
  if (retried.has(img.thumb_path)) return
  retried.add(img.thumb_path)
  const next = new Map(thumbUrls.value)
  next.delete(img.thumb_path)
  thumbUrls.value = next
  await ensureThumbs([img])
}

async function load() {
  const { data, error: err } = await supabase
    .from('images')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(500)
  if (err) {
    error.value = err.message
    return
  }
  images.value = data as ImageRow[]
  await ensureThumbs(images.value)
}

async function remove(img: ImageRow) {
  const { error: err } = await supabase.from('images').delete().eq('id', img.id)
  if (err) error.value = err.message
  else images.value = images.value.filter((x) => x.id !== img.id)
}

onMounted(async () => {
  await load()
  channel = supabase
    .channel(`images-${props.userId}`)
    .on(
      'postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'images', filter: `user_id=eq.${props.userId}` },
      async (payload) => {
        const row = payload.new as ImageRow
        images.value = mergeById(images.value, row)
        await ensureThumbs([row])
      },
    )
    .subscribe()
})
onUnmounted(() => {
  if (channel) supabase.removeChannel(channel)
})
</script>

<template>
  <section class="gallery">
    <div class="card toolbar">
      <label>
        清晰度 ≥ {{ filter.minBlur }}
        <input v-model.number="filter.minBlur" type="range" min="0" max="1000" step="10" />
      </label>
      <label><input v-model="filter.hideDuplicates" type="checkbox" /> 隐藏近似重复</label>
      <label>
        排序
        <select v-model="filter.sort">
          <option value="newest">最新</option>
          <option value="sharpest">最清晰</option>
          <option value="largest">分辨率最高</option>
          <option value="brightest">最亮</option>
        </select>
      </label>
      <span class="muted">显示 {{ visible.length }} / {{ images.length }} 张</span>
    </div>
    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="visible.length === 0" class="center muted">还没有图片，先在左边新建一个采集任务。</div>
    <div class="grid">
      <figure v-for="img in visible" :key="img.id" class="card tile">
        <a :href="img.source_url" target="_blank" rel="noopener noreferrer">
          <img
            v-if="thumbUrls.get(img.thumb_path)"
            :src="thumbUrls.get(img.thumb_path)"
            :alt="img.source_url"
            loading="lazy"
            @error="onThumbError(img)"
          />
          <div v-else class="placeholder" />
        </a>
        <figcaption>
          <div class="swatches">
            <span
              v-for="c in img.colors"
              :key="c.hex"
              :style="{ background: c.hex, flexGrow: c.ratio }"
              :title="`${c.hex} ${Math.round(c.ratio * 100)}%`"
            />
          </div>
          <div class="meta">
            <span>{{ img.width }}×{{ img.height }}</span>
            <span>{{ formatBytes(img.bytes) }}</span>
            <span :class="['sharp', sharpnessLabel(img.blur_score)]">
              {{ sharpnessLabel(img.blur_score) }} {{ Math.round(img.blur_score) }}
            </span>
            <span v-if="dupCounts.get(img.id)" class="dup">+{{ dupCounts.get(img.id) }} 张相似</span>
            <span v-if="img.dup_of !== null" class="dup">重复于 #{{ img.dup_of }}</span>
          </div>
          <button class="ghost small" @click="remove(img)">删除</button>
        </figcaption>
      </figure>
    </div>
  </section>
</template>
