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
import { Link, useNavigate } from "react-router-dom";
import { api, pollTask } from "../api/client";
import type { ExportSettings, VerifiedCad } from "../types";

const DEFAULT_SETTINGS: ExportSettings = {
  Q: 0,
  Af: 2,
  cells: 4,
  cell_size: 20,
  rod_diameter: 2,
  structure: "bcc",
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
  material_model: "neo_hooke",
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
  const [meshing, setMeshing] = useState(false);
  const navigate = useNavigate();
  const structure = Form.useWatch("structure", form);

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

  const onValuesChange = (changed: Partial<ExportSettings>, all: ExportSettings) => {
    if (changed.structure === "bcc") {
      form.setFieldsValue({ Q: 0 });
      all = { ...all, Q: 0, structure: "bcc" };
    } else if (changed.structure === "sfbls" && !(all.Q > 0)) {
      form.setFieldsValue({ Q: 0.5 });
      all = { ...all, Q: 0.5, structure: "sfbls" };
    }
    void refreshPreview(all);
  };

  const applyPreset = (key: string) => {
    const preset = presets[key];
    if (!preset) return;
    const merged = { ...DEFAULT_SETTINGS, ...preset };
    if (!merged.structure) {
      merged.structure = merged.Q > 0 ? "sfbls" : "bcc";
    }
    form.setFieldsValue(merged);
    void refreshPreview(merged);
    message.success(`已加载预设：${key}`);
  };

  const pollUntilDone = (
    taskId: string,
    okMsg: string,
    failMsg: string,
    onDone?: (slug: string | null) => void,
    setBusy?: (v: boolean) => void,
  ) => {
    pollTask(taskId, (t) => {
      if (t.status === "done") {
        message.success(okMsg);
        onDone?.(t.slug);
        setBusy?.(false);
      } else if (t.status === "failed") {
        message.error(t.error || failMsg);
        setBusy?.(false);
      }
    });
  };

  const handleExport = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const task = await api.export(values);
      message.info("导出任务已启动");
      pollUntilDone(
        task.task_id,
        "导出完成",
        "导出失败",
        (slug) => {
          if (slug) navigate(`/monitor?slug=${encodeURIComponent(slug)}`);
        },
        setSubmitting,
      );
    } catch (e) {
      message.error(String(e));
      setSubmitting(false);
    }
  };

  const handleMeshOnly = async () => {
    const values = await form.validateFields();
    setMeshing(true);
    try {
      const task = await api.mesh(values);
      message.info("网格/导出任务已启动");
      pollUntilDone(task.task_id, "网格任务完成", "网格任务失败", undefined, setMeshing);
    } catch (e) {
      message.error(String(e));
      setMeshing(false);
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
              <Form.Item name="structure" label="结构类型" rules={[{ required: true }]}>
                <Select
                  options={[
                    { label: "BCC（Q = 0）", value: "bcc" },
                    { label: "SFBLS（Q > 0）", value: "sfbls" },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="Q"
                label="周期因子 Q"
                rules={[{ required: true }]}
                extra={structure === "bcc" ? "BCC 固定为 0" : "SFBLS 常用 0.5 / 1.0 / 1.5"}
              >
                <InputNumber
                  min={0}
                  max={2}
                  step={0.5}
                  disabled={structure === "bcc"}
                  style={{ width: "100%" }}
                />
              </Form.Item>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name="cell_size" label="单胞边长 L (mm)">
                    <InputNumber min={5} max={50} step={1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="rod_diameter" label="杆径 (mm)">
                    <InputNumber min={0.5} max={8} step={0.1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="Af" label="振幅 Af">
                    <InputNumber min={0.5} max={8} step={0.1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="cells" label="阵列 cells (N×N×N)">
                <InputNumber min={1} max={8} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item
                name="cad_path"
                label="verified STEP（可选，留空自动查找）"
                extra={
                  <span>
                    没有合适 STEP？前往 <Link to="/cad">CAD / STEP 生成</Link>
                  </span>
                }
              >
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
              <Form.Item name="mesh_on_server" valuePropName="checked">
                <Checkbox
                  onChange={(e) => {
                    if (e.target.checked) form.setFieldsValue({ mesh_locally: false });
                  }}
                >
                  CAE 网格在服务器运行（Windows 默认）
                </Checkbox>
              </Form.Item>
              <Form.Item name="mesh_locally" valuePropName="checked">
                <Checkbox
                  onChange={(e) => {
                    if (e.target.checked) form.setFieldsValue({ mesh_on_server: false });
                  }}
                >
                  CAE 网格在本机运行
                </Checkbox>
              </Form.Item>
              <Button loading={meshing} onClick={() => void handleMeshOnly()}>
                仅启动网格/导出任务
              </Button>
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
                  options={[
                    { label: "Neo-Hooke", value: "neo_hooke" },
                    { label: "elastic", value: "elastic" },
                    { label: "marlow", value: "marlow" },
                  ]}
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
                结构: {preview?.structure ?? structure ?? "—"} · variant:{" "}
                {preview?.variant_name ?? "—"} · L={preview?.cell_size ?? "—"} mm · Ø=
                {preview?.rod_diameter ?? "—"} mm
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
