<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import type { Assignment, Group, GroupSubmission, Laboratory, ObservabilitySnapshot, ServiceProfile, SubmissionAttempt, User } from './api'
import type { Node, PaletteItem, StatusNode, Topology, VersionInfo } from './types'

const user = ref<User | null>(null)
const setupAvailable = ref(false)
const hasUsers = ref(true)
const bootstrapRole = ref<'admin' | 'teacher'>('teacher')
const pageError = ref('')
const loginEmail = ref('')
const loginPassword = ref('')
const setupToken = ref('')
const setupName = ref('')
const setupEmail = ref('')
const setupPassword = ref('')
const invitationToken = ref('')
const invitationPassword = ref('')
const resetToken = ref('')
const resetPasswordDraft = ref('')
const topology = ref<Topology | null>(null)
const laboratories = ref<Laboratory[]>([])
const activeLaboratoryId = ref('')
const statuses = ref<StatusNode[]>([])
const logs = ref<string[]>([])
const versions = ref<VersionInfo[]>([])
const selected = ref<string | null>(null)
const linkMode = ref(false)
const linkStart = ref<string | null>(null)
const dirty = ref(false)
const terminalOutput = ref('Sélectionnez un nœud pour ouvrir son terminal.')
const terminalCommand = ref('hostname')
const terminalSocket = ref<WebSocket | null>(null)
const groups = ref<Group[]>([])
const users = ref<User[]>([])
const serviceCatalog = ref<ServiceProfile[]>([])
const selectedServiceId = ref('nginx')
const selectedTemplateId = ref('static-routing')
const submissions = ref<GroupSubmission[]>([])
const assignments = ref<Assignment[]>([])
const activeAssignmentId = ref('')
const studentDraftDirty = ref(false)
const studentTerminalNode = ref('')
const studentTerminalCommand = ref('hostname')
const studentSelectedNodeName = ref('')
const studentSubmissionHistory = ref<SubmissionAttempt[]>([])
const selectedSubmission = ref<{ assignment_id: string; student_id: string; title: string; display_name: string } | null>(null)
const teacherSubmissionHistory = ref<SubmissionAttempt[]>([])
const feedbackDrafts = ref<Record<string, string>>({})
const gradeDrafts = ref<Record<string, string>>({})
const newStudent = ref({ email: '', display_name: '', password: '' })
const newTeacher = ref({ email: '', display_name: '', password: '' })
const newInvitation = ref<{ email: string; display_name: string; role: 'student' | 'teacher'; group_id: string }>({ email: '', display_name: '', role: 'student', group_id: '' })
const invitationTokenIssued = ref('')
const newGroupName = ref('')
const memberEmail = ref('')
const assignmentTitle = ref('')
const assignmentTemplateId = ref('current')
const assignmentInstructions = ref('')
const assignmentCriteriaDraft = ref('')
const selectedGroupId = ref('')
const busy = ref(false)
const operationBusy = ref('')
const undoStack = ref<Topology[]>([])
const redoStack = ref<Topology[]>([])
const observability = ref<ObservabilitySnapshot | null>(null)
const observabilityLoading = ref(false)
const observabilityError = ref('')
const observabilityRefreshAllowed = ref(true)
const cableStart = ref<{ nodeName: string; portIndex: number } | null>(null)
const devicePanelOpen = ref(false)
const devicePanelTab = ref<'terminal' | 'network' | 'logs' | 'resources'>('terminal')
const canvasView = ref({ x: 0, y: 0, scale: 1 })
const canvasPanning = ref(false)
const paletteItems: PaletteItem[] = [
  { id: 'pc-ubuntu', label: 'PC Ubuntu', description: 'poste Linux prêt pour les exercices IP', icon: 'PC', kind: 'node', image: 'netlab/ubuntu-lab:24.04', type: 'linux' },
  { id: 'router-linux', label: 'Routeur Linux', description: 'routeur Debian avec forwarding IPv4', icon: 'R', kind: 'node', image: 'netlab/debian-router:bookworm', type: 'router', router: true },
  { id: 'server-debian', label: 'Serveur Debian', description: 'serveur Linux avec outils réseau', icon: 'S', kind: 'node', image: 'netlab/debian-lab:bookworm', type: 'linux' },
  { id: 'switch-virtual', label: 'Switch virtuel', description: 'ajoute un segment Docker bridge', icon: 'SW', kind: 'network' },
  { id: 'nginx', label: 'Nginx', description: 'service web catalogue', icon: 'WEB', kind: 'service', serviceId: 'nginx' },
  { id: 'apache', label: 'Apache', description: 'service web catalogue', icon: 'WEB', kind: 'service', serviceId: 'apache' },
]
const paletteDragId = ref('')
let timer: number | undefined
let observabilityTimer: number | undefined
let observabilityCooldownTimer: number | undefined

const selectedNode = computed(() => topology.value?.nodes.find(node => node.name === selected.value))
const selectedServiceProfile = computed(() => serviceCatalog.value.find(profile => profile.id === selectedNode.value?.service_id))
const selectedObservabilityNode = computed(() => {
  if (!selectedNode.value) return undefined
  return observability.value?.nodes.find(node =>
    node.name === selectedNode.value?.name &&
    (!activeLaboratoryId.value || node.laboratory_id === activeLaboratoryId.value || node.lab === topology.value?.lab),
  )
})
const selectedNodeLogs = computed(() => {
  if (!selectedNode.value) return []
  const needle = selectedNode.value.name.toLowerCase()
  return logs.value.filter(entry => entry.toLowerCase().includes(needle))
})
const selectedNodeLinks = computed(() => {
  if (!selectedNode.value || !topology.value) return []
  return topology.value.links.filter(link => link.from === selectedNode.value?.name || link.to === selectedNode.value?.name)
})
const stateText = computed(() => dirty.value ? 'modifications non sauvegardées' : 'contrôle actif')
const activeAssignment = computed(() => assignments.value.find(item => item.id === activeAssignmentId.value))
const selectedStudentNode = computed(() => activeAssignment.value?.topology.nodes.find(node => node.name === studentSelectedNodeName.value))
const activeLaboratory = computed(() => laboratories.value.find(item => item.id === activeLaboratoryId.value))
const canModifyLaboratory = computed(() => ['teacher', 'admin'].includes(user.value?.role ?? '') && ['owner', 'editor'].includes(activeLaboratory.value?.role ?? ''))
const ownsLaboratory = computed(() => ['teacher', 'admin'].includes(user.value?.role ?? '') && activeLaboratory.value?.role === 'owner')
const deployableServices = computed(() => serviceCatalog.value.filter(profile => profile.deployable))
const topologyNetworks = computed(() => topology.value?.networks ?? [])
const cableHint = computed(() => cableStart.value ? `Port sélectionné sur ${cableStart.value.nodeName}. Cliquez sur un autre port pour créer le câble.` : 'Faites glisser un équipement ici, puis cliquez sur deux ports pour les relier.')
const topologyIssues = computed(() => {
  const current = topology.value
  if (!current || current.version < 2) return [] as string[]
  const issues: string[] = []
  const networks = current.networks ?? []
  const networkNames = new Set<string>()
  for (const network of networks) {
    if (networkNames.has(network.name)) issues.push(`Segment réseau dupliqué : ${network.name}`)
    networkNames.add(network.name)
    if (!/^\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2}$/.test(network.subnet)) issues.push(`Sous-réseau IPv4 invalide : ${network.name}`)
  }
  for (const node of current.nodes) {
    const interfaces = node.interfaces ?? []
    if (!interfaces.length) issues.push(`${node.name} doit avoir au moins une interface`)
    const interfaceNames = new Set<string>()
    for (const item of interfaces) {
      if (interfaceNames.has(item.name)) issues.push(`${node.name} contient deux interfaces ${item.name}`)
      interfaceNames.add(item.name)
      if (!networkNames.has(item.network)) issues.push(`${node.name}.${item.name} référence le segment absent ${item.network}`)
      if (item.ipv4 && !/^\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2}$/.test(item.ipv4)) issues.push(`Adresse IPv4 invalide sur ${node.name}.${item.name}`)
    }
    for (const route of node.routes ?? []) {
      if (!/^\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2}$/.test(route.destination)) issues.push(`Destination de route invalide sur ${node.name}`)
      if (!/^\d{1,3}(?:\.\d{1,3}){3}$/.test(route.via)) issues.push(`Passerelle de route invalide sur ${node.name}`)
    }
  }
  const nodeNames = new Set(current.nodes.map(node => node.name))
  const linkKeys = new Set<string>()
  for (const link of current.links ?? []) {
    if (!nodeNames.has(link.from)) issues.push(`Le câble part d’un nœud absent : ${link.from}`)
    if (!nodeNames.has(link.to)) issues.push(`Le câble arrive sur un nœud absent : ${link.to}`)
    if (link.from === link.to) issues.push(`Le câble ${link.from} ne peut pas relier un nœud à lui-même`)
    const key = [link.from, link.from_port ?? 'eth0', link.to, link.to_port ?? 'eth0'].join(':')
    const reverseKey = [link.to, link.to_port ?? 'eth0', link.from, link.from_port ?? 'eth0'].join(':')
    if (linkKeys.has(key) || linkKeys.has(reverseKey)) issues.push(`Câble dupliqué entre ${link.from} et ${link.to}`)
    linkKeys.add(key)
    for (const [nodeName, portName] of [[link.from, link.from_port], [link.to, link.to_port]] as Array<[string, string | undefined]>) {
      const linkedNode = current.nodes.find(node => node.name === nodeName)
      if (linkedNode && portName && !(linkedNode.interfaces ?? []).some(item => item.name === portName)) issues.push(`${nodeName}.${portName} est absent des interfaces déclarées`)
    }
  }
  if (!current.nodes.some(node => node.name === current.connectivity_check.from)) issues.push('Le nœud source du test est introuvable')
  if (!current.nodes.some(node => node.name === current.connectivity_check.to)) issues.push('Le nœud destination du test est introuvable')
  return [...new Set(issues)]
})
function nodeHasTopologyIssue(nodeName: string) {
  return topologyIssues.value.some(issue => issue.includes(nodeName))
}
const labTemplates: Array<{ id: string; label: string; description: string; topology: Topology }> = [
  {
    id: 'static-routing',
    label: 'Routage statique client–routeur–serveur',
    description: 'Deux LAN Docker, un routeur Linux et un test ping inter-réseaux.',
    topology: {
      version: 2, lab: 'static-routing-lab',
      network: { name: 'lan-a', driver: 'bridge', subnet: '10.0.1.0/24' },
      networks: [
        { name: 'lan-a', driver: 'bridge', subnet: '10.0.1.0/24' },
        { name: 'lan-b', driver: 'bridge', subnet: '10.0.2.0/24' },
      ],
      nodes: [
        { name: 'client-ubuntu', image: 'netlab/ubuntu-lab:24.04', command: ['sleep', 'infinity'], position: { x: 50, y: 120 }, interfaces: [{ name: 'eth0', network: 'lan-a', ipv4: '10.0.1.10/24', gateway: '10.0.1.1' }], routes: [{ destination: '10.0.2.0/24', via: '10.0.1.1' }] },
        { name: 'router-linux', image: 'netlab/debian-router:bookworm', command: ['sleep', 'infinity'], position: { x: 300, y: 120 }, type: 'router', router: true, interfaces: [{ name: 'eth0', network: 'lan-a', ipv4: '10.0.1.1/24' }, { name: 'eth1', network: 'lan-b', ipv4: '10.0.2.1/24' }], routes: [] },
        { name: 'server-debian', image: 'netlab/debian-lab:bookworm', command: ['sleep', 'infinity'], position: { x: 560, y: 120 }, interfaces: [{ name: 'eth0', network: 'lan-b', ipv4: '10.0.2.10/24', gateway: '10.0.2.1' }], routes: [{ destination: '10.0.1.0/24', via: '10.0.2.1' }] },
      ],
      links: [{ from: 'client-ubuntu', to: 'router-linux' }, { from: 'router-linux', to: 'server-debian' }],
      connectivity_check: { from: 'client-ubuntu', to: 'server-debian', command: ['ping', '-c', '1', '10.0.2.10'] },
    },
  },
  {
    id: 'simple-lan',
    label: 'Réseau local Ubuntu–Debian',
    description: 'Deux hôtes sur un même segment Docker pour les premiers exercices IP.',
    topology: {
      version: 2, lab: 'simple-lan-lab',
      network: { name: 'lan', driver: 'bridge', subnet: '10.10.0.0/24' },
      networks: [{ name: 'lan', driver: 'bridge', subnet: '10.10.0.0/24' }],
      nodes: [
        { name: 'client-ubuntu', image: 'netlab/ubuntu-lab:24.04', command: ['sleep', 'infinity'], position: { x: 150, y: 120 }, interfaces: [{ name: 'eth0', network: 'lan', ipv4: '10.10.0.10/24' }], routes: [] },
        { name: 'server-debian', image: 'netlab/debian-lab:bookworm', command: ['sleep', 'infinity'], position: { x: 470, y: 120 }, interfaces: [{ name: 'eth0', network: 'lan', ipv4: '10.10.0.20/24' }], routes: [] },
      ],
      links: [{ from: 'client-ubuntu', to: 'server-debian' }],
      connectivity_check: { from: 'client-ubuntu', to: 'server-debian', command: ['ping', '-c', '1', '10.10.0.20'] },
    },
  },
]
function nodeStatus(name: string) { return statuses.value.find(node => node.name === name)?.state ?? 'inconnu' }
function showError(error: unknown) { pageError.value = error instanceof Error ? error.message : 'Erreur inconnue' }

