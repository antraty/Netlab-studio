<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import type { Assignment, Group, ObservabilitySnapshot, ServiceProfile, User } from './api'
import type { Node, StatusNode, Topology, VersionInfo } from './types'

const user = ref<User | null>(null)
const setupAvailable = ref(false)
const hasUsers = ref(true)
const pageError = ref('')
const loginEmail = ref('')
const loginPassword = ref('')
const setupToken = ref('')
const setupName = ref('')
const setupEmail = ref('')
const setupPassword = ref('')
const topology = ref<Topology | null>(null)
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
const submissions = ref<Array<{ assignment_id: string; title: string; email: string; display_name: string; status: string; submitted_at: number | null }>>([])
const assignments = ref<Assignment[]>([])
const activeAssignmentId = ref('')
const assignmentDraft = ref('')
const newStudent = ref({ email: '', display_name: '', password: '' })
const newGroupName = ref('')
const memberEmail = ref('')
const assignmentTitle = ref('')
const selectedGroupId = ref('')
const busy = ref(false)
const observability = ref<ObservabilitySnapshot | null>(null)
const observabilityLoading = ref(false)
const observabilityError = ref('')
const observabilityRefreshAllowed = ref(true)
let timer: number | undefined
let observabilityTimer: number | undefined
let observabilityCooldownTimer: number | undefined

const selectedNode = computed(() => topology.value?.nodes.find(node => node.name === selected.value))
const stateText = computed(() => dirty.value ? 'modifications non sauvegardées' : 'contrôle actif')
const activeAssignment = computed(() => assignments.value.find(item => item.id === activeAssignmentId.value))
const deployableServices = computed(() => serviceCatalog.value.filter(profile => profile.deployable))
function nodeStatus(name: string) { return statuses.value.find(node => node.name === name)?.state ?? 'inconnu' }
function showError(error: unknown) { pageError.value = error instanceof Error ? error.message : 'Erreur inconnue' }

