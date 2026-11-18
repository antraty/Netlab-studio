import type { StatusNode, Topology, VersionInfo } from './types'

export interface User {
  id: string
  email: string
  display_name: string
  role: 'admin' | 'teacher' | 'student'
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
  runtime_status: 'stopped' | 'running' | 'expired' | 'failed'
  created_at: number
  submitted_at: number | null
  instructions: string
  criteria: string[]
  attempt_count: number
  feedback: string | null
  grade: number | null
  topology: Topology
}
export interface SubmissionAttempt {
  id: string
  attempt: number
  topology: Topology
  submitted_at: number
  feedback: string | null
  grade: number | null
  reviewed_at: number | null
  reviewed_by?: string | null
}
export interface GroupSubmission {
  assignment_id: string
  student_id: string
  title: string
  email: string
  display_name: string
  status: string
  runtime_status: string
  submitted_at: number | null
  attempt_count: number
  feedback: string | null
  grade: number | null
}
export interface Laboratory {
  id: string
  name: string
  status: 'stopped' | 'running' | 'expired' | 'failed'
  created_at: number
  expires_at: number
  role: 'owner' | 'editor' | 'viewer'
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
  volumes: Array<{ target: string; read_only: boolean }>
  healthcheck: string | null
  constraints: string[]
  deployable: boolean
}

export interface ObservabilityLab {
  name: string
  laboratory_id?: string | null
  node_count: number
  running_count: number
  cpu_percent: number | null
  memory_usage_bytes: number | null
  network_rx_bytes: number | null
  network_tx_bytes: number | null
}

export interface ObservabilityNode {
  id: string
  laboratory_id?: string | null
  lab: string
  name: string
  image: string
  state: string
  status: string
  networks: string[]
  ports: string
  cpu_percent: number | null
  memory_usage_bytes: number | null
  memory_limit_bytes: number | null
  memory_percent: number | null
  cpu_limit_cores: number | null
  pids_limit: number | null
  writable_size_bytes: number | null
  block_read_bytes: number | null
  block_write_bytes: number | null
  network_rx_bytes: number | null
  network_tx_bytes: number | null
}

export interface ObservabilityNetwork {
  name: string
  lab: string | null
  laboratory_id?: string | null
  driver: string
  scope: string
}

export interface ObservabilityStorage {
  kind: string
  total_count: number | null
  active_count: number | null
  used_bytes: number | null
  reclaimable_bytes: number | null
}

export interface ObservabilityAlert {
  severity: 'warning' | 'error'
  lab?: string
  node?: string
  message: string
}