function captureTopologyHistory() {
  if (!topology.value) return
  undoStack.value.push(structuredClone(topology.value))
  if (undoStack.value.length > 50) undoStack.value.shift()
  redoStack.value = []
}

function undoTopology() {
  if (!topology.value || !undoStack.value.length) return
  redoStack.value.push(structuredClone(topology.value))
  topology.value = undoStack.value.pop() ?? topology.value
  dirty.value = true
  terminalOutput.value = 'Dernière modification annulée.'
}

function redoTopology() {
  if (!topology.value || !redoStack.value.length) return
  undoStack.value.push(structuredClone(topology.value))
  topology.value = redoStack.value.pop() ?? topology.value
  dirty.value = true
  terminalOutput.value = 'Modification rétablie.'
}

async function initialize() {
  pageError.value = ''
  try {
    const state = await api.authState()
    hasUsers.value = state.has_users
    setupAvailable.value = state.bootstrap_enabled && !state.has_users
    bootstrapRole.value = state.bootstrap_role
    try { user.value = (await api.me()).user } catch { user.value = null }
    if (!user.value) return
    if (user.value.role !== 'student') {
      await loadLaboratories()
      await refresh(true)
      await loadObservability()
      if (!observabilityTimer) observabilityTimer = window.setInterval(() => loadObservability(), 15000)
      await loadEducation()
      if (!timer) timer = window.setInterval(() => refresh(), 5000)
    } else {
      await loadAssignments()
    }
  } catch (error) { showError(error) }
}
async function loadLaboratories() {
  const response = await api.laboratories()
  laboratories.value = response.laboratories
  if (!laboratories.value.some(lab => lab.id === activeLaboratoryId.value)) {
    activeLaboratoryId.value = laboratories.value[0]?.id ?? ''
  }
}
async function switchLaboratory(event: Event) {
  const select = event.target as HTMLSelectElement
  const nextId = select.value
  if (dirty.value && !window.confirm('Abandonner les modifications non sauvegardées ?')) {
    select.value = activeLaboratoryId.value
    return
  }
  activeLaboratoryId.value = nextId
  terminalSocket.value?.close()
  dirty.value = false
  selected.value = null
  await refresh(true)
}
async function createLaboratory() {
  if (!topology.value) return
  const newLab = window.prompt('Nom du nouveau laboratoire :', `${topology.value.lab}-copy`)
  if (!newLab?.trim()) return
  try {
    const topologyCopy = structuredClone(topology.value)
    topologyCopy.lab = newLab.trim()
    delete topologyCopy.laboratory_id
    const result = await api.createLaboratory(topologyCopy)
    await loadLaboratories()
    activeLaboratoryId.value = result.laboratory.id
    topology.value = result.topology
    selected.value = topology.value.nodes[0]?.name ?? null
    dirty.value = false
    terminalOutput.value = `Nouveau laboratoire créé : ${topology.value.lab}`
    await refresh(false)
  } catch (error) { showError(error) }
}
async function login() {
  busy.value = true
  try { const result = await api.login(loginEmail.value, loginPassword.value); user.value = result.user; loginPassword.value = ''; await initialize() }
  catch (error) { showError(error) }
  finally { busy.value = false }
}
async function acceptInvitation() {
  busy.value = true
  try {
    const result = await api.acceptInvitation(invitationToken.value, invitationPassword.value)
    user.value = result.user
    invitationToken.value = ''
    invitationPassword.value = ''
    await initialize()
  } catch (error) { showError(error) }
  finally { busy.value = false }
}
async function resetPassword() {
  busy.value = true
  try {
    await api.resetPassword(resetToken.value, resetPasswordDraft.value)
    resetToken.value = ''
    resetPasswordDraft.value = ''
    pageError.value = 'Mot de passe modifié. Vous pouvez vous connecter.'
  } catch (error) { showError(error) }
  finally { busy.value = false }
}
async function bootstrap() {
  busy.value = true
  try {
    const result = await api.bootstrap({ bootstrap_token: setupToken.value, email: setupEmail.value, display_name: setupName.value, password: setupPassword.value })
    user.value = result.user; setupToken.value = ''; setupPassword.value = ''; await initialize()
  } catch (error) { showError(error) }
  finally { busy.value = false }
}
async function logout() {
  try { await api.logout() } catch { /* the session may already have expired */ }
  if (timer) window.clearInterval(timer)
  if (observabilityTimer) window.clearInterval(observabilityTimer)
  if (observabilityCooldownTimer) window.clearTimeout(observabilityCooldownTimer)
  timer = undefined
  observabilityTimer = undefined
  observabilityCooldownTimer = undefined
  observabilityRefreshAllowed.value = true
  terminalSocket.value?.close(); user.value = null; topology.value = null; laboratories.value = []; activeLaboratoryId.value = ''; assignments.value = []; observability.value = null; invitationTokenIssued.value = ''; pageError.value = ''
}

async function loadEducation() {
  const [groupResponse, userResponse, servicesResponse] = await Promise.all([api.groups(), api.users(), api.services()])
  groups.value = groupResponse.groups; users.value = userResponse.users; serviceCatalog.value = servicesResponse.services
  if (!deployableServices.value.some(profile => profile.id === selectedServiceId.value)) selectedServiceId.value = deployableServices.value[0]?.id ?? ''
  if (!selectedGroupId.value || !groups.value.some(group => group.id === selectedGroupId.value)) selectedGroupId.value = groups.value[0]?.id ?? ''
  await loadSubmissions()
}
async function createStudent() {
  try { await api.createStudent(newStudent.value); newStudent.value = { email: '', display_name: '', password: '' }; await loadEducation(); pageError.value = 'Compte étudiant créé. Communiquez son adresse et son mot de passe par un canal sûr.' }
  catch (error) { showError(error) }
}
async function createTeacher() {
  try { await api.createTeacher(newTeacher.value); newTeacher.value = { email: '', display_name: '', password: '' }; await loadEducation(); pageError.value = 'Compte enseignant créé. Transmettez ses identifiants par un canal sûr.' }
  catch (error) { showError(error) }
}
async function createInvitation() {
  try {
    const result = await api.createInvitation({
      ...newInvitation.value,
      group_id: newInvitation.value.group_id || null,
    })
    invitationTokenIssued.value = result.token
    newInvitation.value = { email: '', display_name: '', role: 'student', group_id: '' }
    pageError.value = `Invitation créée pour ${result.invitation.email}. Transmettez le jeton avant son expiration dans 7 jours.`
  } catch (error) { showError(error) }
}
async function issuePasswordReset(userItem: User) {
  try {
    const result = await api.issuePasswordReset(userItem.id)
    window.prompt(`Jeton de réinitialisation pour ${userItem.email} (valide 1 heure) — transmettre par un canal sûr :`, result.token)
  } catch (error) { showError(error) }
}
async function createGroup() {
  try { await api.createGroup(newGroupName.value); newGroupName.value = ''; await loadEducation() }
  catch (error) { showError(error) }
}
async function addMember() {
  if (!selectedGroupId.value) return
  try { await api.addMember(selectedGroupId.value, memberEmail.value); memberEmail.value = ''; await loadEducation() }
  catch (error) { showError(error) }
}
async function publishAssignment() {
  if (!selectedGroupId.value || !topology.value) return
  try {
    const template = labTemplates.find(item => item.id === assignmentTemplateId.value)
    const assignedTopology = template ? structuredClone(template.topology) : structuredClone(topology.value)
    const result = await api.assign(selectedGroupId.value, {
      title: assignmentTitle.value.trim() || template?.label || topology.value.lab,
      topology: assignedTopology,
      instructions: assignmentInstructions.value,
      criteria: assignmentCriteriaDraft.value.split('\n').map(item => item.trim()).filter(Boolean),
    })
    assignmentTitle.value = ''
    assignmentInstructions.value = ''
    assignmentCriteriaDraft.value = ''
    pageError.value = `Laboratoire partagé : ${result.assignment.title}`
    await loadSubmissions()
  } catch (error) { showError(error) }
}
async function loadSubmissions() {
  if (!selectedGroupId.value || !['teacher', 'admin'].includes(user.value?.role ?? '')) { submissions.value = []; return }
  try { submissions.value = (await api.submissions(selectedGroupId.value)).submissions }
  catch (error) { showError(error) }
}
async function loadAssignments() {
  try {
    assignments.value = (await api.myAssignments()).assignments
    if (!assignments.value.some(item => item.id === activeAssignmentId.value)) {
      activeAssignmentId.value = assignments.value[0]?.id ?? ''
    }
    studentSelectedNodeName.value = activeAssignment.value?.topology.nodes[0]?.name ?? ''
    studentDraftDirty.value = false
    await refreshStudentRuntime()
    await loadStudentSubmissionHistory()
  } catch (error) { showError(error) }
}
function selectAssignment(id: string) {
  activeAssignmentId.value = id
  const item = activeAssignment.value
  studentDraftDirty.value = false
  studentSelectedNodeName.value = item?.topology.nodes[0]?.name ?? ''
  studentTerminalNode.value = item?.topology.nodes[0]?.name ?? ''
  void refreshStudentRuntime()
  void loadStudentSubmissionHistory()
}
async function loadStudentSubmissionHistory() {
  const item = activeAssignment.value
  if (!item) { studentSubmissionHistory.value = []; return }
  try { studentSubmissionHistory.value = (await api.studentSubmissionHistory(item.id)).submissions }
  catch (error) { showError(error) }
}
async function refreshStudentRuntime() {
  const item = activeAssignment.value
  if (!item?.topology.laboratory_id) { statuses.value = []; return }
  try {
    const runtime = await api.studentRuntime(item.id)
    item.runtime_status = runtime.status
    statuses.value = runtime.nodes
    studentTerminalNode.value = item.topology.nodes[0]?.name ?? ''
  } catch (error) { showError(error) }
}
async function cloneAssignment() {
  if (!activeAssignment.value) return false
  try {
    const result = activeAssignment.value.topology.laboratory_id
      ? await api.resetAssignment(activeAssignment.value.id)
      : await api.cloneAssignment(activeAssignment.value.id)
    activeAssignment.value.topology = result.topology
    activeAssignment.value.status = 'in_progress'
    activeAssignment.value.runtime_status = 'stopped'
    studentDraftDirty.value = false
    statuses.value = []
    studentTerminalNode.value = result.topology.nodes[0]?.name ?? ''
    pageError.value = 'Copie réinitialisée.'
    await loadStudentSubmissionHistory()
    return true
  } catch (error) { showError(error); return false }
}
async function saveAssignment() {
  if (!activeAssignment.value) return false
  try {
    await api.saveAssignmentTopology(activeAssignment.value.id, activeAssignment.value.topology)
    activeAssignment.value.status = 'in_progress'
    studentDraftDirty.value = false
    pageError.value = 'Copie personnelle enregistrée.'
    return true
  } catch (error) { showError(error); return false }
}
async function submitAssignment() {
  if (!activeAssignment.value) return
  try {
    if (['running', 'failed'].includes(activeAssignment.value.runtime_status)) {
      const stopped = await api.studentRuntimeAction(activeAssignment.value.id, 'down')
      if (!stopped.ok) throw new Error(`Impossible de nettoyer le laboratoire (code ${stopped.exit_code}).`)
      activeAssignment.value.runtime_status = 'stopped'
    }
    if (activeAssignment.value.status === 'assigned' && !await cloneAssignment()) return
    if (!await saveAssignment()) return
    await api.submitAssignment(activeAssignment.value.id)
    activeAssignment.value.status = 'submitted'
    pageError.value = 'Travail remis à l’enseignant.'
    await loadAssignments()
  } catch (error) { showError(error) }
}
function addStudentRoute(node: Node) {
  node.routes ??= []
  node.routes.push({ destination: '', via: '' })
  studentDraftDirty.value = true
}
function removeStudentRoute(node: Node, index: number) {
  node.routes?.splice(index, 1)
  studentDraftDirty.value = true
}
async function studentRuntimeAction(action: 'up' | 'down' | 'verify') {
  const item = activeAssignment.value
  if (!item) return
  try {
    if (action === 'up') {
      if (item.status === 'assigned' && !await cloneAssignment()) return
      if (!await saveAssignment()) return
    }
    const result = await api.studentRuntimeAction(item.id, action)
    terminalOutput.value = result.output || (result.ok ? `${action} : terminé` : `${action} : échec (code ${result.exit_code})`)
    if (action === 'up') item.runtime_status = result.ok ? 'running' : 'failed'
    if (action === 'down') item.runtime_status = result.ok ? 'stopped' : 'failed'
    if (result.ok) await refreshStudentRuntime()
  } catch (error) { showError(error) }
}
async function runStudentTerminal() {
  const item = activeAssignment.value
  const command = studentTerminalCommand.value.trim().split(/\s+/).filter(Boolean)
  if (!item || !studentTerminalNode.value || !command.length) return
  try {
    const result = await api.studentTerminal(item.id, studentTerminalNode.value, command)
    terminalOutput.value = result.output || (result.ok ? 'Commande terminée.' : `Commande échouée (code ${result.exit_code}).`)
  } catch (error) { showError(error) }
}
async function openSubmission(item: GroupSubmission) {
  try {
    selectedSubmission.value = {
      assignment_id: item.assignment_id,
      student_id: item.student_id,
      title: item.title,
      display_name: item.display_name,
    }
    teacherSubmissionHistory.value = (await api.teacherSubmissionHistory(item.assignment_id, item.student_id)).submissions
    feedbackDrafts.value = Object.fromEntries(teacherSubmissionHistory.value.map(entry => [entry.id, entry.feedback ?? '']))
    gradeDrafts.value = Object.fromEntries(teacherSubmissionHistory.value.map(entry => [entry.id, entry.grade === null ? '' : String(entry.grade)]))
  } catch (error) { showError(error) }
}
async function saveSubmissionFeedback(submission: SubmissionAttempt) {
  const selectedItem = selectedSubmission.value
  if (!selectedItem) return
  try {
    const rawGrade = gradeDrafts.value[submission.id]?.trim() ?? ''
    const grade = rawGrade ? Number(rawGrade) : null
    if (rawGrade && (!Number.isFinite(grade) || grade! < 0 || grade! > 100)) throw new Error('La note doit être comprise entre 0 et 100.')
    await api.reviewSubmission(selectedItem.assignment_id, selectedItem.student_id, submission.id, feedbackDrafts.value[submission.id] ?? '', grade)
    pageError.value = `Retour enregistré pour ${selectedItem.display_name}, tentative ${submission.attempt}.`
    teacherSubmissionHistory.value = (await api.teacherSubmissionHistory(selectedItem.assignment_id, selectedItem.student_id)).submissions
    await loadSubmissions()
  } catch (error) { showError(error) }
}

