export async function api<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(`/api${path}`, { method: method || (body === undefined ? 'GET' : 'POST'), headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!response.headers.get('content-type')?.includes('application/json')) throw new Error(`服务返回异常 (${response.status})，请检查后端运行状态`)
  const data = await response.json()
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item: {msg: string}) => item.msg).join('；') : data.detail
    throw new Error(data.message || detail || `请求失败 (${response.status})`)
  }
  return data as T
}
