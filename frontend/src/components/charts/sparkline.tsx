"use client";

import { Area, AreaChart, Bar, BarChart, ResponsiveContainer } from "recharts";

export function Sparkline({
  data,
  color,
  variant = "area",
}: {
  data: number[];
  color: string;
  variant?: "area" | "bar";
}) {
  const points = data.map((v, i) => ({ i, v }));
  if (points.length < 2) return <div className="h-9" aria-hidden />;

  return (
    <div className="h-9 w-full" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        {variant === "bar" ? (
          <BarChart data={points} margin={{ top: 6, right: 0, left: 0, bottom: 0 }}>
            <Bar dataKey="v" fill={color} radius={[2, 2, 0, 0]} maxBarSize={8} />
          </BarChart>
        ) : (
          <AreaChart data={points} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <Area type="monotone" dataKey="v" stroke={color} fill={color} fillOpacity={0.14} strokeWidth={1.6} dot={false} />
          </AreaChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