async function initialize() {
  pageError.value = ''
  try {
    const state = await api.authState()
    hasUsers.value = state.has_users
    setupAvailable.value = state.bootstrap_enabled && !state.has_users
    try { user.value = (await api.me()).user } catch { user.value = null }
    if (!user.value) return
    if (user.value.role === 'teacher') {
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
async function login() {
  busy.value = true
  try { const result = await api.login(loginEmail.value, loginPassword.value); user.value = result.user; loginPassword.value = ''; await initialize() }
  catch (error) { showError(error) }
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
  terminalSocket.value?.close(); user.value = null; topology.value = null; assignments.value = []; observability.value = null; pageError.value = ''
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
    const result = await api.assign(selectedGroupId.value, assignmentTitle.value.trim() || topology.value.lab, topology.value)
    assignmentTitle.value = ''; pageError.value = `Laboratoire partagé : ${result.assignment.title}`; await loadSubmissions()
  } catch (error) { showError(error) }
}
async function loadSubmissions() {
  if (!selectedGroupId.value || user.value?.role !== 'teacher') { submissions.value = []; return }
  try { submissions.value = (await api.submissions(selectedGroupId.value)).submissions }
  catch (error) { showError(error) }
}
async function loadAssignments() {
  try {
    assignments.value = (await api.myAssignments()).assignments
    activeAssignmentId.value = assignments.value[0]?.id ?? ''
    assignmentDraft.value = activeAssignment.value ? JSON.stringify(activeAssignment.value.topology, null, 2) : ''
  } catch (error) { showError(error) }
}
function selectAssignment(id: string) {
  activeAssignmentId.value = id
  const item = activeAssignment.value
  assignmentDraft.value = item ? JSON.stringify(item.topology, null, 2) : ''
}
async function cloneAssignment() {
  if (!activeAssignment.value) return
  try {
    const result = await api.cloneAssignment(activeAssignment.value.id)
    activeAssignment.value.topology = result.topology
    activeAssignment.value.status = 'in_progress'
    assignmentDraft.value = JSON.stringify(result.topology, null, 2)
  } catch (error) { showError(error) }
}
async function saveAssignment() {
  if (!activeAssignment.value) return false
  try {
    const parsed = JSON.parse(assignmentDraft.value) as Topology
    await api.saveAssignmentTopology(activeAssignment.value.id, parsed)
    activeAssignment.value.topology = parsed; activeAssignment.value.status = 'in_progress'
    pageError.value = 'Copie personnelle enregistrée.'
    return true
  } catch (error) { showError(error); return false }
}
async function submitAssignment() {
  if (!activeAssignment.value) return
  try {
    if (activeAssignment.value.status === 'assigned') await cloneAssignment()
    if (!await saveAssignment()) return
    await api.submitAssignment(activeAssignment.value.id)
    activeAssignment.value.status = 'submitted'; pageError.value = 'Travail remis à l’enseignant.'
  } catch (error) { showError(error) }
}

function selectNode(node: Node) {
  if (linkMode.value) {
    if (!linkStart.value) linkStart.value = node.name
    else if (linkStart.value !== node.name && topology.value) {
      topology.value.links ??= []
      const exists = topology.value.links.some(link => (link.from === linkStart.value && link.to === node.name) || (link.from === node.name && link.to === linkStart.value))
      if (!exists) topology.value.links.push({ from: linkStart.value, to: node.name })
      linkStart.value = null; linkMode.value = false; dirty.value = true
    }
    return
  }
  selected.value = node.name
  connectTerminal(node.name)
}
function connectTerminal(nodeName: string) {
  terminalSocket.value?.close()
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/nodes/${encodeURIComponent(nodeName)}/terminal`)
  socket.onopen = () => { terminalOutput.value = `Connexion au terminal de ${nodeName}…` }
  socket.onmessage = event => { terminalOutput.value += event.data }
  socket.onerror = () => { terminalOutput.value += '\nErreur de connexion terminal.' }
  terminalSocket.value = socket
}
function removeSelected() {
  if (!topology.value || !selected.value) return
  topology.value.nodes = topology.value.nodes.filter(node => node.name !== selected.value)
  topology.value.links = topology.value.links.filter(link => link.from !== selected.value && link.to !== selected.value)
  selected.value = topology.value.nodes[0]?.name ?? null; dirty.value = true
}
function addNode() {
  if (!topology.value) return
  const name = window.prompt('Nom du nœud :', `linux-node-${topology.value.nodes.length + 1}`)
  const image = window.prompt('Image Docker :', 'ubuntu:24.04')
  if (!name || !image || topology.value.nodes.some(node => node.name === name)) return
  topology.value.nodes.push({ name, image, command: ['sleep', 'infinity'], position: { x: 60 + topology.value.nodes.length * 210, y: 110 } })
  selected.value = name; dirty.value = true
}
function addCatalogService() {
  if (!topology.value) return
  const profile = deployableServices.value.find(item => item.id === selectedServiceId.value)
  if (!profile?.image) return
  const name = window.prompt('Nom du nœud :', `${profile.id}-${topology.value.nodes.length + 1}`)
  if (!name) return
  if (topology.value.nodes.some(node => node.name === name)) { pageError.value = 'Ce nom de nœud existe déjà.'; return }
  let publishedPort: number | undefined
  if (profile.primary_port) {
    const rawPort = window.prompt(`Port hôte facultatif lié seulement à 127.0.0.1 (port du conteneur ${profile.primary_port}). Vide = réseau Docker uniquement.`, '')
    if (rawPort === null) return
    if (rawPort.trim()) {
      const parsed = Number(rawPort)
      if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) { pageError.value = 'Le port doit être un entier entre 1 et 65535.'; return }
      if (topology.value.nodes.some(node => node.published_port === parsed)) { pageError.value = 'Ce port hôte est déjà utilisé dans cette topologie.'; return }
      publishedPort = parsed
    }
  }
  const node: Node = {
    name, image: profile.image, command: [...profile.command], service_id: profile.id,
    position: { x: 60 + topology.value.nodes.length * 210, y: 110 },
  }
  if (publishedPort !== undefined) node.published_port = publishedPort
  topology.value.nodes.push(node); selected.value = name; dirty.value = true
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
  return { x: (event.clientX - rect.left) * 760 / rect.width, y: (event.clientY - rect.top) * 330 / rect.height }
}
function dragNode(event: PointerEvent, node: Node) {
  if (linkMode.value) { selectNode(node); return }
  const start = point(event); const offset = { x: start.x - node.position.x, y: start.y - node.position.y }
  const move = (moveEvent: PointerEvent) => { const next = point(moveEvent); node.position = { x: Math.max(10, Math.min(590, next.x - offset.x)), y: Math.max(10, Math.min(260, next.y - offset.y)) }; dirty.value = true }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop) }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop)
  selectNode(node)
}
async function refresh(loadTopology = !dirty.value) {
  try {
    if (loadTopology) { const response = await api.topology(); topology.value = response.topology; selected.value ??= topology.value.nodes[0]?.name ?? null }
    const [status, eventLog] = await Promise.all([api.status(), api.logs()]); statuses.value = status.nodes; logs.value = eventLog.logs
    if (topology.value) versions.value = (await api.versions(topology.value.lab)).versions
  } catch (error) { showError(error) }
}
async function loadObservability() {
  if (user.value?.role !== 'teacher' || observabilityLoading.value || !observabilityRefreshAllowed.value) return
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
async function action(name: 'up' | 'down' | 'verify') { try { const result = await api.action(name); terminalOutput.value = result.ok ? `${name}: terminé` : `${name}: échec (code ${result.exit_code})`; await refresh() } catch (error) { showError(error) } }
async function save() { if (!topology.value) return; try { await api.save(topology.value); dirty.value = false; await refresh() } catch (error) { showError(error) } }
async function restore() { if (!topology.value || !versions.value.length) return; const raw = window.prompt(`Version à restaurer (${versions.value.map(version => version.version).join(', ')})`, String(versions.value[0].version)); const version = Number(raw); if (!Number.isInteger(version)) return; try { const response = await api.restore(topology.value.lab, version); topology.value = response.topology; dirty.value = false; await refresh(false) } catch (error) { showError(error) } }
async function cloneLab() { if (!topology.value) return; const newLab = window.prompt('Nom du laboratoire cloné :', `${topology.value.lab}-copy`); if (!newLab) return; try { await api.clone(topology.value.lab, newLab); terminalOutput.value = `laboratoire cloné : ${newLab}`; await refresh(false) } catch (error) { showError(error) } }
async function exportLab() { if (!topology.value) return; try { const payload = await api.export(topology.value.lab); const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${topology.value.lab}.netlab.json`; link.click(); URL.revokeObjectURL(link.href) } catch (error) { showError(error) } }
async function importLab(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file) return; try { const payload = JSON.parse(await file.text()); const response = await api.import(payload.topology ?? payload); topology.value = response.topology; selected.value = topology.value.nodes[0]?.name ?? null; dirty.value = false; terminalOutput.value = `laboratoire importé : ${topology.value.lab}`; await refresh(false) } catch (error) { showError(error) } finally { input.value = '' } }
async function runTerminal() { const socket = terminalSocket.value; const command = terminalCommand.value.trim(); if (!socket || socket.readyState !== WebSocket.OPEN || !command) { terminalOutput.value = 'Sélectionnez un nœud avec Docker actif.'; return }; socket.send(command); terminalCommand.value = '' }

