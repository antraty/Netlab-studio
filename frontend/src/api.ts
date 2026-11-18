import type { StatusNode, Topology, VersionInfo } from './types'

export interface User {
  id: string
  email: string
  display_name: string
  role: 'teacher' | 'student'
}
export interface Group {
  id: string
  name: string
  teacher_id: string
  members: number
}
export interface Assignment {
  id: string
  title: string
  group_name: string
  status: 'assigned' | 'in_progress' | 'submitted'
  created_at: number
  submitted_at: number | null
  topology: Topology
}
export interface ServiceProfile {
  id: string
  label: string
  category: string
  status: 'ready' | 'planned' | 'research'
  image: string | null
  command: string[]
  ports: Array<{ container_port: number; protocol: string; host_publishable: boolean }>
  primary_port: number | null
  resources: Record<string, number>
  environment: Array<{ name: string; required: boolean; secret: boolean; purpose: string }>
  constraints: string[]
  deployable: boolean
}

function cookie(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`
  const entry = document.cookie.split('; ').find(value => value.startsWith(prefix))
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : undefined
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = cookie('netlab_csrf')
    if (csrf) headers.set('X-Netlab-CSRF', csrf)
  }
  const response = await fetch(path, { credentials: 'same-origin', ...options, method, headers })
  const body = response.status === 204 ? null : await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body?.detail ?? body?.error ?? `Erreur HTTP ${response.status}`)
  return body as T
}

export const api = {
  services: () => request<{ services: ServiceProfile[] }>('/api/services'),
  authState: () => request<{ has_users: boolean; bootstrap_enabled: boolean }>('/api/auth/state'),
  me: () => request<{ user: User }>('/api/auth/me'),
  login: (email: string, password: string) => request<{ user: User; csrf_token: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  bootstrap: (payload: { bootstrap_token: string; email: string; display_name: string; password: string }) => request<{ user: User; csrf_token: string }>('/api/auth/bootstrap', { method: 'POST', body: JSON.stringify(payload) }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST', body: '{}' }),
  changePassword: (current_password: string, new_password: string) => request<{ ok: boolean; reauthentication_required: boolean }>('/api/auth/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),
  createStudent: (payload: { email: string; display_name: string; password: string }) => request<{ user: User }>('/api/education/users', { method: 'POST', body: JSON.stringify(payload) }),
  users: () => request<{ users: User[] }>('/api/education/users'),
  groups: () => request<{ groups: Group[] }>('/api/education/groups'),
  createGroup: (name: string) => request<{ group: Group }>('/api/education/groups', { method: 'POST', body: JSON.stringify({ name }) }),
  addMember: (groupId: string, email: string) => request<{ ok: boolean }>(`/api/education/groups/${encodeURIComponent(groupId)}/members`, { method: 'POST', body: JSON.stringify({ email }) }),
  assign: (groupId: string, title: string, topology: Topology) => request<{ assignment: { id: string; title: string } }>(`/api/education/groups/${encodeURIComponent(groupId)}/assignments`, { method: 'POST', body: JSON.stringify({ title, topology }) }),
  submissions: (groupId: string) => request<{ submissions: Array<{ assignment_id: string; title: string; email: string; display_name: string; status: string; submitted_at: number | null }> }>(`/api/education/groups/${encodeURIComponent(groupId)}/submissions`),
  myAssignments: () => request<{ assignments: Assignment[] }>('/api/education/my-assignments'),
  cloneAssignment: (assignmentId: string) => request<{ topology: Topology }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/clone`, { method: 'POST', body: '{}' }),
  saveAssignmentTopology: (assignmentId: string, topology: Topology) => request<{ ok: boolean }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/topology`, { method: 'PUT', body: JSON.stringify({ topology }) }),
  submitAssignment: (assignmentId: string) => request<{ ok: boolean }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/submit`, { method: 'POST', body: '{}' }),
  topology: () => request<{ topology: Topology }>('/api/topology'),
  status: () => request<{ nodes: StatusNode[] }>('/api/status'),
  logs: () => request<{ logs: string[] }>('/api/logs'),
  save: (topology: Topology) => request<{ topology: Topology }>('/api/topology', { method: 'POST', body: JSON.stringify({ topology }) }),
  versions: (lab: string) => request<{ lab: string; versions: VersionInfo[] }>(`/api/laboratories/${encodeURIComponent(lab)}/versions`),
  restore: (lab: string, version: number) => request<{ topology: Topology }>(`/api/laboratories/${encodeURIComponent(lab)}/restore/${version}`, { method: 'POST', body: '{}' }),
  clone: (lab: string, newLab: string) => request<{ topology: Topology }>(`/api/laboratories/${encodeURIComponent(lab)}/clone`, { method: 'POST', body: JSON.stringify({ new_lab: newLab }) }),
  export: (lab: string) => request<{ format: string; topology: Topology; versions: VersionInfo[] }>(`/api/laboratories/${encodeURIComponent(lab)}/export`),
  import: (topology: Topology) => request<{ topology: Topology }>('/api/laboratories/import', { method: 'POST', body: JSON.stringify({ topology }) }),
  action: (name: 'up' | 'down' | 'verify') => request<{ ok: boolean; exit_code: number }>(`/api/${name}`, { method: 'POST', body: '{}' }),
  terminal: (node: string, command: string[]) => request<{ ok: boolean; output: string; exit_code: number }>(`/api/nodes/${encodeURIComponent(node)}/terminal`, { method: 'POST', body: JSON.stringify({ command }) }),
}
