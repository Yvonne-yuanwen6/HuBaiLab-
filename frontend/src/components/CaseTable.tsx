import { Space, Table, Tag } from "antd";
import type { ColumnsType, TableProps } from "antd/es/table";
import { Link } from "react-router-dom";
import type { CaseSummary } from "../types";
import { JobStatusBadge } from "./JobStatusBadge";
import { LocationTag } from "./LocationTag";

interface Props {
  cases: CaseSummary[];
  loading?: boolean;
  showTags?: boolean;
  selectedSlugs?: string[];
  onSelectSlugs?: (slugs: string[]) => void;
}

export function CaseTable({
  cases,
  loading,
  showTags = false,
  selectedSlugs,
  onSelectSlugs,
}: Props) {
  const columns: ColumnsType<CaseSummary> = [
    {
      title: "Slug",
      dataIndex: "slug",
      key: "slug",
      render: (slug: string) => (
        <Link to={`/cases/${encodeURIComponent(slug)}`}>
          <code style={{ fontSize: 12 }}>{slug}</code>
        </Link>
      ),
    },
    {
      title: "位置",
      key: "location",
      width: 100,
      render: (_: unknown, row: CaseSummary) => <LocationTag row={row} />,
    },
    ...(showTags
      ? [
          {
            title: "标签",
            key: "display_tags",
            width: 220,
            render: (_: unknown, row: CaseSummary) =>
              row.display_tags?.length ? (
                <Space wrap size={[0, 4]}>
                  {row.display_tags.slice(0, 4).map((t) => (
                    <Tag key={t} style={{ margin: 0, fontSize: 11 }}>
                      {t}
                    </Tag>
                  ))}
                  {(row.display_tags.length ?? 0) > 4 && (
                    <Tag style={{ margin: 0, fontSize: 11 }}>+{row.display_tags!.length - 4}</Tag>
                  )}
                </Space>
              ) : (
                "—"
              ),
          } as ColumnsType<CaseSummary>[number],
        ]
      : []),
    {
      title: "Q",
      dataIndex: "Q",
      key: "Q",
      width: 64,
      render: (q: number | null) => (q != null ? q : "—"),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (status: string) => <JobStatusBadge status={status} />,
    },
    {
      title: "INP",
      dataIndex: "has_inp",
      key: "has_inp",
      width: 64,
      render: (v: boolean) => (v ? "✓" : "—"),
    },
    {
      title: "ODB",
      dataIndex: "has_odb",
      key: "has_odb",
      width: 64,
      render: (v: boolean) => (v ? "✓" : "—"),
    },
    {
      title: "完成时间",
      dataIndex: "completed_at_label",
      key: "completed_at",
      width: 170,
      render: (v: string | null) => v ?? "—",
    },
    {
      title: "墙钟(s)",
      dataIndex: "wallclock_seconds",
      key: "wallclock_seconds",
      width: 88,
      render: (v: number | null) => (v != null ? v : "—"),
    },
    {
      title: "曲线",
      dataIndex: "has_curve",
      key: "has_curve",
      width: 64,
      render: (v: boolean) => (v ? "✓" : "—"),
    },
  ];

  const rowSelection: TableProps<CaseSummary>["rowSelection"] | undefined = onSelectSlugs
    ? {
        selectedRowKeys: selectedSlugs ?? [],
        onChange: (keys) => onSelectSlugs(keys as string[]),
        getCheckboxProps: (row) => ({ disabled: !row.has_inp }),
      }
    : undefined;

  return (
    <Table
      rowKey="slug"
      loading={loading}
      columns={columns}
      dataSource={cases}
      rowSelection={rowSelection}
      pagination={{ pageSize: 20, showSizeChanger: true }}
      size="middle"
    />
  );
}
