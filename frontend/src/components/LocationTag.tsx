import { Tag } from "antd";
import type { CaseSummary } from "../types";

const COLORS: Record<string, string> = {
  local: "blue",
  remote: "orange",
  both: "purple",
};

export function LocationTag({ row }: { row: CaseSummary }) {
  const location = row.location ?? "local";
  const label = row.location_label ?? "本机";
  return (
    <Tag color={COLORS[location] ?? "default"} style={{ margin: 0, fontSize: 11 }}>
      {label}
    </Tag>
  );
}
