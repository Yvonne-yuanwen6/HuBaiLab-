import { Button, Card, Checkbox, Input, Popconfirm, Select, Typography, message } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, pollTask } from "../api/client";
import { CaseTimingPanel } from "../components/CaseSettingsPanel";
import { DataSourceBanner } from "../components/DataSourceBanner";
import { JobStatusBadge } from "../components/JobStatusBadge";
import { JobProgressBar } from "../components/ProgressBar";

const SYNC_REMOTE_KEY = "hubai_dashboard_sync_remote";

function readSyncRemotePref(): boolean {
  try {
    const v = localStorage.getItem(SYNC_REMOTE_KEY);
    if (v === null) return true;
    return v === "1";
  } catch {
    return true;
  }
}

export function MonitorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [slug, setSlug] = useState(searchParams.get("slug") ?? "");
  const [syncRemote, setSyncRemote] = useState(readSyncRemotePref);
  const [pollSec, setPollSec] = useState(30);

  const { data: caseList } = useQuery({
    queryKey: ["cases", syncRemote],
    queryFn: () => api.listCases(syncRemote),
  });
  const cases = caseList?.cases ?? [];

  const selectedCase = cases.find((c) => c.slug === slug);

  const {
    data: status,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["monitor-status", slug, syncRemote],
    queryFn: () => api.getStatus(slug, syncRemote),
    enabled: !!slug,
    refetchInterval: pollSec * 1000,
  });

  const { data: logs } = useQuery({
    queryKey: ["monitor-logs", slug],
    queryFn: () => api.getLogs(slug),
    enabled: !!slug,
    refetchInterval: pollSec * 1000,
  });

  useEffect(() => {
    if (slug) setSearchParams({ slug });
  }, [slug, setSearchParams]);

  return (
    <div>
      <Typography.Title level={3}>作业监控</Typography.Title>
      <DataSourceBanner
        label={syncRemote ? "本机 + 已同步远程" : "本机 output/（未同步）"}
        hint={
          syncRemote
            ? "已勾选「远程同步」：每次刷新前会从服务器 scp .sta/.lck/_meta.json 到本机再解析。"
            : "未勾选时仅读本机 output/jobs/。服务器上正在运行的作业状态可能不准确，请勾选「远程同步」。"
        }
      />
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
          <Select
            showSearch
            placeholder="选择 slug"
            style={{ minWidth: 420 }}
            value={slug || undefined}
            onChange={setSlug}
            options={cases.map((c) => ({ label: c.slug, value: c.slug }))}
          />
          <Input
            placeholder="或输入 slug"
            style={{ width: 320 }}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <Checkbox
            checked={syncRemote}
            onChange={(e) => {
              const checked = e.target.checked;
              setSyncRemote(checked);
              try {
                localStorage.setItem(SYNC_REMOTE_KEY, checked ? "1" : "0");
              } catch {
                /* ignore */
              }
            }}
          >
            远程同步 (.sta/.lck)
          </Checkbox>
          <Select
            value={pollSec}
            onChange={setPollSec}
            style={{ width: 120 }}
            options={[
              { label: "5s", value: 5 },
              { label: "15s", value: 15 },
              { label: "30s", value: 30 },
              { label: "60s", value: 60 },
            ]}
          />
          <Button onClick={() => void refetch()} loading={isFetching}>
            立即刷新
          </Button>
          <Popconfirm
            title="远程终止此算例？"
            onConfirm={() => {
              void api.stop(slug, "remote").then((task) => {
                message.info("终止命令已发送");
                pollTask(task.task_id, (t) => {
                  if (t.status === "done") {
                    message.success("终止完成");
                    void refetch();
                  } else if (t.status === "failed") {
                    message.error(t.error || "终止失败");
                  }
                });
              });
            }}
            disabled={!slug || status?.state !== "RUNNING"}
          >
            <Button danger disabled={!slug || status?.state !== "RUNNING"}>
              远程终止
            </Button>
          </Popconfirm>
        </div>
      </Card>

      {selectedCase && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <CaseTimingPanel timing={selectedCase} />
        </Card>
      )}

      {slug && status && (
        <>
          <Card title="状态" style={{ marginBottom: 16 }}>
            <JobStatusBadge status={status.state} />
            {status.failure_reason && (
              <Typography.Text type="danger" style={{ marginLeft: 12 }}>
                {status.failure_reason}
              </Typography.Text>
            )}
            <div style={{ marginTop: 16 }}>
              <JobProgressBar
                pct={status.progress_pct}
                simTimeS={status.sim_time_s}
                stepTimeS={status.step_time_s}
                frame={status.frame}
                framesTotal={status.frames_total}
                eta={status.eta}
              />
            </div>
            {status.ke != null && status.ie != null && (
              <Typography.Text type="secondary" style={{ display: "block", marginTop: 8 }}>
                KE={status.ke.toExponential(2)} · IE={status.ie.toExponential(2)}
              </Typography.Text>
            )}
          </Card>
          <Card title=".sta 日志尾部">
            <pre
              style={{
                background: "#1e1e1e",
                color: "#d4d4d4",
                padding: 16,
                overflow: "auto",
                maxHeight: 400,
                fontSize: 12,
              }}
            >
              {logs?.sta_tail || "暂无日志"}
            </pre>
          </Card>
        </>
      )}
    </div>
  );
}
