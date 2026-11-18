export interface Position { x: number; y: number }
export interface Interface { name: string; network: string; ipv4?: string; gateway?: string }
export interface Route { destination: string; via: string }
export interface Node { name: string; image: string; command: string[]; position: Position; service_id?: string; published_port?: number; type?: string; router?: boolean; interfaces?: Interface[]; routes?: Route[] }
export interface Link { from: string; to: string }
export interface Network { name: string; driver: string; subnet: string }
export interface Topology { version: number; lab: string; laboratory_id?: string; network: Network; networks?: Network[]; nodes: Node[]; links: Link[]; connectivity_check: { from: string; to: string; command: string[] } }
export interface StatusNode { name: string; state: string }
export interface VersionInfo { version: number; lab: string; created_at: string; reason: string }
