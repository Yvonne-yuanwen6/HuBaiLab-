import { Button, Card, Popconfirm, Table, Typography, message } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { TrashItem } from "../types";

export function TrashPage() {
  const queryClient = useQueryClient();
  const { data: items = [], isLoading, refetch, isFetching } = useQuery({
    queryKey: ["trash"],
    queryFn: api.listTrash,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["trash"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["cases"] });
    void refetch();
  };

  const handleRestore = async (trashId: string) => {
    try {
      await api.restoreTrash(trashId);
      message.success("已还原算例");
      refresh();
    } catch (e) {
      message.error(String(e));
    }
  };

  const handlePurge = async (trashId: string) => {
    try {
      await api.purgeTrash(trashId);
      message.success("已永久删除");
      refresh();
    } catch (e) {
      message.error(String(e));
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          回收站
        </Typography.Title>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={isFetching}>
          刷新
        </Button>
      </div>

      <Typography.Paragraph type="secondary">
        删除算例时，export / jobs / post 目录会移入 <code>output/trash/</code>，可在此还原或永久清除。
      </Typography.Paragraph>

      <Card>
        <Table<TrashItem>
          rowKey="trash_id"
          loading={isLoading}
          dataSource={items}
          pagination={{ pageSize: 15 }}
          columns={[
            {
              title: "Slug",
              dataIndex: "slug",
              render: (slug: string) => <code style={{ fontSize: 12 }}>{slug}</code>,
            },
            {
              title: "删除时间",
              dataIndex: "deleted_at_label",
              width: 180,
              render: (v: string | null) => v ?? "—",
            },
            {
              title: "内容",
              key: "parts",
              width: 120,
              render: (_: unknown, row: TrashItem) =>
                [row.had_export && "export", row.had_jobs && "jobs", row.had_post && "post"]
                  .filter(Boolean)
                  .join(", ") || "—",
            },
            {
              title: "操作",
              key: "actions",
              width: 200,
              render: (_: unknown, row: TrashItem) => (
                <>
                  <Popconfirm
                    title="还原此算例？"
                    description="若原路径已存在同名目录将无法还原。"
                    onConfirm={() => void handleRestore(row.trash_id)}
                  >
                    <Button type="link" size="small">
                      还原
                    </Button>
                  </Popconfirm>
                  <Popconfirm
                    title="永久删除？"
                    description="不可恢复。"
                    onConfirm={() => void handlePurge(row.trash_id)}
                  >
                    <Button type="link" size="small" danger>
                      永久删除
                    </Button>
                  </Popconfirm>
                </>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
