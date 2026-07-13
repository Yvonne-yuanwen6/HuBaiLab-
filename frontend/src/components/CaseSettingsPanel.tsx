import { Descriptions, Table } from "antd";
import type { SettingGroup } from "../types";

interface Props {
  groups: SettingGroup[];
}

export function CaseSettingsPanel({ groups }: Props) {
  if (!groups.length) {
    return <div style={{ color: "#999" }}>暂无参数记录（需先完成 INP 导出并生成 manifest/meta）</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {groups.map((group) => (
        <div key={group.title}>
          <h4 style={{ marginBottom: 12 }}>{group.title}</h4>
          <Table
            size="small"
            pagination={false}
            rowKey="key"
            dataSource={group.items}
            columns={[
              { title: "参数", dataIndex: "label", width: 220 },
              {
                title: "值",
                dataIndex: "value",
                render: (v: string) => <span style={{ fontFamily: "monospace" }}>{v}</span>,
              },
            ]}
          />
        </div>
      ))}
    </div>
  );
}

interface TimingProps {
  timing: {
    exported_at_label?: string | null;
    completed_at_label?: string | null;
    wallclock_seconds?: number | null;
    odb_size_bytes?: number | null;
  } | null;
}

export function CaseTimingPanel({ timing }: TimingProps) {
  if (!timing) return null;
  const odbMb =
    timing.odb_size_bytes != null ? `${(timing.odb_size_bytes / 1024 / 1024).toFixed(1)} MB` : "—";

  return (
    <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
      <Descriptions.Item label="导出时间">{timing.exported_at_label ?? "—"}</Descriptions.Item>
      <Descriptions.Item label="完成时间">{timing.completed_at_label ?? "—"}</Descriptions.Item>
      <Descriptions.Item label="墙钟耗时">
        {timing.wallclock_seconds != null ? `${timing.wallclock_seconds} s` : "—"}
      </Descriptions.Item>
      <Descriptions.Item label="ODB 大小">{odbMb}</Descriptions.Item>
    </Descriptions>
  );
}
