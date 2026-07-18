import { Button, Card, Col, Modal, Popconfirm, Row, Select, Tabs, Typography, message } from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, pollTask } from "../api/client";
import { CaseSettingsPanel, CaseTimingPanel } from "../components/CaseSettingsPanel";
import { DataSourceBanner } from "../components/DataSourceBanner";
import { JobStatusBadge } from "../components/JobStatusBadge";
import { JobProgressBar } from "../components/ProgressBar";
import { StressStrainChart } from "../components/StressStrainChart";

export function CaseDetailPage() {
  const { slug = "" } = useParams();
  const decoded = decodeURIComponent(slug);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [trashScope, setTrashScope] = useState<"local" | "both">("local");

  const { data: detail, refetch: refetchDetail } = useQuery({
    queryKey: ["case", decoded],
    queryFn: () => api.getCase(decoded),
    enabled: !!decoded,
  });

  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["status", decoded],
    queryFn: () => api.getStatus(decoded),
    enabled: !!decoded,
    refetchInterval: 30000,
  });

  const { data: curve, refetch: refetchCurve } = useQuery({
    queryKey: ["curve", decoded],
    queryFn: () => api.getCurve(decoded),
    enabled: !!decoded && !!detail?.paths.curve_csv,
    retry: false,
  });

  const { data: logs } = useQuery({
    queryKey: ["logs", decoded],
    queryFn: () => api.getLogs(decoded),
    enabled: !!decoded,
    refetchInterval: 30000,
  });

  const runAction = async (label: string, fn: () => Promise<{ task_id: string }>) => {
    try {
      const task = await fn();
      message.info(`${label} 已启动`);
      pollTask(task.task_id, (t) => {
        if (t.status === "done") {
          message.success(`${label} 完成`);
          void refetchDetail();
          void refetchStatus();
          void refetchCurve();
          void queryClient.invalidateQueries({ queryKey: ["cases"] });
        } else if (t.status === "failed") {
          message.error(t.error || `${label} 失败`);
        }
      });
    } catch (e) {
      message.error(String(e));
    }
  };

  const handleStop = () => {
    void runAction("远程终止", () => api.stop(decoded, "remote"));
  };

  const handleDelete = async () => {
    try {
      const task = await api.deleteCase(decoded, trashScope);
      if (task.status === "done") {
        const local = task.stdout_tail || "";
        if (local.includes("没有找到可移入回收站")) {
          message.warning("本机未找到可移动的目录；若数据仅在服务器，请选择「本机 + 远程」");
        } else {
          message.success("本机已移入回收站");
        }
        if (trashScope === "both") {
          message.info("远程移入回收站已在后台执行（SSH 失败不影响本机结果）");
        }
        void queryClient.invalidateQueries({ queryKey: ["trash"] });
        void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
        void queryClient.invalidateQueries({ queryKey: ["cases"] });
        navigate("/cases");
        return;
      }
      message.info("移入回收站…");
      pollTask(task.task_id, (t) => {
        if (t.status === "done") {
          message.success("已移入回收站");
          void queryClient.invalidateQueries({ queryKey: ["trash"] });
          void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
          void queryClient.invalidateQueries({ queryKey: ["cases"] });
          navigate("/cases");
        } else if (t.status === "failed") {
          message.error(t.error || "移入回收站失败");
        }
      });
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const showRawJson = () => {
    Modal.info({
      title: "原始 manifest / meta",
      width: 800,
      content: (
        <pre style={{ maxHeight: 480, overflow: "auto", fontSize: 12 }}>
          {JSON.stringify({ manifest: detail?.manifest, meta: detail?.meta }, null, 2)}
        </pre>
      ),
    });
  };

  if (!decoded) return null;

  const isRunning = (detail?.status ?? status?.state) === "RUNNING";

  return (
    <div>
      <Typography.Title level={3} style={{ wordBreak: "break-all" }}>
        <code>{decoded}</code>
      </Typography.Title>
      <div style={{ marginBottom: 16 }}>
        <JobStatusBadge status={detail?.status ?? status?.state ?? "WAITING"} />
      </div>

      <DataSourceBanner />

      <CaseTimingPanel timing={detail?.timing ?? null} />

      {status && (
        <Card title="进度" style={{ marginBottom: 16 }}>
          <JobProgressBar
            pct={status.progress_pct}
            simTimeS={status.sim_time_s}
            stepTimeS={status.step_time_s}
            frame={status.frame}
            framesTotal={status.frames_total}
            eta={status.eta}
          />
        </Card>
      )}

      <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
        <Col>
          <Button
            type="primary"
            disabled={!detail?.paths.inp}
            onClick={() =>
              void runAction("提交求解", () =>
                api.submit(decoded, { target: "remote", cpus: 48, memory_mb: 262144 }),
              )
            }
          >
            提交求解
          </Button>
        </Col>
        <Col>
          <Button
            disabled={!detail?.paths.inp}
            onClick={() => {
              void api
                .addToQueue({
                  slugs: [decoded],
                  target: "remote",
                  cpus: 48,
                  memory_mb: 262144,
                })
                .then(() => {
                  message.success("已加入仿真队列");
                  navigate("/queue");
                })
                .catch((e) => message.error(String(e)));
            }}
          >
            加入队列
          </Button>
        </Col>
        <Col>
          <Button onClick={() => void api.syncRemote(decoded).then(() => refetchStatus())}>
            同步远程
          </Button>
        </Col>
        <Col>
          <Popconfirm
            title="远程终止此算例？"
            description="将向服务器发送 stop_paperbox_job.sh，终止匹配 slug 的 Abaqus 进程。"
            onConfirm={handleStop}
            disabled={!isRunning}
          >
            <Button danger disabled={!isRunning}>
              远程终止
            </Button>
          </Popconfirm>
        </Col>
        <Col>
          <Button
            disabled={!detail?.paths.odb}
            onClick={() => void runAction("提取曲线", () => api.extract(decoded))}
          >
            提取曲线
          </Button>
        </Col>
        <Col>
          <Button
            disabled={!detail?.paths.curve_csv}
            onClick={() => void runAction("生成 PNG", () => api.plot(decoded))}
          >
            生成 PNG
          </Button>
        </Col>
        <Col>
          <Popconfirm
            title="移入回收站？"
            description={
              <div>
                <p style={{ marginBottom: 8 }}>
                  将 export / jobs / post 移至 output/trash/，可在回收站还原。
                </p>
                <Select
                  size="small"
                  style={{ width: "100%" }}
                  value={trashScope}
                  onChange={setTrashScope}
                  options={[
                    { label: "仅本机（默认）", value: "local" },
                    { label: "本机 + 远程服务器", value: "both" },
                  ]}
                />
              </div>
            }
            onConfirm={() => void handleDelete()}
          >
            <Button danger>移入回收站</Button>
          </Popconfirm>
        </Col>
      </Row>

      <Tabs
        items={[
          {
            key: "params",
            label: "参数设置",
            children: (
              <>
                <div style={{ marginBottom: 12 }}>
                  <Button size="small" onClick={showRawJson}>
                    查看原始 JSON
                  </Button>
                </div>
                <CaseSettingsPanel groups={detail?.settings_groups ?? []} />
              </>
            ),
          },
          {
            key: "logs",
            label: "作业日志",
            children: (
              <pre style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 16, overflow: "auto" }}>
                {logs?.sta_tail || "暂无 .sta 日志"}
              </pre>
            ),
          },
          {
            key: "results",
            label: "结果",
            children: curve ? (
              <StressStrainChart points={curve.points} />
            ) : (
              <Typography.Text type="secondary">暂无应力–应变曲线，请先完成求解并提取。</Typography.Text>
            ),
          },
        ]}
      />
    </div>
  );
}
