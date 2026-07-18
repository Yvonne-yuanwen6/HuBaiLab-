import {
  Button,
  Card,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  VerticalAlignBottomOutlined,
  VerticalAlignTopOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { JobStatusBadge } from "../components/JobStatusBadge";
import type { QueueItem } from "../types";

export function QueuePage() {
  const queryClient = useQueryClient();
  const [selectedSlugs, setSelectedSlugs] = useState<string[]>([]);
  const [cpus, setCpus] = useState(48);
  const [memoryMb, setMemoryMb] = useState(262144);
  const [target, setTarget] = useState("remote");

  const { data: queue, isLoading } = useQuery({
    queryKey: ["sim-queue"],
    queryFn: () => api.getQueue(),
    refetchInterval: 5000,
  });

  const { data: caseList } = useQuery({
    queryKey: ["cases", false],
    queryFn: () => api.listCases(false),
  });

  const casesWithInp = useMemo(
    () => (caseList?.cases ?? []).filter((c) => c.has_inp),
    [caseList],
  );

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["sim-queue"] });

  const runMut = (fn: () => Promise<unknown>, ok?: string) => {
    fn()
      .then(() => {
        if (ok) message.success(ok);
        invalidate();
      })
      .catch((e) => message.error(String(e)));
  };

  const addMutation = useMutation({
    mutationFn: () =>
      api.addToQueue({
        slugs: selectedSlugs,
        target,
        cpus,
        memory_mb: memoryMb,
      }),
    onSuccess: () => {
      message.success("已加入队列");
      setSelectedSlugs([]);
      invalidate();
    },
    onError: (e) => message.error(String(e)),
  });

  const columns = [
    {
      title: "#",
      dataIndex: "order",
      width: 48,
      render: (o: number) => o + 1,
    },
    {
      title: "Slug",
      dataIndex: "slug",
      render: (slug: string) => (
        <Link to={`/monitor?slug=${encodeURIComponent(slug)}`}>
          <code style={{ fontSize: 12 }}>{slug}</code>
        </Link>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (s: string) => <JobStatusBadge status={s.toUpperCase()} />,
    },
    {
      title: "目标",
      dataIndex: "target",
      width: 90,
    },
    {
      title: "CPU / 内存",
      key: "res",
      width: 140,
      render: (_: unknown, row: QueueItem) => `${row.cpus} / ${row.memory_mb} MB`,
    },
    {
      title: "错误",
      dataIndex: "error",
      ellipsis: true,
      render: (e: string | null) => e || "—",
    },
    {
      title: "排序",
      key: "move",
      width: 180,
      render: (_: unknown, row: QueueItem) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={row.status === "running"}
            onClick={() => runMut(() => api.moveQueueItem(row.id, "up"))}
          />
          <Button
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={row.status === "running"}
            onClick={() => runMut(() => api.moveQueueItem(row.id, "down"))}
          />
          <Button
            size="small"
            icon={<VerticalAlignTopOutlined />}
            disabled={row.status === "running"}
            onClick={() => runMut(() => api.moveQueueItem(row.id, "top"))}
          />
          <Button
            size="small"
            icon={<VerticalAlignBottomOutlined />}
            disabled={row.status === "running"}
            onClick={() => runMut(() => api.moveQueueItem(row.id, "bottom"))}
          />
        </Space>
      ),
    },
    {
      title: "",
      key: "del",
      width: 64,
      render: (_: unknown, row: QueueItem) => (
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          disabled={row.status === "running"}
          onClick={() => runMut(() => api.removeQueueItem(row.id), "已移除")}
        />
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          仿真队列
        </Typography.Title>
        <Space>
          <Tag color={queue?.running ? "processing" : "default"}>
            {queue?.running ? "队列运行中" : "已暂停"}
          </Tag>
          <Button type="primary" onClick={() => runMut(() => api.startQueue(), "队列已开始")}>
            开始
          </Button>
          <Button onClick={() => runMut(() => api.pauseQueue(), "队列已暂停")}>暂停</Button>
          <Button onClick={() => runMut(() => api.clearFinishedQueue(), "已清空完成项")}>
            清空已完成
          </Button>
        </Space>
      </div>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        串行提交：同一时间只跑一个算例。可对 pending 项上移/下移/置顶/置底调整顺序。
      </Typography.Paragraph>

      <Card title="加入队列" style={{ marginBottom: 16 }}>
        <Space wrap align="start">
          <Select
            mode="multiple"
            allowClear
            showSearch
            placeholder="选择已有 INP 的算例"
            style={{ minWidth: 420 }}
            value={selectedSlugs}
            onChange={setSelectedSlugs}
            options={casesWithInp.map((c) => ({ label: c.slug, value: c.slug }))}
          />
          <Select
            value={target}
            onChange={setTarget}
            style={{ width: 140 }}
            options={[
              { label: "远程", value: "remote" },
              { label: "本机", value: "local" },
            ]}
          />
          <InputNumber
            min={1}
            max={128}
            value={cpus}
            onChange={(v) => setCpus(v ?? 48)}
            addonBefore="CPU"
          />
          <InputNumber
            min={8192}
            step={8192}
            value={memoryMb}
            onChange={(v) => setMemoryMb(v ?? 262144)}
            addonBefore="MB"
          />
          <Button
            type="primary"
            disabled={!selectedSlugs.length}
            loading={addMutation.isPending}
            onClick={() => addMutation.mutate()}
          >
            加入队列
          </Button>
        </Space>
      </Card>

      <Card>
        <Table<QueueItem>
          rowKey="id"
          size="small"
          loading={isLoading}
          dataSource={queue?.items ?? []}
          columns={columns}
          pagination={false}
        />
      </Card>
    </div>
  );
}
