import { Select, Space } from "antd";

export const STATUS_OPTIONS = [
  { label: "运行中", value: "RUNNING" },
  { label: "已完成", value: "COMPLETED" },
  { label: "失败", value: "FAILED" },
  { label: "已停止", value: "STOPPED" },
  { label: "等待中", value: "WAITING" },
] as const;

interface Props {
  value?: string[];
  onChange: (values: string[]) => void;
}

export function StatusFilterSelect({ value = [], onChange }: Props) {
  return (
    <Select
      mode="multiple"
      allowClear
      placeholder="按状态筛选"
      style={{ minWidth: 280 }}
      value={value}
      onChange={onChange}
      options={STATUS_OPTIONS.map((o) => ({ label: o.label, value: o.value }))}
      maxTagCount="responsive"
    />
  );
}

interface QuickProps {
  active: string[];
  onChange: (values: string[]) => void;
}

export function StatusQuickFilters({ active, onChange }: QuickProps) {
  const presets: { label: string; values: string[] }[] = [
    { label: "全部", values: [] },
    { label: "运行中", values: ["RUNNING"] },
    { label: "已完成", values: ["COMPLETED"] },
    { label: "失败", values: ["FAILED"] },
    { label: "未完成", values: ["RUNNING", "WAITING", "STOPPED"] },
  ];

  return (
    <Space wrap size={[8, 8]}>
      {presets.map((p) => {
        const isActive =
          p.values.length === active.length && p.values.every((v) => active.includes(v));
        return (
          <a
            key={p.label}
            onClick={() => onChange(p.values)}
            style={{
              padding: "2px 10px",
              borderRadius: 4,
              background: isActive ? "#1677ff" : "#f0f0f0",
              color: isActive ? "#fff" : "inherit",
            }}
          >
            {p.label}
          </a>
        );
      })}
    </Space>
  );
}

export function filterByStatuses<T extends { status: string }>(
  items: T[],
  statuses: string[],
): T[] {
  if (!statuses.length) return items;
  return items.filter((c) => statuses.includes(c.status));
}