function portCount(node: Node) {
  return Math.max(node.interfaces?.length ?? 0, node.router ? 2 : 1)
}
function portLabel(node: Node, index: number) {
  return node.interfaces?.[index]?.name ?? `eth${index}`
}
function portPoint(node: Node, index: number) {
  const count = portCount(node)
  return { x: node.position.x + 160, y: node.position.y + 18 + (index * 24) / Math.max(1, count - 1) }
}
function interfaceForPort(node: Node, index: number, network?: string) {
  node.interfaces ??= []
  while (node.interfaces.length <= index) node.interfaces.push({ name: `eth${node.interfaces.length}`, network: network ?? topology.value?.network.name ?? 'lan' })
  if (network && node.interfaces[index].network !== network) node.interfaces[index].network = network
  return node.interfaces[index]
}
function linkPortIndex(node: Node, portName: string | undefined) {
  if (!portName) return 0
  const index = node.interfaces?.findIndex(item => item.name === portName) ?? -1
  return index >= 0 ? index : 0
}
function portIsOccupied(node: Node, portIndex: number) {
  const portName = portLabel(node, portIndex)
  return topology.value?.links.some(link =>
    (link.from === node.name && (link.from_port ?? 'eth0') === portName) ||
    (link.to === node.name && (link.to_port ?? 'eth0') === portName),
  ) ?? false
}
function connectPorts(node: Node, portIndex: number) {
  if (!topology.value || !cableStart.value) return
  const startNode = topology.value.nodes.find(item => item.name === cableStart.value?.nodeName)
  if (!startNode || startNode.name === node.name) { cableStart.value = null; return }
  if (portIsOccupied(node, portIndex)) {
    pageError.value = `Le port ${node.name}.${portLabel(node, portIndex)} est déjà utilisé par un câble.`
    cableStart.value = null
    return
  }
  captureTopologyHistory()
  const startInterface = interfaceForPort(startNode, cableStart.value.portIndex)
  const targetInterface = interfaceForPort(node, portIndex, startInterface.network)
  targetInterface.network = startInterface.network
  topology.value.links ??= []
  const exists = topology.value.links.some(link =>
    (link.from === startNode.name && link.to === node.name) ||
    (link.from === node.name && link.to === startNode.name),
  )
  if (!exists) topology.value.links.push({ from: startNode.name, to: node.name, from_port: startInterface.name, to_port: targetInterface.name })
  dirty.value = true
  cableStart.value = null
  selected.value = node.name
}
function selectPort(event: MouseEvent, node: Node, index: number) {
  event.stopPropagation()
  if (portIsOccupied(node, index)) {
    pageError.value = `Le port ${node.name}.${portLabel(node, index)} est déjà utilisé par un câble.`
    cableStart.value = null
    return
  }
  if (cableStart.value) connectPorts(node, index)
  else cableStart.value = { nodeName: node.name, portIndex: index }
}
function paletteDragStart(item: PaletteItem, event: DragEvent) {
  paletteDragId.value = item.id
  event.dataTransfer?.setData('application/x-netlab-palette', item.id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'copy'
}
function paletteDragEnd() { paletteDragId.value = '' }
function addPaletteItem(item: PaletteItem, position?: { x: number; y: number }) {
  if (!topology.value) return
  if (item.kind === 'network') {
    const index = (topology.value.networks?.length ?? 0) + 1
    const name = `lan-${index}`
    topology.value.networks ??= []
    topology.value.networks.push({ name, driver: 'bridge', subnet: `10.0.${index}.0/24` })
    dirty.value = true
    pageError.value = `Switch virtuel ajouté : le segment ${name} est prêt à être utilisé.`
    return
  }
  if (item.kind === 'service') {
    selectedServiceId.value = item.serviceId ?? selectedServiceId.value
    addCatalogService(position)
    return
  }
  const base = item.id.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'node'
  let name = base
  let index = 2
  while (topology.value.nodes.some(node => node.name === name)) name = `${base}-${index++}`
  captureTopologyHistory()
  const node: Node = {
    name, image: item.image ?? 'netlab/debian-lab:bookworm', command: ['sleep', 'infinity'],
    position: position ?? { x: 60 + (topology.value.nodes.length % 3) * 220, y: 90 + Math.floor(topology.value.nodes.length / 3) * 110 },
    type: item.type, router: item.router, environment: {}, secret_refs: {}, depends_on: [],
  }
  if (topology.value.version >= 2) node.interfaces = [{ name: 'eth0', network: topology.value.network.name }]
  if (item.router) node.interfaces = [
    { name: 'eth0', network: topology.value.network.name },
    { name: 'eth1', network: topology.value.networks?.[1]?.name ?? topology.value.network.name },
  ]
  topology.value.nodes.push(node)
  selected.value = name
  dirty.value = true
}
function dropPalette(event: DragEvent) {
  event.preventDefault()
  const id = event.dataTransfer?.getData('application/x-netlab-palette') || paletteDragId.value
  const item = paletteItems.find(candidate => candidate.id === id)
  if (!item) return
  addPaletteItem(item, point(event as unknown as PointerEvent))
  paletteDragEnd()
}
function addCatalogService(position?: { x: number; y: number }) {
  if (!topology.value) return
  const profile = deployableServices.value.find(item => item.id === selectedServiceId.value)
  if (!profile?.image) return
  let name = `${profile.id}-${topology.value.nodes.length + 1}`
  let index = 2
  while (topology.value.nodes.some(node => node.name === name)) name = `${profile.id}-${topology.value.nodes.length + index++}`
  captureTopologyHistory()
  const node: Node = {
    name, image: profile.image, command: [...profile.command], service_id: profile.id,
    position: position ?? { x: 60 + (topology.value.nodes.length % 3) * 220, y: 90 + Math.floor(topology.value.nodes.length / 3) * 110 },
    environment: {}, secret_refs: {}, depends_on: [],
  }
  if (profile.id === 'coredns') node.dns_records = []
  if (topology.value.version >= 2) node.interfaces = [{ name: 'eth0', network: topology.value.network.name }]
  topology.value.nodes.push(node); selected.value = name; dirty.value = true
}
function selectNode(node: Node) {
  if (linkMode.value) {
    if (!linkStart.value) linkStart.value = node.name
    else if (linkStart.value !== node.name && topology.value) {
      topology.value.links ??= []
      const exists = topology.value.links.some(link => (link.from === linkStart.value && link.to === node.name) || (link.from === node.name && link.to === linkStart.value))
      if (!exists) {
        const source = topology.value.nodes.find(item => item.name === linkStart.value)
        if (source) {
          const sourceInterface = interfaceForPort(source, 0)
          const targetInterface = interfaceForPort(node, 0, sourceInterface.network)
          topology.value.links.push({ from: source.name, to: node.name, from_port: sourceInterface.name, to_port: targetInterface.name })
        }
      }
      linkStart.value = null; linkMode.value = false; dirty.value = true
    }
    return
  }
  selected.value = node.name
  connectTerminal(node.name)
}
function openDevicePanel(node: Node, tab: 'terminal' | 'network' | 'logs' | 'resources' = 'terminal') {
  selected.value = node.name
  devicePanelTab.value = tab
  devicePanelOpen.value = true
  if (tab === 'terminal') connectTerminal(node.name)
  else terminalSocket.value?.close()
}
function connectTerminal(nodeName: string) {
  if (!activeLaboratoryId.value || !canModifyLaboratory.value) return
  terminalSocket.value?.close()
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/nodes/${encodeURIComponent(nodeName)}/terminal?laboratory_id=${encodeURIComponent(activeLaboratoryId.value)}`)
  socket.onopen = () => { terminalOutput.value = `Connexion au terminal de ${nodeName}…` }
  socket.onmessage = event => { terminalOutput.value += event.data }
  socket.onerror = () => { terminalOutput.value += '\nErreur de connexion terminal.' }
  terminalSocket.value = socket
}
function removeSelected() {
  if (!topology.value || !selected.value) return
  const nodeName = selected.value
  if (!window.confirm(`Supprimer l’équipement « ${nodeName} » et ses câbles ?`)) return
  captureTopologyHistory()
  topology.value.nodes = topology.value.nodes.filter(node => node.name !== nodeName)
  topology.value.links = topology.value.links.filter(link => link.from !== nodeName && link.to !== nodeName)
  selected.value = topology.value.nodes[0]?.name ?? null; dirty.value = true
}
function addNetwork() {
  if (!topology.value || topology.value.version < 2) return
  const name = window.prompt('Nom du segment réseau :', `lan-${(topology.value.networks?.length ?? 0) + 1}`)
  const subnet = window.prompt('Sous-réseau IPv4 CIDR :', `10.0.${(topology.value.networks?.length ?? 0) + 1}.0/24`)
  if (!name || !subnet) return
  if (topology.value.networks?.some(network => network.name === name)) { pageError.value = 'Ce segment existe déjà.'; return }
  captureTopologyHistory()
  topology.value.networks ??= []
  topology.value.networks.push({ name, driver: 'bridge', subnet })
  dirty.value = true
}
function removeNetwork(networkName: string) {
  if (!topology.value?.networks || topology.value.networks.length <= 1) return
  if (topology.value.nodes.some(node => node.interfaces?.some(item => item.network === networkName))) {
    pageError.value = 'Impossible de supprimer un segment encore utilisé par une interface.'
    return
  }
  captureTopologyHistory()
  topology.value.networks = topology.value.networks.filter(network => network.name !== networkName)
  dirty.value = true
}
function addInterface(node: Node) {
  if (!topology.value || topology.value.version < 2) return
  const networks = topology.value.networks ?? []
  const usedNetworks = new Set((node.interfaces ?? []).map(item => item.network))
  const network = networks.find(item => !usedNetworks.has(item.name)) ?? networks[0]
  if (!network) return
  node.interfaces ??= []
  const index = node.interfaces.length
  node.interfaces.push({ name: `eth${index}`, network: network.name })
  dirty.value = true
}
function removeInterface(node: Node, index: number) {
  if (!node.interfaces || node.interfaces.length <= 1) return
  const portName = node.interfaces[index]?.name
  if (portName && topology.value?.links.some(link => (link.from === node.name && link.from_port === portName) || (link.to === node.name && link.to_port === portName))) {
    pageError.value = `Impossible de supprimer ${node.name}.${portName} : ce port est utilisé par un câble.`
    return
  }
  node.interfaces.splice(index, 1)
  dirty.value = true
}
function addRoute(node: Node) {
  node.routes ??= []
  node.routes.push({ destination: '0.0.0.0/0', via: '' })
  dirty.value = true
}
function removeRoute(node: Node, index: number) {
  if (!node.routes) return
  node.routes.splice(index, 1)
  dirty.value = true
}
function addDNSRecord(node: Node) {
  node.dns_records ??= []
  node.dns_records.push({ name: `host-${node.dns_records.length + 1}.lab.test`, ipv4: '' })
  dirty.value = true
}
function removeDNSRecord(node: Node, index: number) {
  if (!node.dns_records) return
  node.dns_records.splice(index, 1)
  dirty.value = true
}
function nodeCommand(node: Node) { return node.command.join(' ') }
function setNodeCommand(node: Node, value: string) {
  node.command = value.trim().split(/\s+/).filter(Boolean)
  dirty.value = true
}
function setConnectivityCommand(command: string) {
  if (!topology.value) return
  topology.value.connectivity_check.command = [command]
  dirty.value = true
}
function applyTemplate() {
  const template = labTemplates.find(item => item.id === selectedTemplateId.value)
  if (!template) return
  if (dirty.value && !window.confirm('Remplacer la topologie actuelle et perdre les modifications non sauvegardées ?')) return
  captureTopologyHistory()
  topology.value = structuredClone(template.topology)
  selected.value = topology.value.nodes[0]?.name ?? null
  dirty.value = true
  terminalSocket.value?.close()
  terminalOutput.value = `Modèle chargé : ${template.label}`
  pageError.value = ''
}
function addNode() {
  if (!topology.value) return
  const name = window.prompt('Nom du nœud :', `linux-node-${topology.value.nodes.length + 1}`)
  const image = window.prompt('Image Docker :', 'ubuntu:24.04')
  if (!name || !image || topology.value.nodes.some(node => node.name === name)) return
  captureTopologyHistory()
  const node: Node = { name, image, command: ['sleep', 'infinity'], position: { x: 60 + topology.value.nodes.length * 210, y: 110 }, environment: {}, secret_refs: {}, depends_on: [] }
  if (topology.value.version >= 2) node.interfaces = [{ name: 'eth0', network: topology.value.network.name }]
  topology.value.nodes.push(node)
  selected.value = name; dirty.value = true
}
function setNodeEnvironment(node: Node, key: string, value: string) {
  node.environment ??= {}
  if (value) node.environment[key] = value
  else delete node.environment[key]
  if (node.secret_refs) delete node.secret_refs[key]
  dirty.value = true
}
function setNodeSecretRef(node: Node, key: string, value: string) {
  node.secret_refs ??= {}
  if (value) node.secret_refs[key] = value
  else delete node.secret_refs[key]
  if (node.environment) delete node.environment[key]
  dirty.value = true
}
function setNodeDependencies(node: Node, event: Event) {
  const select = event.target as HTMLSelectElement
  node.depends_on = Array.from(select.selectedOptions).map(option => option.value)
  dirty.value = true
}
function resourceText(profile: ServiceProfile) {
  return Object.entries(profile.resources).map(([key, value]) => `${key.replaceAll('_', ' ')} ${value}`).join(' · ')
}
function portsText(profile: ServiceProfile) {
  return profile.ports.map(port => `${port.container_port}/${port.protocol}`).join(', ') || 'aucun port conteneur défini'
}
function point(event: PointerEvent) {
  const svg = event.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const view = canvasView.value
  return {
    x: ((event.clientX - rect.left) * 760 / rect.width - view.x) / view.scale,
    y: ((event.clientY - rect.top) * 330 / rect.height - view.y) / view.scale,
  }
}
function zoomCanvas(event: WheelEvent) {
  const nextScale = Math.max(0.65, Math.min(2.2, canvasView.value.scale * (event.deltaY < 0 ? 1.1 : 0.9)))
  canvasView.value.scale = nextScale
}
function resetCanvasView() { canvasView.value = { x: 0, y: 0, scale: 1 } }
function startCanvasPan(event: PointerEvent) {
  const target = event.target as SVGElement
  if (target !== event.currentTarget) return
  const svg = event.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  canvasPanning.value = true
  const start = { x: event.clientX, y: event.clientY, viewX: canvasView.value.x, viewY: canvasView.value.y }
  const move = (moveEvent: PointerEvent) => {
    canvasView.value = { ...canvasView.value, x: start.viewX + (moveEvent.clientX - start.x) * 760 / rect.width, y: start.viewY + (moveEvent.clientY - start.y) * 330 / rect.height }
  }
  const stop = () => { canvasPanning.value = false; window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop) }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop)
}
function dragNode(event: PointerEvent, node: Node) {
  if (linkMode.value) { selectNode(node); return }
  captureTopologyHistory()
  const start = point(event); const offset = { x: start.x - node.position.x, y: start.y - node.position.y }
  const move = (moveEvent: PointerEvent) => { const next = point(moveEvent); node.position = { x: Math.max(10, Math.min(590, next.x - offset.x)), y: Math.max(10, Math.min(260, next.y - offset.y)) }; dirty.value = true }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop) }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop)
  selectNode(node)
}
async function refresh(loadTopology = !dirty.value) {
  const laboratoryId = activeLaboratoryId.value
  if (!laboratoryId) return
  try {
    if (loadTopology) {
      const response = await api.laboratory(laboratoryId)
      topology.value = response.topology
      selected.value = topology.value.nodes[0]?.name ?? null
    }
    const [status, eventLog, versionList] = await Promise.all([
      api.laboratoryStatus(laboratoryId),
      api.laboratoryLogs(laboratoryId),
      api.laboratoryVersions(laboratoryId),
    ])
    statuses.value = status.nodes
    logs.value = eventLog.logs
      .map(item => `${new Date(item.created_at * 1000).toLocaleString()} ${item.message}`)
      .reverse()
    versions.value = versionList.versions
    laboratories.value = (await api.laboratories()).laboratories
  } catch (error) { showError(error) }
}
async function loadObservability() {
  if (!['teacher', 'admin'].includes(user.value?.role ?? '') || observabilityLoading.value || !observabilityRefreshAllowed.value) return
  observabilityLoading.value = true
  observabilityRefreshAllowed.value = false
  observabilityCooldownTimer = window.setTimeout(() => {
    observabilityRefreshAllowed.value = true
    observabilityCooldownTimer = undefined
  }, 15000)
  observabilityError.value = ''
  try { observability.value = await api.observability() }
  catch (error) { observabilityError.value = error instanceof Error ? error.message : 'Erreur inconnue' }
  finally { observabilityLoading.value = false }
}
function bytesText(value: number | null) {
  if (value === null || !Number.isFinite(value)) return 'Indisponible'
  if (value < 0) return 'Indisponible'
  if (value < 1024) return `${value} o`
  const units = ['Kio', 'Mio', 'Gio', 'Tio']
  let amount = value / 1024; let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++ }
  return `${amount.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} ${units[unit]}`
}
function percentText(value: number | null) {
  return value === null || !Number.isFinite(value) ? 'Indisponible' : `${value.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %`
}
function numberText(value: number | null, suffix = '') {
  return value === null || !Number.isFinite(value) ? 'Indisponible' : `${value.toLocaleString('fr-FR', { maximumFractionDigits: 2 })}${suffix}`
}
function collectedAtText(value: string | null) {
  if (!value) return 'heure inconnue'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('fr-FR')
}
function topologyReady() {
  if (!topologyIssues.value.length) return true
  pageError.value = `Topologie invalide : ${topologyIssues.value[0]}`
  return false
}
async function action(name: 'up' | 'down' | 'verify') {
  if (!activeLaboratoryId.value) return
  if (!canModifyLaboratory.value) { pageError.value = 'Ce laboratoire est en lecture seule.'; return }
  if (operationBusy.value) return
  operationBusy.value = name
  try {
    if (name !== 'down' && !topologyReady()) return
    const result = await api.laboratoryAction(activeLaboratoryId.value, name)
    terminalOutput.value = result.output || (result.ok ? `${name}: terminé` : `${name}: échec (code ${result.exit_code})`)
    await refresh(false)
  } catch (error) { showError(error) }
  finally { operationBusy.value = '' }
}
async function save() {
  if (!topology.value || !topologyReady() || !activeLaboratoryId.value) return
  if (!canModifyLaboratory.value) { pageError.value = 'Ce laboratoire est en lecture seule.'; return }
  if (operationBusy.value) return
  operationBusy.value = 'save'
  try {
    const result = await api.saveLaboratory(activeLaboratoryId.value, topology.value)
    topology.value = result.topology
    dirty.value = false
    undoStack.value = []
    redoStack.value = []
    await refresh(false)
  } catch (error) { showError(error) }
  finally { operationBusy.value = '' }
}
async function restore() { if (!activeLaboratoryId.value || !versions.value.length) return; const raw = window.prompt(`Version à restaurer (${versions.value.map(version => version.version).join(', ')})`, String(versions.value[0].version)); const version = Number(raw); if (!Number.isInteger(version)) return; try { const response = await api.restoreLaboratory(activeLaboratoryId.value, version); topology.value = response.topology; dirty.value = false; await refresh(false) } catch (error) { showError(error) } }
async function cloneLab() { await createLaboratory() }
async function shareLaboratory() {
  if (!activeLaboratoryId.value || activeLaboratory.value?.role !== 'owner') return
  const email = window.prompt('Adresse e-mail du membre :')
  if (!email?.trim()) return
  const role = window.prompt('Rôle : editor ou viewer', 'viewer')
  if (role !== 'editor' && role !== 'viewer') { pageError.value = 'Rôle invalide : choisissez editor ou viewer.'; return }
  try { await api.addLaboratoryMember(activeLaboratoryId.value, email.trim(), role); pageError.value = `Accès ${role} accordé à ${email.trim()}.` }
  catch (error) { showError(error) }
}
async function exportLab() { if (!topology.value || !activeLaboratoryId.value) return; try { const payload = { format: 'netlab-laboratory-v1', topology: topology.value, versions: (await api.laboratoryVersions(activeLaboratoryId.value)).versions }; const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${topology.value.lab}.netlab.json`; link.click(); URL.revokeObjectURL(link.href) } catch (error) { showError(error) } }
async function importLab(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file) return; try { const payload = JSON.parse(await file.text()) as Topology | { topology: Topology }; const imported = 'topology' in payload ? payload.topology : payload; delete imported.laboratory_id; const response = await api.createLaboratory(imported); await loadLaboratories(); activeLaboratoryId.value = response.laboratory.id; topology.value = response.topology; selected.value = topology.value.nodes[0]?.name ?? null; dirty.value = false; terminalOutput.value = `laboratoire importé : ${topology.value.lab}`; await refresh(false) } catch (error) { showError(error) } finally { input.value = '' } }
async function runTerminal() { const socket = terminalSocket.value; const command = terminalCommand.value.trim(); if (!socket || socket.readyState !== WebSocket.OPEN || !command) { terminalOutput.value = 'Sélectionnez un nœud avec Docker actif.'; return }; socket.send(command); terminalCommand.value = '' }

