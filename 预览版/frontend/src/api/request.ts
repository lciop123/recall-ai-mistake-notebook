import axios from 'axios'

export function toast(message: string, type: 'info' | 'error' = 'info') {
  const el = document.createElement('div')
  el.className = `toast ${type === 'error' ? 'error' : ''}`
  el.textContent = message
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 2500)
}

const http = axios.create({ baseURL: '/api', timeout: 60000 })

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      toast(body.message || '请求失败', 'error')
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body
  },
  (err) => {
    const msg = err.response?.data?.message || (err.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : '网络异常，请重试')
    toast(msg, 'error')
    return Promise.reject(err)
  },
)

export default http
