import {
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Steps,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, pollTask } from "../api/client";
import type { ExportSettings, VerifiedCad } from "../types";

const DEFAULT_SETTINGS: ExportSettings = {
  Q: 0,
  Af: 2,
  cells: 4,
  cad_path: "",
  cae_seed_mm: 0.6,
  cae_mesh_quality: "lattice_contact",
  cae_rods_per_diameter: 3,
  cae_virtual_topology: true,
  cae_element_type: "C3D4",
  slug_mode: "long",
  short_slug: "",
  profile: "fast",
  strain: 0.8,
  load_rate_mm_min: 5,
  material_model: "paper",
  contact_store_offsets: true,
  contact_settle: true,
  case_suffix: "cae_tet0p6mm80_5mmin_paperbox",
  mesh_on_server: true,
  mesh_locally: false,
  remote_host: "",
  remote_root: "",
  submit_target: "remote",
  submit_cpus: 48,
  submit_memory_mb: 262144,
  submit_recover: false,
  submit_restart_from: "",
};

interface Props {
  presets: Record<string, ExportSettings>;
  cadFiles: VerifiedCad[];
}

export function ExportForm({ presets, cadFiles }: Props) {
  const [step, setStep] = useState(0);
  const [form] = Form.useForm<ExportSettings>();
  const [preview, setPreview] = useState<ExportSettings | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    form.setFieldsValue(DEFAULT_SETTINGS);
    void refreshPreview(DEFAULT_SETTINGS);
  }, [form]);

  const refreshPreview = async (values: Partial<ExportSettings>) => {
    try {
      const p = await api.previewSettings(values);
      setPreview(p);
    } catch {
      setPreview(null);
    }
  };

  const onValuesChange = (_: Partial<ExportSettings>, all: ExportSettings) => {
    void refreshPreview(all);
  };

  const applyPreset = (key: string) => {
    const preset = presets[key];
    if (!preset) return;
    form.setFieldsValue({ ...DEFAULT_SETTINGS, ...preset });
    void refreshPreview({ ...DEFAULT_SETTINGS, ...preset });
    message.success(`已加载预设：${key}`);
  };

  const handleExport = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const task = await api.export(values);
      message.info("导出任务已启动");
      pollTask(task.task_id, (t) => {
        if (t.status === "done") {
          message.success("导出完成");
          if (t.slug) navigate(`/monitor?slug=${encodeURIComponent(t.slug)}`);
          setSubmitting(false);
        } else if (t.status === "failed") {
          message.error(t.error || "导出失败");
          setSubmitting(false);
        }
      });
    } catch (e) {
      message.error(String(e));
      setSubmitting(false);
    }
  };

  return (
    <Row gutter={24}>
      <Col span={6}>
        <Card title="预设" size="small">
          {Object.keys(presets).map((key) => (
            <Button key={key} block style={{ marginBottom: 8 }} onClick={() => applyPreset(key)}>
              {key}
            </Button>
          ))}
        </Card>
      </Col>
      <Col span={18}>
        <Steps
          current={step}
          items={[
            { title: "几何" },
            { title: "网格" },
            { title: "载荷" },
            { title: "计算" },
            { title: "确认" },
          ]}
          style={{ marginBottom: 24 }}
        />
        <Form form={form} layout="vertical" onValuesChange={onValuesChange}>
          {step === 0 && (
            <>
              <Form.Item name="Q" label="周期因子 Q" rules={[{ required: true }]}>
                <InputNumber min={0} max={2} step={0.5} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="cells" label="阵列 cells (N×N×N)">
                <InputNumber min={1} max={8} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="cad_path" label="verified STEP（可选，留空自动查找）">
                <Select
                  allowClear
                  showSearch
                  placeholder="选择 CAD 文件"
                  options={cadFiles.map((f) => ({ label: f.name, value: f.path }))}
                />
              </Form.Item>
            </>
          )}
          {step === 1 && (
            <>
              <Form.Item name="cae_seed_mm" label="CAE 全局 seed (mm)">
                <InputNumber min={0.1} max={3} step={0.1} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="cae_mesh_quality" label="网格 preset">
                <Select
                  options={[
                    "fast",
                    "lattice",
                    "lattice_contact",
                    "lattice_curve",
                    "paper",
                  ].map((v) => ({ label: v, value: v }))}
                />
              </Form.Item>
              <Form.Item name="cae_element_type" label="单元类型">
                <Select options={["C3D4", "C3D10", "C3D10M"].map((v) => ({ label: v, value: v }))} />
              </Form.Item>
              <Form.Item name="cae_rods_per_diameter" label="杆径方向单元数">
                <InputNumber min={2} max={8} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="cae_virtual_topology" valuePropName="checked">
                <Checkbox>Virtual Topology</Checkbox>
              </Form.Item>
            </>
          )}
          {step === 2 && (
            <>
              <Form.Item name="strain" label="目标工程应变">
                <InputNumber min={0.05} max={0.95} step={0.05} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="load_rate_mm_min" label="加载速率 (mm/min)">
                <InputNumber min={1} max={60} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="material_model" label="材料模型">
                <Select
                  options={["paper", "elastic", "marlow", "hyperelastic"].map((v) => ({
                    label: v,
                    value: v,
                  }))}
                />
              </Form.Item>
              <Form.Item name="contact_store_offsets" valuePropName="checked">
                <Checkbox>Contact STORE OFFSETS</Checkbox>
              </Form.Item>
              <Form.Item name="contact_settle" valuePropName="checked">
                <Checkbox>ContactSettle 预压步</Checkbox>
              </Form.Item>
              <Form.Item name="case_suffix" label="case suffix">
                <Input />
              </Form.Item>
            </>
          )}
          {step === 3 && (
            <>
              <Form.Item name="submit_target" label="提交目标">
                <Select
                  options={[
                    { label: "远程 Linux 服务器", value: "remote" },
                    { label: "本机", value: "local" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="mesh_on_server" valuePropName="checked">
                <Checkbox>CAE 网格在服务器运行（Windows 默认）</Checkbox>
              </Form.Item>
              <Form.Item name="submit_cpus" label="求解 CPU 数">
                <InputNumber min={1} max={128} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="submit_memory_mb" label="求解内存 (MB)">
                <InputNumber min={8192} step={8192} style={{ width: "100%" }} />
              </Form.Item>
            </>
          )}
          {step === 4 && (
            <Card size="small">
              <Typography.Paragraph>
                <strong>预计 slug：</strong>
                <br />
                <code>{preview?.slug_preview ?? "—"}</code>
              </Typography.Paragraph>
              <Typography.Paragraph type="secondary">
                variant: {preview?.variant_name ?? "—"}
              </Typography.Paragraph>
            </Card>
          )}
        </Form>
        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          {step > 0 && <Button onClick={() => setStep((s) => s - 1)}>上一步</Button>}
          {step < 4 && (
            <Button type="primary" onClick={() => setStep((s) => s + 1)}>
              下一步
            </Button>
          )}
          {step === 4 && (
            <Button type="primary" loading={submitting} onClick={() => void handleExport()}>
              开始导出 INP
            </Button>
          )}
        </div>
      </Col>
    </Row>
  );
}
