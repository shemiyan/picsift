<script setup lang="ts">
import { ref } from 'vue'
import { supabase } from '../lib/supabase'

const email = ref('')
const password = ref('')
const mode = ref<'signin' | 'signup'>('signin')
const busy = ref(false)
const message = ref('')

async function submit() {
  busy.value = true
  message.value = ''
  const creds = { email: email.value.trim(), password: password.value }
  const { error } =
    mode.value === 'signin'
      ? await supabase.auth.signInWithPassword(creds)
      : await supabase.auth.signUp(creds)
  busy.value = false
  if (error) message.value = error.message
  else if (mode.value === 'signup') message.value = '注册成功，如果项目开了邮箱验证，请先去邮箱点确认链接。'
}
</script>

<template>
  <form class="card login" @submit.prevent="submit">
    <h2>{{ mode === 'signin' ? '登录' : '注册' }}</h2>
    <label>邮箱 <input v-model="email" type="email" required autocomplete="email" /></label>
    <label>
      密码
      <input v-model="password" type="password" required minlength="6" autocomplete="current-password" />
    </label>
    <button :disabled="busy">{{ busy ? '请稍候…' : mode === 'signin' ? '登录' : '注册' }}</button>
    <p v-if="message" class="muted">{{ message }}</p>
    <a href="#" @click.prevent="mode = mode === 'signin' ? 'signup' : 'signin'">
      {{ mode === 'signin' ? '没有账号？注册' : '已有账号？登录' }}
    </a>
  </form>
</template>
