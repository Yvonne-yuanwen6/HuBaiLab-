export interface CaseSummary {
  slug: string;
  variant: string | null;
  Q: number | null;
  status: string;
  has_inp: boolean;
  has_odb: boolean;
  has_curve: boolean;
  export_dir: string;
  modified_at: number | null;
  exported_at: number | null;
  exported_at_label: string | null;
  completed_at: number | null;
  completed_at_label: string | null;
  wallclock_seconds: number | null;
  data_source?: string;
  material?: string | null;
  element_type?: string | null;
  cae_seed_mm?: string | null;
  target_strain?: string | null;
  load_rate_mm_min?: string | null;
  explicit_dt?: string | null;
  step_time_s?: string | null;
  cells?: string | null;
  profile?: string | null;
  mesh_quality?: string | null;
  tags?: Record<string, string>;
  display_tags?: string[];
  location?: string;
  location_label?: string;
  has_local?: boolean;
  has_remote?: boolean;
}

export interface FilterFacetValue {
  value: string;
  count: number;
}

export interface FilterFacet {
  key: string;
  label: string;
  values: FilterFacetValue[];
}

export type CaseTagFilters = Record<string, string[]>;

export interface CaseListResponse {
  data_source: string;
  data_source_label: string;
  hint: string;
  cases: CaseSummary[];
  filter_facets?: FilterFacet[];
}

export interface SettingItem {
  key: string;
  label: string;
  value: string;
}

export interface SettingGroup {
  title: string;
  items: SettingItem[];
}

export interface CaseTiming {
  exported_at: number | null;
  exported_at_label: string | null;
  completed_at: number | null;
  completed_at_label: string | null;
  wallclock_seconds: number | null;
  odb_size_bytes: number | null;
}

export interface CaseDetail {
  slug: string;
  manifest: Record<string, unknown> | null;
  meta: Record<string, unknown> | null;
  status: string;
  paths: Record<string, boolean>;
  settings_groups: SettingGroup[];
  timing: CaseTiming | null;
}

export interface JobStatus {
  slug: string;
  state: string;
  failure_reason: string | null;
  lck_exists: boolean;
  frame: number | null;
  frames_total: number | null;
  sim_time_s: number;
  total_time_s: number;
  ke: number | null;
  ie: number | null;
  progress_pct: number;
  step_time_s: number | null;
  target_strain: number | null;
  eta: string | null;
}

export interface CurvePoint {
  engineering_strain: number;
  engineering_stress_MPa: number;
}

export interface CurveResponse {
  slug: string;
  points: CurvePoint[];
  yield_data: Record<string, unknown> | null;
}

export interface TaskResponse {
  task_id: string;
  status: string;
  command: string[];
  slug: string | null;
  exit_code: number | null;
  stdout_tail: string;
  stderr_tail: string;
  created_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface DashboardSummary {
  active_case: Record<string, unknown> | null;
  running_count: number;
  completed_count: number;
  failed_count: number;
  trash_count: number;
  recent_cases: CaseSummary[];
  data_source?: string;
  data_source_label?: string;
  hint?: string;
}

export interface TrashItem {
  trash_id: string;
  slug: string;
  deleted_at?: string | null;
  deleted_at_label?: string | null;
  deleted_at_ts?: number | null;
  had_export?: boolean;
  had_jobs?: boolean;
  had_post?: boolean;
  cleared_active_case?: boolean | null;
}

export interface ExportSettings {
  Q: number;
  Af: number;
  cells: number;
  cad_path: string;
  cae_seed_mm: number;
  cae_mesh_quality: string;
  cae_rods_per_diameter: number;
  cae_virtual_topology: boolean;
  cae_element_type: string;
  slug_mode: string;
  short_slug: string;
  profile: string;
  strain: number;
  load_rate_mm_min: number;
  material_model: string;
  contact_store_offsets: boolean;
  contact_settle: boolean;
  case_suffix: string;
  mesh_on_server: boolean;
  mesh_locally: boolean;
  remote_host: string;
  remote_root: string;
  submit_target: string;
  submit_cpus: number;
  submit_memory_mb: number;
  submit_recover: boolean;
  submit_restart_from: string;
  slug_preview?: string;
  variant_name?: string;
}

export interface VerifiedCad {
  name: string;
  path: string;
  size_bytes: number;
}
