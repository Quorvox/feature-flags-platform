import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? '/api/v1' })

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('ff_token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

export default api
