import {
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  InputNumber,
  Row,
  Select,
  Table,
  Typography,
  message,
} from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, pollTask } from "../api/client";
import type { CadGenerateRequest, VerifiedCad } from "../types";

export function CadGeneratePage() {
  const [form] = Form.useForm<CadGenerateRequest>();
  const [submitting, setSubmitting] = useState(false);
  const [log, setLog] = useState("");
  const queryClient = useQueryClient();
  const structure = Form.useWatch("structure", form);

  const { data: cadFiles = [], isLoading } = useQuery({
    queryKey: ["cad-verified"],
    queryFn: () => api.listCad(),
  });

  const handleGenerate = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    setLog("");
    try {
      const task = await api.generateCad(values);
      message.info("STEP 生成任务已启动");
      pollTask(task.task_id, (t) => {
        setLog(t.stdout_tail || t.stderr_tail || t.error || "");
        if (t.status === "done") {
          message.success("STEP 生成完成");
          void queryClient.invalidateQueries({ queryKey: ["cad-verified"] });
          setSubmitting(false);
        } else if (t.status === "failed") {
          message.error(t.error || "STEP 生成失败");
          setSubmitting(false);
        }
      });
    } catch (e) {
      message.error(String(e));
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: "文件名",
      dataIndex: "name",
      key: "name",
      render: (name: string) => <code style={{ fontSize: 12 }}>{name}</code>,
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      key: "size_bytes",
      width: 120,
      render: (n: number) => `${(n / 1024 / 1024).toFixed(2)} MB`,
    },
    {
      title: "路径",
      dataIndex: "path",
      key: "path",
      ellipsis: true,
    },
  ];

  return (
    <div>
      <Typography.Title level={3}>CAD / STEP 生成</Typography.Title>
      <Typography.Paragraph type="secondary">
        调用 paper_box array fuse 脚本生成点阵 STEP，输出到 <code>output/cad/verified/</code>。
        完成后可在 <Link to="/export">导出 INP</Link> 中选用。
      </Typography.Paragraph>

      <Row gutter={24}>
        <Col span={10}>
          <Card title="生成参数">
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                structure: "bcc",
                Q: 0,
                cells: 4,
                L: 20,
                backend: "ocp",
                mode: "auto",
                force: false,
                ocp_fuse_mode: "hierarchical_batch",
              }}
              onValuesChange={(changed, all) => {
                if (changed.structure === "bcc") {
                  form.setFieldsValue({ Q: 0 });
                } else if (changed.structure === "sfbls" && !(all.Q > 0)) {
                  form.setFieldsValue({ Q: 0.5 });
                }
              }}
            >
              <Form.Item name="structure" label="结构类型" rules={[{ required: true }]}>
                <Select
                  options={[
                    { label: "BCC（Q = 0）", value: "bcc" },
                    { label: "SFBLS（Q > 0）", value: "sfbls" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="Q" label="周期因子 Q" rules={[{ required: true }]}>
                <InputNumber
                  min={0}
                  max={2}
                  step={0.5}
                  disabled={structure === "bcc"}
                  style={{ width: "100%" }}
                />
              </Form.Item>
              <Form.Item name="L" label="单胞边长 L (mm)">
                <InputNumber min={5} max={50} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="cells" label="阵列 cells (N×N×N)">
                <InputNumber min={1} max={8} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="backend" label="融合后端">
                <Select
                  options={[
                    { label: "OCP（推荐）", value: "ocp" },
                    { label: "Gmsh", value: "gmsh" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="mode" label="模式">
                <Select
                  options={[
                    { label: "默认 layered（auto）", value: "auto" },
                    { label: "auto-only（整阵列 OCC）", value: "auto_only" },
                    { label: "stepwise-only（SW 指导）", value: "stepwise" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="ocp_fuse_mode" label="OCP fuse 模式">
                <Select
                  options={[
                    { label: "hierarchical_batch", value: "hierarchical_batch" },
                    { label: "sequential", value: "sequential" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="force" valuePropName="checked">
                <Checkbox>强制重算（--force）</Checkbox>
              </Form.Item>
              <Button type="primary" loading={submitting} onClick={() => void handleGenerate()}>
                开始生成 STEP
              </Button>
            </Form>
          </Card>
        </Col>
        <Col span={14}>
          <Card
            title="verified STEP"
            extra={
              <Button size="small" onClick={() => void queryClient.invalidateQueries({ queryKey: ["cad-verified"] })}>
                刷新
              </Button>
            }
          >
            <Table<VerifiedCad>
              rowKey="path"
              size="small"
              loading={isLoading}
              dataSource={cadFiles}
              columns={columns}
              pagination={{ pageSize: 8 }}
            />
          </Card>
          {log ? (
            <Card title="任务输出" style={{ marginTop: 16 }} size="small">
              <pre
                style={{
                  background: "#1e1e1e",
                  color: "#d4d4d4",
                  padding: 12,
                  maxHeight: 280,
                  overflow: "auto",
                  fontSize: 12,
                }}
              >
                {log}
              </pre>
            </Card>
          ) : null}
        </Col>
      </Row>
    </div>
  );
}
