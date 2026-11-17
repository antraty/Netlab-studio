import type { StatusNode, Topology } from './types'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) }, ...options })
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail ?? body.error ?? 'Erreur serveur')
  return body as T
}

export const api = {
  topology: () => request<{ topology: Topology }>('/api/topology'),
  status: () => request<{ nodes: StatusNode[] }>('/api/status'),
  logs: () => request<{ logs: string[] }>('/api/logs'),
  save: (topology: Topology) => request<{ topology: Topology }>('/api/topology', { method: 'POST', body: JSON.stringify({ topology }) }),
  action: (name: 'up' | 'down' | 'verify') => request<{ ok: boolean; exit_code: number }>(`/api/${name}`, { method: 'POST', body: '{}' }),
  terminal: (node: string, command: string[]) => request<{ ok: boolean; output: string; exit_code: number }>(`/api/nodes/${encodeURIComponent(node)}/terminal`, { method: 'POST', body: JSON.stringify({ command }) }),
}
