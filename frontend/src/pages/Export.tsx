import { Card, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ExportForm } from "../components/ExportForm";

export function ExportPage() {
  const { data: presets = {} } = useQuery({
    queryKey: ["presets"],
    queryFn: api.getPresets,
  });
  const { data: cadFiles = [] } = useQuery({
    queryKey: ["cad"],
    queryFn: api.listCad,
  });

  return (
    <div>
      <Typography.Title level={3}>导出 INP</Typography.Title>
      <Typography.Paragraph type="secondary">
        paper_box CAE C3D4 四面体网格 → Explicit 压缩 INP（STORE OFFSETS + ContactSettle）
      </Typography.Paragraph>
      <Card>
        <ExportForm presets={presets} cadFiles={cadFiles} />
      </Card>
    </div>
  );
}
