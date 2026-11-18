export interface Position { x: number; y: number }
export interface Node { name: string; image: string; command: string[]; position: Position; service_id?: string; published_port?: number }
export interface Link { from: string; to: string }
export interface Topology { version: number; lab: string; network: { name: string; driver: string; subnet?: string }; nodes: Node[]; links: Link[]; connectivity_check: { from: string; to: string; command: string[] } }
export interface StatusNode { name: string; state: string }
export interface VersionInfo { version: number; lab: string; created_at: string; reason: string }
