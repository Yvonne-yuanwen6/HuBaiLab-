import type {
  CadGenerateRequest,
  CaseDetail,
  CaseListResponse,
  CaseSummary,
  CurveResponse,
  DashboardSummary,
  ExportSettings,
  JobStatus,
  QueueState,
  TaskResponse,
  TrashItem,
  VerifiedCad,
} from "../types";

const CASE_LIST_HINT_LOCAL =
  "列表与状态读取本机 output/ 目录。作业若在 Linux 服务器运行，请勾选「同步服务器 output」。";

function normalizeCaseListResponse(data: CaseListResponse | CaseSummary[]): CaseListResponse {
  if (Array.isArray(data)) {
    return {
      data_source: "local",
      data_source_label: "本机 output/",
      hint: CASE_LIST_HINT_LOCAL,
      cases: data,
      filter_facets: [],
    };
  }
  return data;
}

async function fetchCaseList(discoverRemote: boolean): Promise<CaseListResponse> {
  if (discoverRemote) {
    await apiSyncOutput();
  }
  const raw = await request<CaseListResponse | CaseSummary[]>(
    `/api/abaqus/cases?discover_remote=${discoverRemote ? "true" : "false"}`,
  );
  return normalizeCaseListResponse(raw);
}

async function apiSyncOutput() {
  return request<{
    slug_count: number;
    synced_slugs: number;
    remote_job_count: number;
    remote_jobs: string[];
  }>("/api/abaqus/sync-output", { method: "POST", body: "{}" });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      const parsed = JSON.parse(text) as { detail?: string | { msg?: string }[] };
      if (typeof parsed.detail === "string") {
        throw new Error(parsed.detail);
      }
      if (Array.isArray(parsed.detail)) {
        throw new Error(parsed.detail.map((d) => d.msg ?? JSON.stringify(d)).join("; "));
      }
    } catch (e) {
      if (e instanceof Error && e.message !== text) throw e;
    }
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  dashboard: (discoverRemote = false) =>
    request<DashboardSummary>(
      `/api/abaqus/dashboard?discover_remote=${discoverRemote ? "true" : "false"}`,
    ),
  syncOutput: () => apiSyncOutput(),
  listCases: (discoverRemote = false) => fetchCaseList(discoverRemote),
  getCase: (slug: string) => request<CaseDetail>(`/api/abaqus/cases/${encodeURIComponent(slug)}`),
  getStatus: (slug: string, syncRemote = false) =>
    request<JobStatus>(
      `/api/abaqus/jobs/${encodeURIComponent(slug)}/status?sync_remote=${syncRemote}`,
    ),
  getLogs: (slug: string) =>
    request<{ sta_tail: string; submit_log_tail: string }>(
      `/api/abaqus/jobs/${encodeURIComponent(slug)}/logs`,
    ),
  getCurve: (slug: string) =>
    request<CurveResponse>(`/api/abaqus/cases/${encodeURIComponent(slug)}/curve`),
  listCad: () => request<VerifiedCad[]>("/api/abaqus/cad/verified"),
  generateCad: (body: CadGenerateRequest) =>
    request<TaskResponse>("/api/abaqus/cad/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPresets: () => request<Record<string, ExportSettings>>("/api/abaqus/presets"),
  previewSettings: (settings: Partial<ExportSettings>) =>
    request<ExportSettings>("/api/abaqus/settings/preview", {
      method: "POST",
      body: JSON.stringify(settings),
    }),
  export: (settings: Partial<ExportSettings>) =>
    request<TaskResponse>("/api/abaqus/export", {
      method: "POST",
      body: JSON.stringify({ settings }),
    }),
  mesh: (settings: Partial<ExportSettings>) =>
    request<TaskResponse>("/api/abaqus/mesh", {
      method: "POST",
      body: JSON.stringify({ settings }),
    }),
  getQueue: () => request<QueueState>("/api/abaqus/queue"),
  addToQueue: (body: {
    slugs: string[];
    target?: string;
    cpus?: number;
    memory_mb?: number;
  }) =>
    request<QueueState>("/api/abaqus/queue", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reorderQueue: (ids: string[]) =>
    request<QueueState>("/api/abaqus/queue/reorder", {
      method: "PATCH",
      body: JSON.stringify({ ids }),
    }),
  moveQueueItem: (id: string, direction: "up" | "down" | "top" | "bottom") =>
    request<QueueState>(`/api/abaqus/queue/${encodeURIComponent(id)}/move`, {
      method: "POST",
      body: JSON.stringify({ direction }),
    }),
  removeQueueItem: (id: string) =>
    request<QueueState>(`/api/abaqus/queue/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  startQueue: () =>
    request<QueueState>("/api/abaqus/queue/start", { method: "POST", body: "{}" }),
  pauseQueue: () =>
    request<QueueState>("/api/abaqus/queue/pause", { method: "POST", body: "{}" }),
  clearFinishedQueue: () =>
    request<QueueState>("/api/abaqus/queue/clear-finished", {
      method: "POST",
      body: "{}",
    }),
  submit: (
    slug: string,
    body: {
      target?: string;
      cpus?: number;
      memory_mb?: number;
      recover?: boolean;
      restart_from?: string;
      background?: boolean;
    },
  ) =>
    request<TaskResponse>(`/api/abaqus/jobs/${encodeURIComponent(slug)}/submit`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  syncRemote: (slug: string) =>
    request<Record<string, boolean>>(
      `/api/abaqus/jobs/${encodeURIComponent(slug)}/sync-remote`,
      { method: "POST", body: "{}" },
    ),
  extract: (slug: string) =>
    request<TaskResponse>(`/api/abaqus/jobs/${encodeURIComponent(slug)}/extract`, {
      method: "POST",
    }),
  plot: (slug: string) =>
    request<TaskResponse>(`/api/abaqus/jobs/${encodeURIComponent(slug)}/plot`, {
      method: "POST",
    }),
  stop: (slug: string, target: "local" | "remote" = "remote") =>
    request<TaskResponse>(`/api/abaqus/jobs/${encodeURIComponent(slug)}/stop`, {
      method: "POST",
      body: JSON.stringify({ target }),
    }),
  deleteCase: (slug: string, scope: "local" | "remote" | "both" = "local") =>
    request<TaskResponse>(
      `/api/abaqus/cases/${encodeURIComponent(slug)}?scope=${scope}`,
      { method: "DELETE" },
    ),
  listTrash: () => request<TrashItem[]>("/api/abaqus/trash"),
  restoreTrash: (trashId: string) =>
    request<TaskResponse>(`/api/abaqus/trash/${encodeURIComponent(trashId)}/restore`, {
      method: "POST",
    }),
  purgeTrash: (trashId: string) =>
    request<TaskResponse>(`/api/abaqus/trash/${encodeURIComponent(trashId)}`, {
      method: "DELETE",
    }),
  getTask: (taskId: string) => request<TaskResponse>(`/api/tasks/${taskId}`),
};

export function pollTask(
  taskId: string,
  onUpdate: (task: TaskResponse) => void,
  intervalMs = 3000,
): () => void {
  let active = true;
  const tick = async () => {
    if (!active) return;
    try {
      const task = await api.getTask(taskId);
      onUpdate(task);
      if (task.status === "running" || task.status === "pending") {
        setTimeout(tick, intervalMs);
      }
    } catch {
      setTimeout(tick, intervalMs);
    }
  };
  tick();
  return () => {
    active = false;
  };
}
