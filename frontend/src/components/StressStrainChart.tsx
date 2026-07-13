import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CurvePoint } from "../types";

interface Props {
  points: CurvePoint[];
  height?: number;
}

export function StressStrainChart({ points, height = 360 }: Props) {
  if (!points.length) {
    return <div style={{ padding: 24, textAlign: "center", color: "#999" }}>暂无曲线数据</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={points} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="engineering_strain"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
          label={{ value: "工程应变", position: "insideBottom", offset: -4 }}
        />
        <YAxis
          dataKey="engineering_stress_MPa"
          label={{ value: "应力 (MPa)", angle: -90, position: "insideLeft" }}
        />
        <Tooltip
          formatter={(value: number) => [`${value.toFixed(3)} MPa`, "应力"]}
          labelFormatter={(label) => `应变 ${(Number(label) * 100).toFixed(2)}%`}
        />
        <Legend />
        <Line
          type="monotone"
          dataKey="engineering_stress_MPa"
          name="工程应力"
          stroke="#1677ff"
          dot={false}
          strokeWidth={2}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
