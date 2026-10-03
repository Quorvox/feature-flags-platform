<template>
  <div class="max-w-5xl mx-auto p-6">
    <h1 class="text-2xl font-bold mb-4">Feature Flags — пульт директора</h1>
    <div class="flex gap-2 mb-4">
      <input v-model="email" placeholder="admin@example.com" class="border rounded px-2 py-1" />
      <input v-model="password" type="password" placeholder="пароль" class="border rounded px-2 py-1" />
      <button @click="doLogin" class="bg-black text-white rounded px-3 py-1">Войти</button>
      <button @click="store.fetch()" class="border rounded px-3 py-1">Обновить</button>
    </div>
    <p v-if="store.error" class="text-red-600 mb-2">{{ store.error }}</p>
    <div v-if="store.loading">Загрузка...</div>
    <table v-else class="w-full text-sm border">
      <thead><tr class="bg-gray-100"><th class="p-2 text-left">Key</th><th class="p-2">Вкл</th><th class="p-2">Значение</th><th class="p-2">Rollout</th></tr></thead>
      <tbody>
        <tr v-for="f in store.flags" :key="f.key" class="border-t">
          <td class="p-2 font-mono">{{ f.key }}</td>
          <td class="p-2 text-center"><button @click="store.toggle(f)" :class="f.enabled ? 'bg-green-600' : 'bg-gray-400'" class="text-white rounded px-2">{{ f.enabled ? 'ON' : 'OFF' }}</button></td>
          <td class="p-2"><FlagRow :flag="f" @save="(v) => saveVal(f, v)" /></td>
          <td class="p-2 text-center">{{ f.rollout_percentage }}%</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useFlagsStore, type Flag } from '../stores/flags'
import FlagRow from '../components/FlagRow.vue'
import api from '../api/client'
const store = useFlagsStore()
const email = ref('admin@example.com')
const password = ref('')
async function doLogin() { await store.login(email.value, password.value); await store.fetch() }
async function saveVal(f: Flag, v: unknown) {
  const { data } = await api.patch(`/admin/flags/${f.key}`, { value: v })
  Object.assign(f, data)
}
onMounted(() => { if (localStorage.getItem('ff_token')) store.fetch() })
</script>
