import { defineStore } from 'pinia'
import api from '../api/client'

export type FlagType = 'boolean' | 'number' | 'string' | 'json'
export interface Flag {
  key: string; name: string; description: string; type: FlagType
  enabled: boolean; value: unknown; rollout_percentage: number; version: number
}

export const useFlagsStore = defineStore('flags', {
  state: () => ({ flags: [] as Flag[], loading: false, error: '' as string }),
  actions: {
    async login(email: string, password: string) {
      const { data } = await api.post('/auth/login', { email, password })
      localStorage.setItem('ff_token', data.access_token)
    },
    async fetch() {
      this.loading = true; this.error = ''
      try { this.flags = (await api.get('/admin/flags')).data }
      catch (e: unknown) { this.error = 'load failed (need login?)' }
      finally { this.loading = false }
    },
    async toggle(f: Flag) {
      const { data } = await api.patch(`/admin/flags/${f.key}`, { enabled: !f.enabled })
      Object.assign(f, data)
    },
    async create(payload: Omit<Flag, 'version'>) {
      await api.post('/admin/flags', payload)
      await this.fetch()
    }
  }
})