onMounted(async () => { await initialize() })
onUnmounted(() => { if (timer) window.clearInterval(timer); if (observabilityTimer) window.clearInterval(observabilityTimer); if (observabilityCooldownTimer) window.clearTimeout(observabilityCooldownTimer); terminalSocket.value?.close() })
</script>

<template>
  <template v-if="!user">
    <header><div><p class="eyebrow">NETLAB STUDIO / ESPACE SÉCURISÉ</p><h1>{{ setupAvailable ? 'Créer le compte enseignant' : 'Connexion' }}</h1></div><span class="badge">Prototype local</span></header>
    <main class="auth-main">
      <section class="panel auth-panel">
        <p class="hint">Les sessions sont protégées par cookie HttpOnly et jeton CSRF. Le service reste destiné à un usage local.</p>
        <form v-if="setupAvailable" @submit.prevent="bootstrap" class="stack-form">
          <label>Jeton de configuration<input v-model="setupToken" type="password" autocomplete="off" required /></label>
          <label>Nom affiché<input v-model="setupName" autocomplete="name" required maxlength="100" /></label>
          <label>Adresse e-mail<input v-model="setupEmail" type="email" autocomplete="email" required /></label>
          <label>Mot de passe initial (12 caractères minimum)<input v-model="setupPassword" type="password" autocomplete="new-password" minlength="12" required /></label>
          <button :disabled="busy">Initialiser le compte enseignant</button>
        </form>
        <form v-else @submit.prevent="login" class="stack-form">
          <label>Adresse e-mail<input v-model="loginEmail" type="email" autocomplete="username" required /></label>
          <label>Mot de passe<input v-model="loginPassword" type="password" autocomplete="current-password" required /></label>
          <button :disabled="busy">Se connecter</button>
          <p v-if="!hasUsers" class="hint">Aucun compte n’existe. Configurez NETLAB_BOOTSTRAP_TOKEN puis rechargez cette page pour initialiser le premier enseignant.</p>
        </form>
        <p v-if="pageError" class="notice error">{{ pageError }}</p>
      </section>
    </main>
  </template>
  <template v-else-if="user.role === 'student'">
    <header><div><p class="eyebrow">NETLAB STUDIO / ESPACE ÉTUDIANT</p><h1>Bonjour, {{ user.display_name }}</h1></div><div class="header-actions"><span class="badge">{{ user.email }}</span><button class="secondary" @click="logout">Déconnexion</button></div></header>
    <main>
      <section class="panel">
        <div class="section-title"><div><h2>Mes travaux pratiques</h2><span>{{ assignments.length }} affectation(s)</span></div><button class="secondary" @click="loadAssignments">Actualiser</button></div>
        <p class="hint">Les topologies sont des copies personnelles sauvegardées. Elles ne lancent pas de conteneurs : l’exécution isolée par étudiant n’est pas encore disponible.</p>
        <p v-if="!assignments.length" class="hint">Aucun laboratoire ne vous a encore été affecté.</p>
        <div v-else class="student-layout">
          <nav class="assignment-list"><button v-for="item in assignments" :key="item.id" class="secondary assignment-item" :class="{ active: activeAssignmentId === item.id }" @click="selectAssignment(item.id)"><strong>{{ item.title }}</strong><small>{{ item.group_name }} · {{ item.status }}</small></button></nav>
          <div v-if="activeAssignment" class="assignment-editor">
            <div class="section-title"><div><h2>{{ activeAssignment.title }}</h2><span>{{ activeAssignment.group_name }} · {{ activeAssignment.status }}</span></div><div class="tools"><button class="secondary" @click="cloneAssignment">Créer / réinitialiser ma copie</button><button class="secondary" @click="saveAssignment">Enregistrer la copie</button><button @click="submitAssignment">Remettre</button></div></div>
            <label class="json-label">Topologie JSON personnelle<textarea v-model="assignmentDraft" spellcheck="false"></textarea></label>
          </div>
        </div>
      </section>
      <p v-if="pageError" class="notice">{{ pageError }}</p>
    </main>
    <footer>Netlab Studio — copie pédagogique sauvegardée ; aucun déploiement Docker étudiant n’est exposé.</footer>
  </template>
  <template v-else>
    <header><div><p class="eyebrow">NETLAB STUDIO / ESPACE ENSEIGNANT</p><h1>{{ topology?.lab ?? 'Laboratoire' }}</h1></div><div class="header-actions"><span class="badge online">{{ stateText }}</span><span class="badge">{{ user.display_name }}</span><button class="secondary" @click="logout">Déconnexion</button></div></header>
    <main>
      <p v-if="pageError" class="notice">{{ pageError }}<button class="notice-close" @click="pageError = ''">×</button></p>
      <template v-if="topology">
      <section class="toolbar"><button @click="action('up')">Déployer</button><button class="secondary" @click="action('verify')">Tester la connectivité</button><button class="danger" @click="action('down')">Arrêter</button><button class="secondary" @click="save">Nouvelle version</button><button class="secondary" @click="restore">Restaurer</button><button class="secondary" @click="cloneLab">Cloner</button><button class="secondary" @click="exportLab">Exporter</button><label class="file-button secondary">Importer<input type="file" accept="application/json,.json" @change="importLab" /></label></section>
      <section class="panel"><div class="section-title"><div><h2>Éditeur de topologie</h2><span>réseau {{ topology.network.name }}</span></div><div class="tools"><select v-model="selectedServiceId" class="service-select" aria-label="Profil catalogue"><option v-for="profile in deployableServices" :key="profile.id" :value="profile.id">{{ profile.label }}</option></select><button class="secondary" @click="addCatalogService">Ajouter le profil</button><button class="secondary" @click="addNode">Nœud personnalisé</button><button class="secondary" @click="linkMode = !linkMode; linkStart = null">{{ linkMode ? 'Annuler' : 'Relier' }}</button><button class="danger" @click="removeSelected">Supprimer</button></div></div><p class="hint">Les profils disponibles sont limités à Nginx et Apache. Un port hôte est facultatif et lié uniquement à 127.0.0.1. {{ linkMode ? 'Mode liaison actif : sélectionnez deux nœuds.' : 'Sélectionnez un nœud pour le terminal.' }}</p><svg class="canvas" viewBox="0 0 760 330"><line v-for="(link, index) in topology.links" :key="`link-${index}`" class="topology-link" :x1="(topology.nodes.find(node => node.name === link.from)?.position.x ?? 0) + 80" :y1="(topology.nodes.find(node => node.name === link.from)?.position.y ?? 0) + 30" :x2="(topology.nodes.find(node => node.name === link.to)?.position.x ?? 0) + 80" :y2="(topology.nodes.find(node => node.name === link.to)?.position.y ?? 0) + 30" /><g v-for="node in topology.nodes" :key="node.name" class="canvas-node" :class="{ selected: selected === node.name }" :transform="`translate(${node.position.x},${node.position.y})`" @pointerdown="dragNode($event, node)"><rect width="160" height="60" rx="10" /><text class="canvas-node-title" x="14" y="24">{{ node.name }}</text><text class="canvas-node-image" x="14" y="44">{{ node.image }}</text></g></svg></section>
      <section class="panel catalog-panel"><div class="section-title"><div><h2>Catalogue de services</h2><span>{{ deployableServices.length }} profils déployables localement · {{ serviceCatalog.length }} documentés</span></div></div><div class="catalog-grid"><article v-for="profile in serviceCatalog" :key="profile.id" class="catalog-card"><div class="catalog-card-head"><h3>{{ profile.label }}</h3><span class="catalog-status" :class="profile.status">{{ profile.status === 'ready' ? 'disponible' : profile.status === 'planned' ? 'prévu' : 'étude' }}</span></div><code>{{ profile.image ?? 'image VM à définir' }}</code><p><strong>Ports :</strong> {{ portsText(profile) }}</p><p><strong>Ressources :</strong> {{ resourceText(profile) }}</p><p v-if="profile.environment.length"><strong>Variables :</strong> {{ profile.environment.map(item => `${item.name}${item.secret ? ' (secret)' : ''}`).join(', ') }}</p><ul><li v-for="constraint in profile.constraints" :key="constraint">{{ constraint }}</li></ul></article></div></section>
      <section class="panel education-panel">
        <div class="section-title"><div><h2>Partage pédagogique</h2><span>Comptes, groupes, affectations et remises</span></div><button class="secondary" @click="loadEducation">Actualiser</button></div>
        <p class="hint">Les étudiants reçoivent un instantané JSON indépendant. Le déploiement reste réservé à l’enseignant tant que l’isolation d’exécution par étudiant n’existe pas.</p>
        <div class="education-grid">
          <form class="stack-form panel nested" @submit.prevent="createStudent"><h3>Créer un compte étudiant</h3><label>Nom affiché<input v-model="newStudent.display_name" required maxlength="100" /></label><label>E-mail<input v-model="newStudent.email" type="email" required /></label><label>Mot de passe initial (12+)<input v-model="newStudent.password" type="password" minlength="12" required /></label><button>Créer le compte</button></form>
          <form class="stack-form panel nested" @submit.prevent="createGroup"><h3>Créer un groupe</h3><label>Nom du groupe<input v-model="newGroupName" required maxlength="100" /></label><button>Créer le groupe</button><label>Groupe actif<select v-model="selectedGroupId" @change="loadSubmissions"><option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }} ({{ group.members }})</option></select></label><label>Ajouter l’étudiant (e-mail)<input v-model="memberEmail" type="email" required /></label><button class="secondary" type="button" :disabled="!selectedGroupId" @click="addMember">Ajouter au groupe</button></form>
          <div class="panel nested"><h3>Partager le laboratoire courant</h3><label>Titre de l’affectation<input v-model="assignmentTitle" :placeholder="topology.lab" maxlength="120" /></label><button :disabled="!selectedGroupId" @click="publishAssignment">Affecter au groupe</button><p class="hint">La topologie actuelle est copiée comme instantané ; les changements ultérieurs ne modifient pas l’affectation.</p></div>
          <div class="panel nested"><h3>Élèves enregistrés</h3><ul class="compact-list"><li v-for="student in users.filter(item => item.role === 'student')" :key="student.id">{{ student.display_name }} <small>{{ student.email }}</small></li><li v-if="!users.some(item => item.role === 'student')" class="muted">Aucun étudiant créé.</li></ul></div>
        </div>
        <div class="submissions"><h3>Suivi des remises {{ groups.find(group => group.id === selectedGroupId)?.name ? `— ${groups.find(group => group.id === selectedGroupId)?.name}` : '' }}</h3><table><thead><tr><th>TP</th><th>Étudiant</th><th>Statut</th><th>Remis</th></tr></thead><tbody><tr v-for="(item, index) in submissions" :key="`${item.assignment_id}-${item.email}-${index}`"><td>{{ item.title }}</td><td>{{ item.display_name }} <small>{{ item.email }}</small></td><td>{{ item.status }}</td><td>{{ item.submitted_at ? new Date(item.submitted_at * 1000).toLocaleString() : '—' }}</td></tr><tr v-if="!submissions.length"><td colspan="4" class="muted">Aucune affectation ou remise pour ce groupe.</td></tr></tbody></table></div>
      </section>
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