export interface ObservabilitySnapshot {
  available: boolean
  collected_at: string | null
  active_lab_count: number
  running_node_count: number
  labs: ObservabilityLab[]
  nodes: ObservabilityNode[]
  networks: ObservabilityNetwork[]
  storage: ObservabilityStorage[]
  alerts: ObservabilityAlert[]
  errors: string[]
  events: string[]
  truncated: boolean
  thresholds: {
    cpu_percent: number
    memory_percent: number
    writable_storage_mb: number
  }
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
  authState: () => request<{ has_users: boolean; bootstrap_enabled: boolean; bootstrap_role: 'admin' | 'teacher' }>('/api/auth/state'),
  me: () => request<{ user: User }>('/api/auth/me'),
  observability: () => request<ObservabilitySnapshot>('/api/observability'),
  login: (email: string, password: string) => request<{ user: User; csrf_token: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  bootstrap: (payload: { bootstrap_token: string; email: string; display_name: string; password: string }) => request<{ user: User; csrf_token: string }>('/api/auth/bootstrap', { method: 'POST', body: JSON.stringify(payload) }),
  acceptInvitation: (token: string, password: string) => request<{ user: User; csrf_token: string }>('/api/auth/invitations/accept', { method: 'POST', body: JSON.stringify({ token, password }) }),
  resetPassword: (token: string, new_password: string) => request<{ ok: boolean }>('/api/auth/password/reset', { method: 'POST', body: JSON.stringify({ token, new_password }) }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST', body: '{}' }),
  changePassword: (current_password: string, new_password: string) => request<{ ok: boolean; reauthentication_required: boolean }>('/api/auth/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),
  createStudent: (payload: { email: string; display_name: string; password: string }) => request<{ user: User }>('/api/education/users', { method: 'POST', body: JSON.stringify(payload) }),
  createTeacher: (payload: { email: string; display_name: string; password: string }) => request<{ user: User }>('/api/education/teachers', { method: 'POST', body: JSON.stringify(payload) }),
  createInvitation: (payload: { email: string; display_name: string; role: 'student' | 'teacher'; group_id?: string | null }) => request<{ invitation: { email: string; display_name: string; role: string }; token: string; expires_in: number }>('/api/education/invitations', { method: 'POST', body: JSON.stringify(payload) }),
  issuePasswordReset: (userId: string) => request<{ token: string; expires_in: number }>(`/api/education/users/${encodeURIComponent(userId)}/password-reset`, { method: 'POST', body: '{}' }),
  users: () => request<{ users: User[] }>('/api/education/users'),
  groups: () => request<{ groups: Group[] }>('/api/education/groups'),
  createGroup: (name: string) => request<{ group: Group }>('/api/education/groups', { method: 'POST', body: JSON.stringify({ name }) }),
  addMember: (groupId: string, email: string) => request<{ ok: boolean }>(`/api/education/groups/${encodeURIComponent(groupId)}/members`, { method: 'POST', body: JSON.stringify({ email }) }),
  assign: (groupId: string, payload: { title: string; topology: Topology; instructions: string; criteria: string[] }) => request<{ assignment: { id: string; title: string } }>(`/api/education/groups/${encodeURIComponent(groupId)}/assignments`, { method: 'POST', body: JSON.stringify(payload) }),
  submissions: (groupId: string) => request<{ submissions: GroupSubmission[] }>(`/api/education/groups/${encodeURIComponent(groupId)}/submissions`),
  studentSubmissionHistory: (assignmentId: string) => request<{ submissions: SubmissionAttempt[] }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/submissions`),
  teacherSubmissionHistory: (assignmentId: string, studentId: string) => request<{ submissions: SubmissionAttempt[] }>(`/api/education/assignments/${encodeURIComponent(assignmentId)}/students/${encodeURIComponent(studentId)}/submissions`),
  reviewSubmission: (assignmentId: string, studentId: string, submissionId: string, feedback: string, grade: number | null) => request<{ ok: boolean }>(`/api/education/assignments/${encodeURIComponent(assignmentId)}/students/${encodeURIComponent(studentId)}/submissions/${encodeURIComponent(submissionId)}/feedback`, { method: 'POST', body: JSON.stringify({ feedback, grade }) }),
  myAssignments: () => request<{ assignments: Assignment[] }>('/api/education/my-assignments'),
  cloneAssignment: (assignmentId: string) => request<{ topology: Topology }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/clone`, { method: 'POST', body: '{}' }),
  resetAssignment: (assignmentId: string) => request<{ topology: Topology }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/reset`, { method: 'POST', body: '{}' }),
  saveAssignmentTopology: (assignmentId: string, topology: Topology) => request<{ ok: boolean }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/topology`, { method: 'PUT', body: JSON.stringify({ topology }) }),
  submitAssignment: (assignmentId: string) => request<{ ok: boolean }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/submit`, { method: 'POST', body: '{}' }),
  studentRuntime: (assignmentId: string) => request<{ status: Assignment['runtime_status']; expires_at: number | null; nodes: StatusNode[] }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/runtime`),
  studentRuntimeAction: (assignmentId: string, action: 'up' | 'down' | 'verify') => request<{ ok: boolean; action: string; exit_code: number; output: string }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/runtime/${action}`, { method: 'POST', body: '{}' }),
  studentTerminal: (assignmentId: string, node: string, command: string[]) => request<{ ok: boolean; output: string; exit_code: number }>(`/api/education/my-assignments/${encodeURIComponent(assignmentId)}/runtime/nodes/${encodeURIComponent(node)}/terminal`, { method: 'POST', body: JSON.stringify({ command }) }),
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
  laboratories: () => request<{ laboratories: Laboratory[] }>('/api/laboratories'),
  laboratory: (id: string) => request<{ laboratory: Laboratory; topology: Topology }>(`/api/laboratories/${encodeURIComponent(id)}`),
  createLaboratory: (topology: Topology) => request<{ laboratory: Laboratory; topology: Topology }>('/api/laboratories', { method: 'POST', body: JSON.stringify({ topology }) }),
  saveLaboratory: (id: string, topology: Topology) => request<{ topology: Topology }>(`/api/laboratories/${encodeURIComponent(id)}/topology`, { method: 'PUT', body: JSON.stringify({ topology }) }),
  laboratoryStatus: (id: string) => request<{ nodes: StatusNode[] }>(`/api/laboratories/${encodeURIComponent(id)}/status`),
  laboratoryLogs: (id: string) => request<{ logs: Array<{ message: string; created_at: number }> }>(`/api/laboratories/${encodeURIComponent(id)}/logs`),
  laboratoryVersions: (id: string) => request<{ lab: string; versions: VersionInfo[] }>(`/api/laboratories/${encodeURIComponent(id)}/versions`),
  restoreLaboratory: (id: string, version: number) => request<{ topology: Topology }>(`/api/laboratories/${encodeURIComponent(id)}/versions/${version}/restore`, { method: 'POST', body: '{}' }),
  laboratoryAction: (id: string, action: 'up' | 'down' | 'verify') => request<{ ok: boolean; exit_code: number; output: string }>(`/api/laboratories/${encodeURIComponent(id)}/actions/${action}`, { method: 'POST', body: '{}' }),
  addLaboratoryMember: (id: string, email: string, role: 'editor' | 'viewer') => request<{ ok: boolean }>(`/api/laboratories/${encodeURIComponent(id)}/members`, { method: 'POST', body: JSON.stringify({ email, role }) }),
}
