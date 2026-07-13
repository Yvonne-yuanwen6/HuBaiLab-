import { Alert } from "antd";

interface Props {
  label?: string;
  hint?: string;
}

export function DataSourceBanner({
  label = "本机 output/",
  hint = "列表与状态读取本机 output/ 目录。作业若在 Linux 服务器运行，请先在「作业监控」开启「远程同步」。",
}: Props) {
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message={`数据来源：${label}`}
      description={hint}
    />
  );
}
