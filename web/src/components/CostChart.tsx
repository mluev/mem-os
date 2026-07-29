import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function CostChart({ data }: { data: Array<Record<string, string | number>> }) {
  const keys = Array.from(new Set(data.flatMap((item) => Object.keys(item)))).filter((key) => !["day", "total_usd"].includes(key));
  const colors = ["var(--chart-blue)", "var(--chart-violet)", "var(--chart-amber)", "var(--chart-green)"];
  return <div style={{ width: "100%", height: 260 }}>
    <ResponsiveContainer>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="day" tick={{ fontSize: 9, fill: "var(--muted)" }} tickLine={false} axisLine={false} tickFormatter={(value: string) => value.slice(5)} />
        <YAxis tick={{ fontSize: 9, fill: "var(--muted)" }} tickLine={false} axisLine={false} />
        <Tooltip contentStyle={{ background: "var(--floating)", border: "1px solid var(--line-strong)", borderRadius: 14, boxShadow: "var(--shadow-float)", fontSize: 11 }} />
        {keys.map((key, index) => <Bar key={key} dataKey={key} stackId="cost" fill={colors[index % colors.length]} radius={index === keys.length - 1 ? [5, 5, 0, 0] : 0} animationDuration={520} />)}
      </BarChart>
    </ResponsiveContainer>
  </div>;
}
