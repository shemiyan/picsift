<script setup lang="ts">
import type { Session } from '@supabase/supabase-js'
import { onMounted, onUnmounted, ref } from 'vue'
import ImageGallery from './components/ImageGallery.vue'
import JobPanel from './components/JobPanel.vue'
import LoginForm from './components/LoginForm.vue'
import { configured, supabase } from './lib/supabase'

const session = ref<Session | null>(null)
const ready = ref(false)
const selectedJob = ref<number | null>(null)
let unsubscribe = () => {}

onMounted(async () => {
  if (!configured) {
    ready.value = true
    return
  }
  const { data } = await supabase.auth.getSession()
  session.value = data.session
  ready.value = true
  const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => (session.value = s))
  unsubscribe = () => sub.subscription.unsubscribe()
})
onUnmounted(() => unsubscribe())

async function signOut() {
  await supabase.auth.signOut()
}
</script>

<template>
  <header class="topbar">
    <h1>PicSift <small>公开图片采集与筛选</small></h1>
    <div v-if="session" class="user">
      {{ session.user.email }}
      <button class="ghost" @click="signOut">退出</button>
    </div>
  </header>

  <main v-if="!ready" class="center muted">加载中…</main>
  <main v-else-if="!configured" class="center">
    <div class="card notice">
      还没配置 Supabase：把 <code>web/.env.example</code> 复制成 <code>web/.env.local</code>，
      填上项目地址和 Publishable key 后重启 <code>npm run dev</code>。
    </div>
  </main>
  <main v-else-if="!session" class="center">
    <LoginForm />
  </main>
  <main v-else class="layout">
    <JobPanel :user-id="session.user.id" :selected="selectedJob" @select="selectedJob = $event" />
    <ImageGallery :user-id="session.user.id" :job-id="selectedJob" />
  </main>
</template>
