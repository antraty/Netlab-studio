export interface Position { x: number; y: number }
export interface Node { name: string; image: string; command: string[]; position: Position }
export interface Link { from: string; to: string }
export interface Topology { version: number; lab: string; network: { name: string; driver: string; subnet?: string }; nodes: Node[]; links: Link[]; connectivity_check: { from: string; to: string; command: string[] } }
export interface StatusNode { name: string; state: string }