function handleEditorShortcut(event: KeyboardEvent) {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return
  event.preventDefault()
  if (event.shiftKey) redoTopology()
  else undoTopology()
}

onMounted(async () => {
  window.addEventListener('keydown', handleEditorShortcut)
  await initialize()
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleEditorShortcut)
  if (timer) window.clearInterval(timer)
  if (observabilityTimer) window.clearInterval(observabilityTimer)
  if (observabilityCooldownTimer) window.clearTimeout(observabilityCooldownTimer)
  terminalSocket.value?.close()
})
</script>

<template>
  <template v-if="!user">
    <header><div><p class="eyebrow">NETLAB STUDIO / ESPACE SÉCURISÉ</p><h1>{{ setupAvailable ? `Créer le compte ${bootstrapRole === 'admin' ? 'administrateur' : 'enseignant'}` : 'Connexion' }}</h1></div><span class="badge">Prototype local</span></header>
    <main class="auth-main">
      <section class="panel auth-panel">
        <p class="hint">Les sessions sont protégées par cookie HttpOnly et jeton CSRF. Le service reste destiné à un usage local.</p>
        <form v-if="setupAvailable" @submit.prevent="bootstrap" class="stack-form">
          <label>Jeton de configuration<input v-model="setupToken" type="password" autocomplete="off" required /></label>
          <label>Nom affiché<input v-model="setupName" autocomplete="name" required maxlength="100" /></label>
          <label>Adresse e-mail<input v-model="setupEmail" type="email" autocomplete="email" required /></label>
          <label>Mot de passe initial (12 caractères minimum)<input v-model="setupPassword" type="password" autocomplete="new-password" minlength="12" required /></label>
          <button :disabled="busy">Initialiser le compte {{ bootstrapRole === 'admin' ? 'administrateur' : 'enseignant' }}</button>
        </form>
        <form v-else @submit.prevent="login" class="stack-form">
          <label>Adresse e-mail<input v-model="loginEmail" type="email" autocomplete="username" required /></label>
          <label>Mot de passe<input v-model="loginPassword" type="password" autocomplete="current-password" required /></label>
          <button :disabled="busy">Se connecter</button>
          <p v-if="!hasUsers" class="hint">Aucun compte n’existe. Configurez NETLAB_BOOTSTRAP_TOKEN puis rechargez cette page pour initialiser le premier enseignant.</p>
        </form>
        <details v-if="!setupAvailable" class="auth-recovery">
          <summary>Accepter une invitation</summary>
          <form class="stack-form" @submit.prevent="acceptInvitation">
            <label>Jeton d’invitation<input v-model="invitationToken" autocomplete="off" required /></label>
            <label>Mot de passe (12 caractères minimum)<input v-model="invitationPassword" type="password" autocomplete="new-password" minlength="12" required /></label>
            <button :disabled="busy">Créer mon compte</button>
          </form>
        </details>
        <details v-if="!setupAvailable" class="auth-recovery">
          <summary>Réinitialiser mon mot de passe</summary>
          <form class="stack-form" @submit.prevent="resetPassword">
            <label>Jeton de réinitialisation<input v-model="resetToken" autocomplete="off" required /></label>
            <label>Nouveau mot de passe (12 caractères minimum)<input v-model="resetPasswordDraft" type="password" autocomplete="new-password" minlength="12" required /></label>
            <button :disabled="busy">Changer le mot de passe</button>
          </form>
          <p class="hint">Demandez un jeton à un enseignant ou administrateur ; aucun jeton n’est envoyé par e-mail automatiquement.</p>
        </details>
        <p v-if="pageError" class="notice error">{{ pageError }}</p>
      </section>
    </main>
  </template>
  <template v-else-if="user.role === 'student'">
    <header><div><p class="eyebrow">NETLAB STUDIO / ESPACE ÉTUDIANT</p><h1>Bonjour, {{ user.display_name }}</h1></div><div class="header-actions"><span class="badge">{{ user.email }}</span><button class="secondary" @click="logout">Déconnexion</button></div></header>
    <main>
      <section class="panel">
        <div class="section-title"><div><h2>Mes travaux pratiques</h2><span>{{ assignments.length }} affectation(s)</span></div><button class="secondary" @click="loadAssignments">Actualiser</button></div>
        <p class="hint">Chaque copie possède son propre identifiant et ses propres ressources Docker. Arrêtez le laboratoire avant de le réinitialiser ou de le remettre.</p>
        <p v-if="!assignments.length" class="hint">Aucun laboratoire ne vous a encore été affecté.</p>
        <div v-else class="student-layout">
          <nav class="assignment-list"><button v-for="item in assignments" :key="item.id" class="secondary assignment-item" :class="{ active: activeAssignmentId === item.id }" @click="selectAssignment(item.id)"><strong>{{ item.title }}</strong><small>{{ item.group_name }} · {{ item.status }}</small></button></nav>
          <div v-if="activeAssignment" class="assignment-editor">
            <div class="section-title"><div><h2>{{ activeAssignment.title }}</h2><span>{{ activeAssignment.group_name }} · {{ activeAssignment.status }} · runtime {{ activeAssignment.runtime_status }}</span></div><div class="tools"><button class="secondary" @click="cloneAssignment">{{ activeAssignment.topology.laboratory_id ? 'Réinitialiser ma copie' : 'Créer ma copie' }}</button><button class="secondary" :disabled="['running', 'failed'].includes(activeAssignment.runtime_status)" @click="saveAssignment">Enregistrer la copie</button><button @click="submitAssignment">Remettre</button></div></div>
            <div class="assignment-instructions">
              <p v-if="activeAssignment.instructions">{{ activeAssignment.instructions }}</p>
              <div v-if="activeAssignment.criteria.length"><strong>Critères de réussite</strong><ul><li v-for="criterion in activeAssignment.criteria" :key="criterion">{{ criterion }}</li></ul></div>
            </div>
            <div class="tools">
              <button :disabled="activeAssignment.runtime_status === 'running' || activeAssignment.runtime_status === 'failed'" @click="studentRuntimeAction('up')">Déployer ma copie</button>
              <button class="secondary" :disabled="activeAssignment.runtime_status === 'stopped' || activeAssignment.runtime_status === 'expired'" @click="studentRuntimeAction('down')">Arrêter</button>
              <button class="secondary" :disabled="activeAssignment.runtime_status !== 'running'" @click="studentRuntimeAction('verify')">Vérifier la connectivité</button>
            </div>
            <section v-if="activeAssignment.topology.version >= 2" class="student-topology-editor">
              <div class="section-title"><div><h3>Éditeur réseau de ma copie</h3><span>modifiez les interfaces et les routes avant le déploiement</span></div></div>
              <label>Nœud à configurer<select v-model="studentSelectedNodeName"><option v-for="node in activeAssignment.topology.nodes" :key="node.name" :value="node.name">{{ node.name }}</option></select></label>
              <div v-if="selectedStudentNode" class="student-node-editor">
                <h4>{{ selectedStudentNode.name }} · Interfaces</h4>
                <div v-for="iface in selectedStudentNode.interfaces ?? []" :key="`${selectedStudentNode.name}-${iface.name}`" class="student-interface-row">
                  <strong>{{ iface.name }} · {{ iface.network }}</strong>
                  <label>IPv4<input v-model="iface.ipv4" placeholder="10.0.1.10/24" @input="studentDraftDirty = true" /></label>
                  <label>Passerelle<input v-model="iface.gateway" placeholder="10.0.1.1" @input="studentDraftDirty = true" /></label>
                </div>
                <div class="section-title routes-heading"><div><h4>Routes statiques</h4></div><button class="secondary" @click="addStudentRoute(selectedStudentNode)">Ajouter une route</button></div>
                <div v-for="(route, index) in selectedStudentNode.routes ?? []" :key="`${selectedStudentNode.name}-route-${index}`" class="student-interface-row student-route-row">
                  <label>Destination<input v-model="route.destination" placeholder="10.0.2.0/24" @input="studentDraftDirty = true" /></label>
                  <label>Passerelle<input v-model="route.via" placeholder="10.0.1.1" @input="studentDraftDirty = true" /></label>
                  <button class="danger" @click="removeStudentRoute(selectedStudentNode, index)">Supprimer</button>
                </div>
              </div>
              <p class="hint">{{ studentDraftDirty ? 'Modifications non enregistrées.' : 'Configuration enregistrée.' }}</p>
            </section>
            <p v-else class="hint">Cette topologie utilise le format ancien ; sa configuration est visible mais pas modifiable visuellement.</p>
            <section v-if="studentSubmissionHistory.length" class="submission-history">
              <h3>Historique des remises</h3>
              <article v-for="attempt in studentSubmissionHistory" :key="attempt.id">
                <strong>Tentative {{ attempt.attempt }} · {{ new Date(attempt.submitted_at * 1000).toLocaleString() }}</strong>
                <p v-if="attempt.grade !== null"><strong>Note :</strong> {{ attempt.grade }} / 100</p>
                <p v-if="attempt.feedback"><strong>Retour enseignant :</strong> {{ attempt.feedback }}</p>
                <p v-else class="muted">En attente du retour de l’enseignant.</p>
              </article>
            </section>
            <div v-if="activeAssignment.topology.laboratory_id" class="terminal-panel">
              <h3>Terminal de ma copie</h3>
              <div class="tools">
                <select v-model="studentTerminalNode" aria-label="Nœud étudiant">
                  <option v-for="node in activeAssignment.topology.nodes" :key="node.name" :value="node.name">{{ node.name }}</option>
                </select>
                <input v-model="studentTerminalCommand" aria-label="Commande autorisée" @keyup.enter="runStudentTerminal" />
                <button :disabled="activeAssignment.runtime_status !== 'running'" @click="runStudentTerminal">Exécuter</button>
              </div>
              <pre>{{ terminalOutput }}</pre>
              <p class="hint">Commandes disponibles : hostname, uname, ip, ping.</p>
            </div>
          </div>
        </div>
      </section>
      <p v-if="pageError" class="notice">{{ pageError }}</p>
    </main>
    <footer>Netlab Studio — copie pédagogique isolée avec historique de remise.</footer>
  </template>
  <template v-else>
    <header><div><p class="eyebrow">NETLAB STUDIO / ESPACE ENSEIGNANT</p><h1>{{ topology?.lab ?? 'Laboratoire' }}</h1><span v-if="activeLaboratory">Expire le {{ new Date(activeLaboratory.expires_at * 1000).toLocaleString() }}</span></div><div class="header-actions"><select :value="activeLaboratoryId" aria-label="Laboratoire actif" @change="switchLaboratory($event)"><option v-for="lab in laboratories" :key="lab.id" :value="lab.id">{{ lab.name }} · {{ lab.status }}</option></select><button class="secondary" @click="createLaboratory">Nouveau laboratoire</button><span class="badge online">{{ stateText }}</span><span class="badge">{{ user.display_name }}</span><button class="secondary" @click="logout">Déconnexion</button></div></header>
    <main>
      <p v-if="pageError" class="notice">{{ pageError }}<button class="notice-close" @click="pageError = ''">×</button></p>
      <template v-if="topology">
      <section class="toolbar">
        <button :disabled="!canModifyLaboratory || Boolean(operationBusy)" @click="action('up')">{{ operationBusy === 'up' ? 'Déploiement…' : 'Déployer' }}</button>
        <button class="secondary" :disabled="!canModifyLaboratory || Boolean(operationBusy)" @click="action('verify')">{{ operationBusy === 'verify' ? 'Test en cours…' : 'Tester la connectivité' }}</button>
        <button class="danger" :disabled="!canModifyLaboratory || Boolean(operationBusy)" @click="action('down')">{{ operationBusy === 'down' ? 'Arrêt…' : 'Arrêter' }}</button>
        <button class="secondary" :disabled="!canModifyLaboratory || Boolean(operationBusy)" @click="save">{{ operationBusy === 'save' ? 'Enregistrement…' : 'Nouvelle version' }}</button>
        <button class="secondary" :disabled="!canModifyLaboratory || Boolean(operationBusy)" @click="restore">Restaurer</button>
        <button class="secondary" :disabled="!undoStack.length" @click="undoTopology" title="Ctrl/Cmd+Z">Annuler</button>
        <button class="secondary" :disabled="!redoStack.length" @click="redoTopology" title="Ctrl/Cmd+Maj+Z">Rétablir</button>
        <button class="secondary" @click="cloneLab">Cloner</button>
        <button v-if="ownsLaboratory" class="secondary" @click="shareLaboratory">Partager</button>
        <button class="secondary" @click="exportLab">Exporter</button>
        <label v-if="canModifyLaboratory" class="file-button secondary">Importer<input type="file" accept="application/json,.json" @change="importLab" /></label>
        <select v-model="selectedTemplateId" class="template-select" aria-label="Modèle de laboratoire"><option v-for="template in labTemplates" :key="template.id" :value="template.id">{{ template.label }}</option></select>
        <button class="secondary" :disabled="!canModifyLaboratory" @click="applyTemplate">Charger le modèle</button>
        <span v-if="operationBusy" class="operation-status" role="status">Opération en cours…</span>
      </section>
      <section class="panel topology-workbench"><div class="section-title"><div><h2>Éditeur visuel</h2><span>glissez un équipement, puis reliez ses ports</span></div><div class="tools"><button class="secondary" @click="linkMode = !linkMode; linkStart = null; cableStart = null">{{ linkMode ? 'Annuler' : 'Relier par nœuds' }}</button><button class="danger" @click="removeSelected">Supprimer</button></div></div><div class="workbench"><aside class="palette"><div class="palette-heading"><strong>Équipements</strong><span>glisser-déposer</span></div><button v-for="item in paletteItems" :key="item.id" class="palette-item" :class="{ dragging: paletteDragId === item.id }" draggable="true" @dragstart="paletteDragStart(item, $event)" @dragend="paletteDragEnd"><span class="palette-icon">{{ item.icon }}</span><span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span></button><p class="palette-hint">Le switch virtuel ajoute un segment Docker bridge. Les ports sont les futures interfaces réseau du laboratoire.</p></aside><div class="canvas-wrap"><div class="canvas-help"><span>{{ cableHint }}</span><span v-if="cableStart" class="badge online">câblage en cours</span><div class="canvas-controls"><button class="icon-button secondary" title="Réduire" @click="canvasView.scale = Math.max(0.65, canvasView.scale - 0.1)">−</button><span>{{ Math.round(canvasView.scale * 100) }}%</span><button class="icon-button secondary" title="Agrandir" @click="canvasView.scale = Math.min(2.2, canvasView.scale + 0.1)">+</button><button class="icon-button secondary" title="Réinitialiser la vue" @click="resetCanvasView">Réinitialiser</button></div></div><svg class="canvas" :class="{ panning: canvasPanning }" viewBox="0 0 760 330" @dragover.prevent @drop.prevent="dropPalette" @wheel.prevent="zoomCanvas" @pointerdown="startCanvasPan"><g :transform="`translate(${canvasView.x} ${canvasView.y}) scale(${canvasView.scale})`"><line v-for="(link, index) in topology.links" :key="`link-${index}`" class="topology-link" :x1="portPoint(topology.nodes.find(node => node.name === link.from)!, linkPortIndex(topology.nodes.find(node => node.name === link.from)!, link.from_port)).x" :y1="portPoint(topology.nodes.find(node => node.name === link.from)!, linkPortIndex(topology.nodes.find(node => node.name === link.from)!, link.from_port)).y" :x2="portPoint(topology.nodes.find(node => node.name === link.to)!, linkPortIndex(topology.nodes.find(node => node.name === link.to)!, link.to_port)).x" :y2="portPoint(topology.nodes.find(node => node.name === link.to)!, linkPortIndex(topology.nodes.find(node => node.name === link.to)!, link.to_port)).y" /><g v-for="node in topology.nodes" :key="node.name" class="canvas-node" :class="{ selected: selected === node.name, invalid: nodeHasTopologyIssue(node.name) }" :transform="`translate(${node.position.x},${node.position.y})`" @pointerdown="dragNode($event, node)" @dblclick.stop="openDevicePanel(node)"><rect width="160" height="70" rx="10" /><title>{{ node.name }}{{ nodeHasTopologyIssue(node.name) ? ' — erreur de topologie' : '' }}</title><text class="canvas-node-title" x="14" y="24">{{ node.name }}</text><text class="canvas-node-image" x="14" y="44">{{ node.image }}</text><text class="canvas-node-type" x="14" y="60">{{ node.router ? 'ROUTEUR' : node.service_id ? node.service_id.toUpperCase() : 'HÔTE' }}</text><g v-for="portIndex in portCount(node)" :key="`${node.name}-port-${portIndex}`" class="canvas-port" :class="{ active: cableStart?.nodeName === node.name && cableStart?.portIndex === portIndex - 1, occupied: portIsOccupied(node, portIndex - 1) }" :transform="`translate(160,${18 + ((portIndex - 1) * 24) / Math.max(1, portCount(node) - 1)})`" @pointerdown.stop @click.stop="selectPort($event, node, portIndex - 1)"><circle r="6" /><title>{{ portLabel(node, portIndex - 1) }}{{ portIsOccupied(node, portIndex - 1) ? ' — occupé' : ' — libre' }}</title></g></g></g></svg></div></div></section>
      <section v-if="topology.version >= 2" class="panel topology-config">
        <div class="section-title"><div><h2>Configuration réseau v2</h2><span>segments Docker, interfaces IPv4 et routes statiques</span></div><button class="secondary" @click="addNetwork">Ajouter un segment</button></div>
        <div class="network-editor-grid">
          <article v-for="network in topologyNetworks" :key="network.name" class="nested network-editor-card">
            <div class="card-heading"><strong>{{ network.name }}</strong><button v-if="topologyNetworks.length > 1" class="icon-button danger" @click="removeNetwork(network.name)">Supprimer</button></div>
            <label>Nom du segment (identifiant)<input :value="network.name" readonly /></label>
            <label>Sous-réseau IPv4<input v-model="network.subnet" placeholder="10.0.1.0/24" @input="dirty = true" /></label>
          </article>
        </div>
        <div v-if="selectedNode" class="node-config">
          <div class="section-title"><div><h3>Nœud sélectionné : {{ selectedNode.name }}</h3><span>configuration de ses interfaces et routes</span></div><button class="secondary" @click="addInterface(selectedNode)">Ajouter une interface</button></div>
          <div class="node-basic-fields">
            <label>Image Docker<input v-model="selectedNode.image" :readonly="Boolean(selectedNode.service_id)" @input="dirty = true" /></label>
            <label v-if="!selectedNode.service_id">Commande de démarrage<input :value="nodeCommand(selectedNode)" placeholder="sleep infinity" @input="setNodeCommand(selectedNode, ($event.target as HTMLInputElement).value)" /></label>
            <p v-else class="hint">Le profil catalogue contrôle l’image et la commande de ce nœud.</p>
          </div>
          <div v-if="selectedServiceProfile?.environment.length" class="service-runtime-config">
            <div class="section-title"><div><h3>Configuration du service</h3><span>les valeurs secrètes restent hors de la topologie</span></div></div>
            <div v-for="requirement in selectedServiceProfile.environment" :key="requirement.name" class="interface-row">
              <label v-if="!requirement.secret">{{ requirement.name }}<input :value="selectedNode.environment?.[requirement.name] ?? ''" :placeholder="requirement.purpose" @input="setNodeEnvironment(selectedNode, requirement.name, ($event.target as HTMLInputElement).value)" /></label>
              <label v-else>{{ requirement.name }} — référence du secret<input :value="selectedNode.secret_refs?.[requirement.name] ?? ''" placeholder="ex. postgres-password" @input="setNodeSecretRef(selectedNode, requirement.name, ($event.target as HTMLInputElement).value)" /></label>
            </div>
            <p class="hint">Le worker lit les secrets sous la forme <code>NETLAB_SECRET_NOM_DU_SECRET</code>. Aucun mot de passe ne doit être saisi dans la topologie ou le dépôt.</p>
          </div>
          <label v-if="topology.nodes.length > 1">Dépendances de démarrage (Ctrl/Cmd pour plusieurs)<select multiple :value="selectedNode.depends_on ?? []" @change="setNodeDependencies(selectedNode, $event)"><option v-for="candidate in topology.nodes" :key="candidate.name" :value="candidate.name" :disabled="candidate.name === selectedNode.name">{{ candidate.name }}</option></select></label>
          <label class="router-toggle"><input v-model="selectedNode.router" type="checkbox" @change="selectedNode.type = selectedNode.router ? 'router' : 'linux'; dirty = true" /> Activer le forwarding IPv4 et les capacités routeur</label>
          <div class="interface-list">
            <div v-for="(interfaceItem, index) in selectedNode.interfaces" :key="`${selectedNode.name}-${index}`" class="interface-row">
              <input v-model="interfaceItem.name" aria-label="Nom de l’interface" placeholder="eth0" @input="dirty = true" />
              <select v-model="interfaceItem.network" aria-label="Segment de l’interface" @change="dirty = true"><option v-for="network in topologyNetworks" :key="network.name" :value="network.name">{{ network.name }}</option></select>
              <input v-model="interfaceItem.ipv4" aria-label="Adresse IPv4" placeholder="10.0.1.10/24" @input="dirty = true" />
              <input v-model="interfaceItem.gateway" aria-label="Passerelle" placeholder="Passerelle facultative" @input="dirty = true" />
              <button class="icon-button danger" :disabled="(selectedNode.interfaces?.length ?? 0) <= 1" @click="removeInterface(selectedNode, index)">×</button>
            </div>
          </div>
          <div class="section-title routes-heading"><div><h3>Routes statiques</h3><span>appliquées au déploiement Docker</span></div><button class="secondary" @click="addRoute(selectedNode)">Ajouter une route</button></div>
          <div class="route-list">
            <div v-for="(route, index) in selectedNode.routes" :key="`${selectedNode.name}-route-${index}`" class="interface-row">
              <input v-model="route.destination" aria-label="Destination de la route" placeholder="0.0.0.0/0" @input="dirty = true" />
              <input v-model="route.via" aria-label="Passerelle de la route" placeholder="10.0.1.1" @input="dirty = true" />
              <button class="icon-button danger" @click="removeRoute(selectedNode, index)">×</button>
            </div>
          </div>
          <template v-if="selectedNode.service_id === 'coredns'">
            <div class="section-title routes-heading"><div><h3>Entrées DNS A</h3><span>adresses du laboratoire uniquement</span></div><button class="secondary" @click="addDNSRecord(selectedNode)">Ajouter une entrée</button></div>
            <div class="route-list">
              <div v-for="(record, index) in selectedNode.dns_records" :key="`${selectedNode.name}-dns-${index}`" class="interface-row">
                <input v-model="record.name" aria-label="Nom DNS" placeholder="serveur.lab.test" @input="dirty = true" />
                <input v-model="record.ipv4" aria-label="Adresse IPv4 DNS" placeholder="10.0.1.10" @input="dirty = true" />
                <button class="icon-button danger" @click="removeDNSRecord(selectedNode, index)">×</button>
              </div>
            </div>
            <p class="hint">CoreDNS génère son Corefile à partir de ces entrées et le monte en lecture seule. La configuration n’accepte que des noms DNS et des adresses des sous-réseaux déclarés.</p>
          </template>
        </div>
        <p v-else class="hint">Sélectionnez un nœud dans le graphe pour modifier ses interfaces et ses routes.</p>
      </section>
      <section v-if="topology.version >= 2" class="panel connectivity-config">
        <div class="section-title"><div><h2>Test de connectivité</h2><span>commande contrôlée exécutée depuis le nœud source</span></div></div>
        <div class="connectivity-fields">
          <label>Nœud source<select v-model="topology.connectivity_check.from" @change="dirty = true"><option v-for="node in topology.nodes" :key="`from-${node.name}`" :value="node.name">{{ node.name }}</option></select></label>
          <label>Nœud destination<select v-model="topology.connectivity_check.to" @change="dirty = true"><option v-for="node in topology.nodes" :key="`to-${node.name}`" :value="node.name">{{ node.name }}</option></select></label>
          <label>Vérification<select :value="topology.connectivity_check.command[0] ?? 'ping'" @change="setConnectivityCommand(($event.target as HTMLSelectElement).value)"><option value="ping">ping</option><option value="getent">getent hosts</option><option value="ip">ip route</option></select></label>
        </div>
        <div v-if="topologyIssues.length" class="validation-box error"><strong>{{ topologyIssues.length }} problème(s) à corriger avant sauvegarde ou déploiement</strong><ul><li v-for="issue in topologyIssues" :key="issue">{{ issue }}</li></ul></div>
        <div v-else class="validation-box success">Topologie v2 cohérente localement. La validation serveur vérifiera aussi les CIDR, chevauchements de sous-réseaux et adresses IPv4.</div>
      </section>
      <section class="panel catalog-panel"><div class="section-title"><div><h2>Catalogue de services</h2><span>{{ deployableServices.length }} profils déployables localement · {{ serviceCatalog.length }} documentés</span></div></div><div class="catalog-grid"><article v-for="profile in serviceCatalog" :key="profile.id" class="catalog-card"><div class="catalog-card-head"><h3>{{ profile.label }}</h3><span class="catalog-status" :class="profile.status">{{ profile.status === 'ready' ? 'disponible' : profile.status === 'planned' ? 'prévu' : 'étude' }}</span></div><code>{{ profile.image ?? 'image VM à définir' }}</code><p><strong>Ports :</strong> {{ portsText(profile) }}</p><p><strong>Ressources :</strong> {{ resourceText(profile) }}</p><p v-if="profile.environment.length"><strong>Variables :</strong> {{ profile.environment.map(item => `${item.name}${item.secret ? ' (secret)' : ''}`).join(', ') }}</p><ul><li v-for="constraint in profile.constraints" :key="constraint">{{ constraint }}</li></ul></article></div></section>
      <section class="panel education-panel">
        <div class="section-title"><div><h2>Partage pédagogique</h2><span>Comptes, groupes, affectations et remises</span></div><button class="secondary" @click="loadEducation">Actualiser</button></div>
        <p class="hint">Chaque étudiant reçoit une copie isolée et exécutable. Les modèles et topologies affectés restent des instantanés indépendants.</p>
        <div class="education-grid">
          <form class="stack-form panel nested" @submit.prevent="createTeacher"><h3>Créer un autre compte enseignant</h3><label>Nom affiché<input v-model="newTeacher.display_name" required maxlength="100" /></label><label>E-mail<input v-model="newTeacher.email" type="email" required /></label><label>Mot de passe initial (12+)<input v-model="newTeacher.password" type="password" minlength="12" required /></label><button>Créer le compte enseignant</button><p class="hint">Transmettez le mot de passe initial séparément.</p></form>
          <form class="stack-form panel nested" @submit.prevent="createStudent"><h3>Créer un compte étudiant</h3><label>Nom affiché<input v-model="newStudent.display_name" required maxlength="100" /></label><label>E-mail<input v-model="newStudent.email" type="email" required /></label><label>Mot de passe initial (12+)<input v-model="newStudent.password" type="password" minlength="12" required /></label><button>Créer le compte</button></form>
          <form class="stack-form panel nested" @submit.prevent="createInvitation"><h3>Inviter un utilisateur</h3><label>Nom affiché<input v-model="newInvitation.display_name" required maxlength="100" /></label><label>E-mail<input v-model="newInvitation.email" type="email" required /></label><label>Rôle<select v-model="newInvitation.role"><option value="student">Étudiant</option><option v-if="user.role === 'admin'" value="teacher">Enseignant</option></select></label><label v-if="newInvitation.role === 'student'">Groupe initial<select v-model="newInvitation.group_id"><option value="">Aucun groupe</option><option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option></select></label><button>Créer l’invitation</button><p class="hint">Le jeton à usage unique s’affiche une fois. À transmettre par un canal distinct et sûr.</p><label v-if="invitationTokenIssued">Jeton à transmettre<textarea :value="invitationTokenIssued" rows="3" readonly /></label></form>
          <form class="stack-form panel nested" @submit.prevent="createGroup"><h3>Créer un groupe</h3><label>Nom du groupe<input v-model="newGroupName" required maxlength="100" /></label><button>Créer le groupe</button><label>Groupe actif<select v-model="selectedGroupId" @change="loadSubmissions"><option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }} ({{ group.members }})</option></select></label><label>Ajouter l’étudiant (e-mail)<input v-model="memberEmail" type="email" required /></label><button class="secondary" type="button" :disabled="!selectedGroupId" @click="addMember">Ajouter au groupe</button></form>
          <div class="panel nested assignment-form">
            <h3>Préparer et affecter un TP</h3>
            <label>Modèle de topologie<select v-model="assignmentTemplateId"><option value="current">Topologie actuelle — {{ topology.lab }}</option><option v-for="template in labTemplates" :key="template.id" :value="template.id">{{ template.label }}</option></select></label>
            <label>Titre de l’affectation<input v-model="assignmentTitle" :placeholder="topology.lab" maxlength="120" /></label>
            <label>Consignes<textarea v-model="assignmentInstructions" rows="3" maxlength="5000" placeholder="Présentez les objectifs et le travail attendu."></textarea></label>
            <label>Critères de réussite (un par ligne)<textarea v-model="assignmentCriteriaDraft" rows="3" maxlength="3000" placeholder="Le client atteint le serveur&#10;La route par défaut est correcte"></textarea></label>
            <button :disabled="!selectedGroupId" @click="publishAssignment">Affecter au groupe</button>
            <p class="hint">Le TP est figé au moment de l’affectation ; les futures modifications du laboratoire ne changeront pas les copies.</p>
          </div>
          <div class="panel nested"><h3>Comptes</h3><ul class="compact-list"><li v-for="account in users" :key="account.id">{{ account.display_name }} <small>{{ account.email }} · {{ account.role }}</small><button class="secondary" type="button" @click="issuePasswordReset(account)">Émettre un jeton de réinitialisation</button></li><li v-if="!users.length" class="muted">Aucun compte.</li></ul></div>
        </div>
        <div class="submissions"><h3>Suivi des remises {{ groups.find(group => group.id === selectedGroupId)?.name ? `— ${groups.find(group => group.id === selectedGroupId)?.name}` : '' }}</h3><table><thead><tr><th>TP</th><th>Étudiant</th><th>Statut</th><th>Runtime</th><th>Tentatives</th><th>Note / retour</th></tr></thead><tbody><tr v-for="(item, index) in submissions" :key="`${item.assignment_id}-${item.email}-${index}`"><td>{{ item.title }}</td><td>{{ item.display_name }} <small>{{ item.email }}</small></td><td>{{ item.status }}</td><td>{{ item.runtime_status }}</td><td>{{ item.attempt_count }}</td><td>{{ item.grade === null ? '—' : `${item.grade} / 100` }}<small>{{ item.feedback ? 'Retour transmis' : 'Pas de retour' }}</small><button v-if="item.attempt_count" class="secondary" @click="openSubmission(item)">Examiner</button></td></tr><tr v-if="!submissions.length"><td colspan="6" class="muted">Aucune affectation ou remise pour ce groupe.</td></tr></tbody></table></div>
        <section v-if="selectedSubmission" class="submission-review">
          <div class="section-title"><div><h3>Remises — {{ selectedSubmission.title }} / {{ selectedSubmission.display_name }}</h3><span>{{ teacherSubmissionHistory.length }} tentative(s)</span></div><button class="secondary" @click="selectedSubmission = null">Fermer</button></div>
          <article v-for="attempt in teacherSubmissionHistory" :key="attempt.id" class="submission-attempt">
            <div class="section-title"><strong>Tentative {{ attempt.attempt }} · {{ new Date(attempt.submitted_at * 1000).toLocaleString() }}</strong><span v-if="attempt.reviewed_at">Retourné le {{ new Date(attempt.reviewed_at * 1000).toLocaleString() }}</span></div>
            <details><summary>Consulter l’instantané remis</summary><pre>{{ JSON.stringify(attempt.topology, null, 2) }}</pre></details>
            <label>Retour à l’étudiant<textarea v-model="feedbackDrafts[attempt.id]" maxlength="4000" rows="3" placeholder="Commentaires sur cette tentative"></textarea></label>
            <label>Note sur 100<input v-model="gradeDrafts[attempt.id]" type="number" min="0" max="100" step="0.5" placeholder="Facultatif" /></label>
            <button class="secondary" @click="saveSubmissionFeedback(attempt)">Enregistrer le retour</button>
          </article>
        </section>
      </section>
      <section v-if="devicePanelOpen && selectedNode" class="device-modal" role="dialog" aria-modal="true" :aria-label="`Équipement ${selectedNode.name}`" @click.self="devicePanelOpen = false"><div class="device-window"><div class="section-title"><div><p class="eyebrow">ÉQUIPEMENT / CONSOLE</p><h2>{{ selectedNode.name }}</h2><span>{{ selectedNode.image }} · {{ nodeStatus(selectedNode.name) }}</span></div><button class="secondary" @click="devicePanelOpen = false">Fermer</button></div><div class="device-tabs" role="tablist" aria-label="Informations de l’équipement">
