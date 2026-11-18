<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import type { Assignment, Group, User } from './api'
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
let timer: number | undefined

const selectedNode = computed(() => topology.value?.nodes.find(node => node.name === selected.value))
const stateText = computed(() => dirty.value ? 'modifications non sauvegardées' : 'contrôle actif')
const activeAssignment = computed(() => assignments.value.find(item => item.id === activeAssignmentId.value))
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
  timer = undefined
  terminalSocket.value?.close(); user.value = null; topology.value = null; assignments.value = []; pageError.value = ''
}

async function loadEducation() {
  const [groupResponse, userResponse] = await Promise.all([api.groups(), api.users()])
  groups.value = groupResponse.groups; users.value = userResponse.users
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
async function action(name: 'up' | 'down' | 'verify') { try { const result = await api.action(name); terminalOutput.value = result.ok ? `${name}: terminé` : `${name}: échec (code ${result.exit_code})`; await refresh() } catch (error) { showError(error) } }
async function save() { if (!topology.value) return; try { await api.save(topology.value); dirty.value = false; await refresh() } catch (error) { showError(error) } }
async function restore() { if (!topology.value || !versions.value.length) return; const raw = window.prompt(`Version à restaurer (${versions.value.map(version => version.version).join(', ')})`, String(versions.value[0].version)); const version = Number(raw); if (!Number.isInteger(version)) return; try { const response = await api.restore(topology.value.lab, version); topology.value = response.topology; dirty.value = false; await refresh(false) } catch (error) { showError(error) } }
async function cloneLab() { if (!topology.value) return; const newLab = window.prompt('Nom du laboratoire cloné :', `${topology.value.lab}-copy`); if (!newLab) return; try { await api.clone(topology.value.lab, newLab); terminalOutput.value = `laboratoire cloné : ${newLab}`; await refresh(false) } catch (error) { showError(error) } }
async function exportLab() { if (!topology.value) return; try { const payload = await api.export(topology.value.lab); const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${topology.value.lab}.netlab.json`; link.click(); URL.revokeObjectURL(link.href) } catch (error) { showError(error) } }
async function importLab(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file) return; try { const payload = JSON.parse(await file.text()); const response = await api.import(payload.topology ?? payload); topology.value = response.topology; selected.value = topology.value.nodes[0]?.name ?? null; dirty.value = false; terminalOutput.value = `laboratoire importé : ${topology.value.lab}`; await refresh(false) } catch (error) { showError(error) } finally { input.value = '' } }
async function runTerminal() { const socket = terminalSocket.value; const command = terminalCommand.value.trim(); if (!socket || socket.readyState !== WebSocket.OPEN || !command) { terminalOutput.value = 'Sélectionnez un nœud avec Docker actif.'; return }; socket.send(command); terminalCommand.value = '' }

onMounted(async () => { await initialize() })
onUnmounted(() => { if (timer) window.clearInterval(timer); terminalSocket.value?.close() })
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
    <main v-if="topology">
      <p v-if="pageError" class="notice">{{ pageError }}<button class="notice-close" @click="pageError = ''">×</button></p>
      <section class="toolbar"><button @click="action('up')">Déployer</button><button class="secondary" @click="action('verify')">Tester la connectivité</button><button class="danger" @click="action('down')">Arrêter</button><button class="secondary" @click="save">Nouvelle version</button><button class="secondary" @click="restore">Restaurer</button><button class="secondary" @click="cloneLab">Cloner</button><button class="secondary" @click="exportLab">Exporter</button><label class="file-button secondary">Importer<input type="file" accept="application/json,.json" @change="importLab" /></label></section>
      <section class="panel"><div class="section-title"><div><h2>Éditeur de topologie</h2><span>réseau {{ topology.network.name }}</span></div><div class="tools"><button class="secondary" @click="addNode">+ Nœud</button><button class="secondary" @click="linkMode = !linkMode; linkStart = null">{{ linkMode ? 'Annuler' : 'Relier' }}</button><button class="danger" @click="removeSelected">Supprimer</button></div></div><p class="hint">Déplacez les nœuds par glisser-déposer. {{ linkMode ? 'Mode liaison actif : sélectionnez deux nœuds.' : 'Sélectionnez un nœud pour le terminal.' }}</p><svg class="canvas" viewBox="0 0 760 330"><line v-for="(link, index) in topology.links" :key="`link-${index}`" class="topology-link" :x1="(topology.nodes.find(node => node.name === link.from)?.position.x ?? 0) + 80" :y1="(topology.nodes.find(node => node.name === link.from)?.position.y ?? 0) + 30" :x2="(topology.nodes.find(node => node.name === link.to)?.position.x ?? 0) + 80" :y2="(topology.nodes.find(node => node.name === link.to)?.position.y ?? 0) + 30" /><g v-for="node in topology.nodes" :key="node.name" class="canvas-node" :class="{ selected: selected === node.name }" :transform="`translate(${node.position.x},${node.position.y})`" @pointerdown="dragNode($event, node)"><rect width="160" height="60" rx="10" /><text class="canvas-node-title" x="14" y="24">{{ node.name }}</text><text class="canvas-node-image" x="14" y="44">{{ node.image }}</text></g></svg></section>
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
    </main>
    <p v-else class="loading">Impossible de charger le laboratoire. Vérifiez l’API et la configuration du compte.</p>
    <footer>Netlab Studio — accès réservé au compte enseignant ; les étudiants ne reçoivent pas d’accès au socket Docker.</footer>
  </template>
</template>
