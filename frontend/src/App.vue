<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import type { Node, StatusNode, Topology } from './types'

const topology = ref<Topology | null>(null)
const statuses = ref<StatusNode[]>([])
const logs = ref<string[]>([])
const selected = ref<string | null>(null)
const linkMode = ref(false)
const linkStart = ref<string | null>(null)
const dirty = ref(false)
const terminalOutput = ref('Sélectionnez un nœud pour ouvrir son terminal.')
const terminalCommand = ref('hostname')
let timer: number | undefined

const selectedNode = computed(() => topology.value?.nodes.find(node => node.name === selected.value))
const stateText = computed(() => dirty.value ? 'modifications non sauvegardées' : 'contrôle actif')

function nodeStatus(name: string) { return statuses.value.find(node => node.name === name)?.state ?? 'inconnu' }
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
  } catch (error) { terminalOutput.value = error instanceof Error ? error.message : 'Erreur inconnue' }
}
async function action(name: 'up' | 'down' | 'verify') { const result = await api.action(name); terminalOutput.value = result.ok ? `${name}: terminé` : `${name}: échec (code ${result.exit_code})`; await refresh() }
async function save() { if (!topology.value) return; await api.save(topology.value); dirty.value = false; await refresh() }
async function runTerminal() { if (!selected.value) return; const result = await api.terminal(selected.value, terminalCommand.value.trim().split(/\s+/)); terminalOutput.value = result.output || `code de sortie : ${result.exit_code}`; await refresh(false) }

onMounted(async () => { await refresh(); timer = window.setInterval(() => refresh(), 5000) })
onUnmounted(() => { if (timer) window.clearInterval(timer) })
</script>

<template>
  <header><div><p class="eyebrow">NETLAB STUDIO / FASTAPI + VUE</p><h1>{{ topology?.lab ?? 'Chargement…' }}</h1></div><span class="badge online">{{ stateText }}</span></header>
  <main v-if="topology">
    <section class="toolbar"><button @click="action('up')">Déployer</button><button class="secondary" @click="action('verify')">Tester la connectivité</button><button class="danger" @click="action('down')">Arrêter</button><button class="secondary" @click="save">Sauvegarder</button></section>
    <section class="panel"><div class="section-title"><div><h2>Éditeur de topologie</h2><span>réseau {{ topology.network.name }}</span></div><div class="tools"><button class="secondary" @click="addNode">+ Nœud</button><button class="secondary" @click="linkMode = !linkMode; linkStart = null">{{ linkMode ? 'Annuler' : 'Relier' }}</button><button class="danger" @click="removeSelected">Supprimer</button></div></div><p class="hint">Déplacez les nœuds par glisser-déposer. {{ linkMode ? 'Mode liaison actif : sélectionnez deux nœuds.' : 'Sélectionnez un nœud pour le terminal.' }}</p><svg class="canvas" viewBox="0 0 760 330"><line v-for="(link, index) in topology.links" :key="`link-${index}`" class="topology-link" :x1="(topology.nodes.find(node => node.name === link.from)?.position.x ?? 0) + 80" :y1="(topology.nodes.find(node => node.name === link.from)?.position.y ?? 0) + 30" :x2="(topology.nodes.find(node => node.name === link.to)?.position.x ?? 0) + 80" :y2="(topology.nodes.find(node => node.name === link.to)?.position.y ?? 0) + 30" /><g v-for="node in topology.nodes" :key="node.name" class="canvas-node" :class="{ selected: selected === node.name }" :transform="`translate(${node.position.x},${node.position.y})`" @pointerdown="dragNode($event, node)"><rect width="160" height="60" rx="10" /><text class="canvas-node-title" x="14" y="24">{{ node.name }}</text><text class="canvas-node-image" x="14" y="44">{{ node.image }}</text></g></svg></section>
    <section class="lower"><div class="panel"><div class="section-title"><h2>Terminal web</h2><span>{{ selectedNode?.name ?? 'aucun nœud' }}</span></div><div class="terminal"><div>{{ terminalOutput }}</div><form @submit.prevent="runTerminal"><span>$</span><input v-model="terminalCommand" aria-label="Commande terminal" /><button>Exécuter</button></form></div></div><div class="panel"><div class="section-title"><h2>Journal</h2></div><pre>{{ logs.length ? logs.join('\n') : 'Aucun événement.' }}</pre></div></section>
  </main>
  <p v-else class="loading">Impossible de charger le laboratoire. Vérifiez que FastAPI est démarré.</p>
  <footer>Netlab Studio — le navigateur pilote le plan de contrôle FastAPI, jamais Docker directement.</footer>
</template>
