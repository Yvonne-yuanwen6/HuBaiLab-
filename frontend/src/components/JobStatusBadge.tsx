import { Tag } from "antd";

const COLORS: Record<string, string> = {
  RUNNING: "processing",
  COMPLETED: "success",
  FAILED: "error",
  STOPPED: "warning",
  WAITING: "default",
  PENDING: "default",
  DONE: "success",
  CANCELLED: "warning",
};

export function JobStatusBadge({ status }: { status: string }) {
  const key = (status || "").toUpperCase();
  return <Tag color={COLORS[key] ?? "default"}>{key}</Tag>;
}
