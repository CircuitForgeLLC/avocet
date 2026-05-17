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

// ── Full profile types (for profile editor) ────────────────────────────────────

export interface ServiceManaged {
  type: string
  exec_path?: string
  args_template?: string
  port?: number
  host_port?: number
  base_port?: number
  health_path?: string
  cwd?: string
  adopt?: boolean
  [key: string]: unknown
}

export interface CatalogEntryFull {
  path: string
  vram_mb: number
  description?: string
  multi_gpu?: boolean
  env?: Record<string, string>
}

export interface ServiceDefinition {
  max_mb: number
  priority: number
  min_compute_cap?: number
  preferred_compute_cap?: number
  shared?: boolean
  max_concurrent?: number
  idle_stop_after_s?: number
  always_on?: boolean
  model_base_path?: string
  managed?: ServiceManaged
  catalog?: Record<string, CatalogEntryFull>
}

export interface NodeHardwareGpu {
  id: number
  vram_mb: number
  compute_cap?: number
  card?: string
  role?: string
  services?: string[]
}

export interface NodeHardwareEntry {
  local_model_root?: string
  agent_url?: string
  gpus: NodeHardwareGpu[]
}

export interface FullProfile {
  schema_version?: number
  name?: string
  vram_total_mb?: number
  eviction_timeout_s?: number
  services: Record<string, ServiceDefinition>
  nodes: Record<string, NodeHardwareEntry>
  model_size_hints?: Record<string, string>
}
