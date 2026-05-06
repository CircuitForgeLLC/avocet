export interface GpuEntry {
  gpu_id: number
  card: string
  vram_total_mb: number
  vram_used_mb: number
  vram_free_mb: number
  temp_c: number | null
  utilization_pct: number | null
  compute_cap: number | null
  services_assigned: string[]
  services_running: string[]
}

export interface ServiceInfo {
  min_compute_cap: number
  max_mb: number
  catalog_size: number
}

export interface NodeSummary {
  node_id: string
  online: boolean
  agent_url: string
  gpus: GpuEntry[]
  profile_loaded: boolean
  services_catalog: Record<string, ServiceInfo>
}
