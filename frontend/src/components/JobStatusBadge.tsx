import { Tag } from "antd";

const COLORS: Record<string, string> = {
  RUNNING: "processing",
  COMPLETED: "success",
  FAILED: "error",
  STOPPED: "warning",
  WAITING: "default",
};

export function JobStatusBadge({ status }: { status: string }) {
  return <Tag color={COLORS[status] ?? "default"}>{status}</Tag>;
}