<button :class="{ active: devicePanelTab === 'terminal' }" role="tab" :aria-selected="devicePanelTab === 'terminal'" @click="devicePanelTab = 'terminal'; connectTerminal(selectedNode!.name)">Terminal</button>
<button :class="{ active: devicePanelTab === 'network' }" role="tab" :aria-selected="devicePanelTab === 'network'" @click="devicePanelTab = 'network'; terminalSocket?.close()">Réseau</button>
<button :class="{ active: devicePanelTab === 'logs' }" role="tab" :aria-selected="devicePanelTab === 'logs'" @click="devicePanelTab = 'logs'; terminalSocket?.close()">Journaux</button>
<button :class="{ active: devicePanelTab === 'resources' }" role="tab" :aria-selected="devicePanelTab === 'resources'" @click="devicePanelTab = 'resources'; terminalSocket?.close()">Ressources</button>
</div>
<div v-if="devicePanelTab === 'terminal'" class="device-terminal"><div class="terminal"><div>{{ terminalOutput }}</div><form @submit.prevent="runTerminal"><span>$</span><input v-model="terminalCommand" aria-label="Commande terminal" placeholder="commande shell" /><button>Envoyer</button></form></div><p class="hint">Les commandes passent par le WebSocket vers le conteneur réel. Le terminal n’est disponible que lorsque le laboratoire est démarré.</p></div>
<div v-else-if="devicePanelTab === 'network'" class="device-config"><div class="device-summary"><span class="badge online">{{ selectedNode.router ? 'routeur' : selectedNode.service_id ? selectedNode.service_id : 'hôte Linux' }}</span><span>{{ selectedNodeLinks.length }} câble(s) connecté(s)</span></div><div class="device-interfaces"><strong>Interfaces réseau</strong><div v-for="interfaceItem in selectedNode.interfaces" :key="`${selectedNode.name}-${interfaceItem.name}`" class="interface-row"><span>{{ interfaceItem.name }}</span><span>{{ interfaceItem.network }}</span><span>{{ interfaceItem.ipv4 || 'adresse automatique' }}</span><span>{{ interfaceItem.gateway || 'sans passerelle' }}</span></div><p v-if="!selectedNode.interfaces?.length" class="hint">Aucune interface configurée.</p></div><div class="device-links"><strong>Câbles</strong><ul><li v-for="link in selectedNodeLinks" :key="`${link.from}-${link.to}-${link.from_port}-${link.to_port}`">{{ link.from }}.{{ link.from_port || 'eth0' }} ↔ {{ link.to }}.{{ link.to_port || 'eth0' }}</li><li v-if="!selectedNodeLinks.length" class="muted">Aucun câble connecté.</li></ul></div><p class="hint">La configuration détaillée des interfaces et routes reste disponible dans le panneau réseau sous le canvas.</p></div>
<div v-else-if="devicePanelTab === 'logs'" class="device-log-panel"><div class="section-title"><strong>Événements associés</strong><span>{{ selectedNodeLogs.length }} entrée(s)</span></div><pre>{{ selectedNodeLogs.length ? selectedNodeLogs.join('\n') : 'Aucun événement associé à cet équipement.' }}</pre><p class="hint">Les événements généraux du laboratoire restent visibles dans le journal principal.</p></div>
<div v-else class="device-resource-panel"><div class="resource-grid"><article><span>État</span><strong>{{ selectedObservabilityNode?.state || nodeStatus(selectedNode.name) }}</strong></article><article><span>CPU</span><strong>{{ selectedObservabilityNode?.cpu_percent == null ? '—' : `${selectedObservabilityNode.cpu_percent.toFixed(1)} %` }}</strong></article><article><span>Mémoire</span><strong>{{ selectedObservabilityNode?.memory_percent == null ? '—' : `${selectedObservabilityNode.memory_percent.toFixed(1)} %` }}</strong></article><article><span>Réseau</span><strong>{{ selectedObservabilityNode ? `${bytesText(selectedObservabilityNode.network_rx_bytes)} reçus · ${bytesText(selectedObservabilityNode.network_tx_bytes)} envoyés` : '—' }}</strong></article></div><p v-if="!selectedObservabilityNode" class="hint">Les métriques détaillées apparaîtront lorsque Docker sera disponible et que la supervision aura collecté cet équipement.</p><div v-else class="resource-details"><span>Image <strong>{{ selectedObservabilityNode.image }}</strong></span><span>Processus <strong>{{ selectedObservabilityNode.pids_limit ?? 'sans limite déclarée' }}</strong></span><span>Stockage écrivable <strong>{{ bytesText(selectedObservabilityNode.writable_size_bytes) }}</strong></span></div></div>
</div></section>
      <section class="lower"><div class="panel"><div class="section-title"><h2>Terminal WebSocket</h2><span>{{ selectedNode?.name ?? 'aucun nœud' }} · {{ selectedNode ? nodeStatus(selectedNode.name) : '' }}</span></div><div class="terminal"><div>{{ terminalOutput }}</div><form @submit.prevent="runTerminal"><span>$</span><input v-model="terminalCommand" aria-label="Commande terminal" placeholder="commande shell" /><button>Envoyer</button></form></div></div><div class="panel"><div class="section-title"><h2>Journal</h2></div><pre>{{ logs.length ? logs.join('\n') : 'Aucun événement.' }}</pre></div></section>
      </template>
      <p v-if="!topology" class="loading">Impossible de charger le laboratoire. Vérifiez l’API et la configuration du compte.</p>
      <section class="panel observability-panel" aria-labelledby="observability-title">
        <div class="section-title observability-heading"><div><p class="eyebrow">SUPERVISION / ÉTAPE 9</p><h2 id="observability-title">État de la plateforme</h2><span v-if="observability?.collected_at">Collecté {{ collectedAtText(observability.collected_at) }}</span></div><div class="observability-actions"><span class="badge" :class="observability?.available ? 'online' : ''">{{ observabilityLoading && !observability ? 'Chargement…' : observability?.available ? 'Docker disponible' : 'Docker indisponible' }}</span><button class="secondary" :disabled="observabilityLoading || !observabilityRefreshAllowed" @click="loadObservability">{{ observabilityRefreshAllowed ? 'Actualiser' : 'Actualisation différée' }}</button></div></div>
        <p v-if="observabilityError" class="observability-error">{{ observabilityError }}<span v-if="!observability">Le service de supervision n’est pas disponible pour le moment.</span></p>
        <p v-if="observabilityLoading && !observability" class="hint">Chargement des indicateurs de supervision…</p>
        <template v-if="observability?.available">
          <div class="observability-stats">
            <article class="obs-stat"><span>Laboratoires actifs</span><strong>{{ observability.active_lab_count }}</strong></article>
            <article class="obs-stat"><span>Nœuds actifs</span><strong>{{ observability.running_node_count }}</strong></article>
            <article class="obs-stat"><span>Utilisateurs</span><strong>{{ users.length }}</strong><small>comptes connus</small></article>
          </div>
          <div class="obs-section">
            <div class="obs-section-title"><h3>Laboratoires</h3><span>{{ observability.labs.length }} recensé(s)</span></div>
            <div v-if="observability.labs.length" class="obs-lab-grid">
              <article v-for="lab in observability.labs" :key="lab.name" class="obs-lab-card">
                <div class="obs-card-heading"><strong>{{ lab.name }}</strong><span class="badge">{{ lab.running_count }}/{{ lab.node_count }} nœud(s)</span></div>
                <div class="obs-meter"><span>CPU</span><strong>{{ percentText(lab.cpu_percent) }}</strong></div>
                <div class="obs-meter"><span>Mémoire</span><strong>{{ bytesText(lab.memory_usage_bytes) }}</strong></div>
                <div class="obs-meter"><span>Réseau RX / TX</span><strong>{{ bytesText(lab.network_rx_bytes) }} / {{ bytesText(lab.network_tx_bytes) }}</strong></div>
              </article>
            </div>
            <p v-else class="muted obs-empty">Aucun laboratoire actif recensé.</p>
          </div>
          <div class="obs-section">
            <div class="obs-section-title"><h3>Nœuds</h3><span>{{ observability.nodes.length }} recensé(s)</span></div>
            <div v-if="observability.nodes.length" class="obs-node-list">
              <article v-for="node in observability.nodes" :key="node.id" class="obs-node-card">
                <div class="obs-node-heading"><div><strong>{{ node.name }}</strong><small>{{ node.lab }} · {{ node.image }}</small></div><span class="catalog-status" :class="node.state === 'running' ? 'ready' : 'planned'">{{ node.state || 'état inconnu' }}</span></div>
                <p class="obs-node-status">{{ node.status || 'Statut détaillé indisponible' }}<span v-if="node.ports"> · Ports {{ node.ports }}</span></p>
                <div class="obs-node-metrics">
                  <span>CPU <strong>{{ percentText(node.cpu_percent) }}</strong></span>
                  <span>Mémoire <strong>{{ bytesText(node.memory_usage_bytes) }} / {{ bytesText(node.memory_limit_bytes) }}</strong> <small>({{ percentText(node.memory_percent) }})</small></span>
                  <span>Writable <strong>{{ bytesText(node.writable_size_bytes) }}</strong></span>
                  <span>I/O bloc R / W <strong>{{ bytesText(node.block_read_bytes) }} / {{ bytesText(node.block_write_bytes) }}</strong></span>
                  <span>Trafic RX / TX <strong>{{ bytesText(node.network_rx_bytes) }} / {{ bytesText(node.network_tx_bytes) }}</strong></span>
                  <span v-if="node.cpu_limit_cores !== null">Limite CPU <strong>{{ numberText(node.cpu_limit_cores, ' cœur(s)') }}</strong></span>
                  <span v-if="node.pids_limit !== null">Limite PID <strong>{{ numberText(node.pids_limit) }}</strong></span>
                </div>
                <div v-if="node.networks.length" class="obs-tags"><span v-for="network in node.networks" :key="network">{{ network }}</span></div>
              </article>
            </div>
            <p v-else class="muted obs-empty">Aucun nœud recensé.</p>
          </div>
          <div class="obs-two-columns">
            <section class="obs-section"><div class="obs-section-title"><h3>Réseaux Docker</h3><span>{{ observability.networks.length }}</span></div><div v-if="observability.networks.length" class="obs-table-wrap"><table class="obs-table"><thead><tr><th>Réseau</th><th>Laboratoire</th><th>Pilote</th><th>Portée</th></tr></thead><tbody><tr v-for="network in observability.networks" :key="`${network.name}-${network.lab ?? 'global'}`"><td>{{ network.name }}</td><td>{{ network.lab ?? 'Global' }}</td><td>{{ network.driver || 'Indisponible' }}</td><td>{{ network.scope || 'Indisponible' }}</td></tr></tbody></table></div><p v-else class="muted obs-empty">Aucun réseau recensé.</p></section>
            <section class="obs-section"><div class="obs-section-title"><h3>Stockage Docker</h3><span>Vue globale</span></div><div v-if="observability.storage.length" class="obs-table-wrap"><table class="obs-table"><thead><tr><th>Type</th><th>Objets actifs / total</th><th>Utilisé</th><th>Récupérable</th></tr></thead><tbody><tr v-for="storage in observability.storage" :key="storage.kind"><td>{{ storage.kind }}</td><td>{{ numberText(storage.active_count) }} / {{ numberText(storage.total_count) }}</td><td>{{ bytesText(storage.used_bytes) }}</td><td>{{ bytesText(storage.reclaimable_bytes) }}</td></tr></tbody></table></div><p v-else class="muted obs-empty">Aucune donnée de stockage.</p></section>
          </div>
          <div class="obs-two-columns obs-messages">
            <section class="obs-section"><div class="obs-section-title"><h3>Alertes et erreurs</h3><span>{{ observability.alerts.length + observability.errors.length }}</span></div><ul class="obs-message-list"><li v-for="(alert, index) in observability.alerts" :key="`alert-${index}`" class="obs-message" :class="alert.severity"><strong>{{ alert.severity === 'error' ? 'Erreur' : 'Alerte' }}<span v-if="alert.lab"> · {{ alert.lab }}</span><span v-if="alert.node"> / {{ alert.node }}</span></strong><p>{{ alert.message }}</p></li><li v-for="(error, index) in observability.errors" :key="`error-${index}`" class="obs-message error"><strong>Erreur de collecte</strong><p>{{ error }}</p></li><li v-if="!observability.alerts.length && !observability.errors.length" class="muted">Aucune alerte ni erreur.</li></ul></section>
            <section class="obs-section"><div class="obs-section-title"><h3>Événements récents</h3><span>{{ observability.events.length }}{{ observability.truncated ? '+' : '' }}</span></div><ul class="obs-event-list"><li v-for="(event, index) in observability.events" :key="index">{{ event }}</li><li v-if="!observability.events.length" class="muted">Aucun événement récent.</li></ul><p v-if="observability.truncated" class="obs-truncated">Liste tronquée par le service.</p></section>
          </div>
          <p class="obs-thresholds">Seuils configurés — CPU {{ percentText(observability.thresholds.cpu_percent) }} · mémoire {{ percentText(observability.thresholds.memory_percent) }} · espace writable {{ numberText(observability.thresholds.writable_storage_mb, ' Mo') }}</p>
        </template>
        <div v-else-if="!observabilityLoading && !observabilityError && observability">
          <p class="obs-unavailable">Le moteur Docker est absent ou indisponible. Les données de supervision ne peuvent pas être collectées pour le moment.</p>
          <ul v-if="observability.errors.length" class="obs-message-list"><li v-for="(error, index) in observability.errors" :key="`unavailable-${index}`" class="obs-message error"><strong>Erreur de collecte</strong><p>{{ error }}</p></li></ul>
        </div>
        <p v-else-if="!observability && !observabilityLoading && !observabilityError" class="obs-unavailable">Aucune donnée de supervision n’est disponible.</p>
      </section>
    </main>
    <footer>Netlab Studio — accès réservé au compte enseignant ; les étudiants ne reçoivent pas d’accès au socket Docker.</footer>
  </template>
</template>
