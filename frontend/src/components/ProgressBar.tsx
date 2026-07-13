import { Progress, Typography } from "antd";

interface Props {
  pct: number;
  simTimeS?: number;
  stepTimeS?: number | null;
  frame?: number | null;
  framesTotal?: number | null;
  eta?: string | null;
}

export function JobProgressBar({
  pct,
  simTimeS,
  stepTimeS,
  frame,
  framesTotal,
  eta,
}: Props) {
  return (
    <div>
      <Progress percent={Math.round(pct)} status={pct >= 100 ? "success" : "active"} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {simTimeS !== undefined && stepTimeS
          ? `仿真时间 ${simTimeS.toFixed(1)} / ${stepTimeS.toFixed(1)} s`
          : null}
        {frame != null && framesTotal != null ? ` · 帧 ${frame}/${framesTotal}` : null}
        {eta ? ` · ETA ${eta}` : null}
      </Typography.Text>
    </div>
  );
}
