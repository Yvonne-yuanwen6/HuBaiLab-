import { Layout, Menu, Typography } from "antd";
import {
  DashboardOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  ExportOutlined,
  BuildOutlined,
  MonitorOutlined,
  OrderedListOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Link, Outlet, useLocation } from "react-router-dom";

const { Sider, Content, Header } = Layout;

const items = [
  { key: "/", icon: <DashboardOutlined />, label: <Link to="/">仪表盘</Link> },
  { key: "/cases", icon: <UnorderedListOutlined />, label: <Link to="/cases">算例</Link> },
  { key: "/cad", icon: <BuildOutlined />, label: <Link to="/cad">CAD / STEP</Link> },
  { key: "/export", icon: <ExportOutlined />, label: <Link to="/export">导出 INP</Link> },
  { key: "/queue", icon: <OrderedListOutlined />, label: <Link to="/queue">仿真队列</Link> },
  { key: "/monitor", icon: <MonitorOutlined />, label: <Link to="/monitor">作业监控</Link> },
  { key: "/trash", icon: <DeleteOutlined />, label: <Link to="/trash">回收站</Link> },
  {
    key: "comsol",
    icon: <ExperimentOutlined />,
    label: <span style={{ color: "#999" }}>COMSOL（即将推出）</span>,
    disabled: true,
  },
];

export function AppLayout() {
  const location = useLocation();
  const selected = (() => {
    if (location.pathname.startsWith("/cases")) return "/cases";
    if (location.pathname.startsWith("/cad")) return "/cad";
    if (location.pathname.startsWith("/export")) return "/export";
    if (location.pathname.startsWith("/queue")) return "/queue";
    if (location.pathname.startsWith("/monitor")) return "/monitor";
    if (location.pathname.startsWith("/trash")) return "/trash";
    return "/";
  })();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="light" width={220} breakpoint="lg" collapsedWidth={0}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #f0f0f0" }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            HuBaiLab
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Abaqus 压缩仿真
          </Typography.Text>
        </div>
        <Menu mode="inline" selectedKeys={[selected === "/" ? "/" : selected]} items={items} />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            borderBottom: "1px solid #f0f0f0",
            display: "flex",
            alignItems: "center",
          }}
        >
          <Typography.Text type="secondary">Hu & Bai 点阵结构 · Explicit 压缩</Typography.Text>
        </Header>
        <Content style={{ padding: 24, background: "#f5f5f5" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
