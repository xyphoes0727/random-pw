import { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";

interface MetricCardProps {
  title: string;
  value: string;
  change: string;
  icon: LucideIcon;
  trend: "up" | "down";
  variant?: "default" | "destructive" | "warning" | "success";
}

export const MetricCard = ({ title, value, change, icon: Icon, trend, variant = "default" }: MetricCardProps) => {
  const variantStyles = {
    default: "bg-primary/10 text-primary",
    destructive: "bg-destructive/10 text-destructive",
    warning: "bg-warning/10 text-warning",
    success: "bg-success/10 text-success",
  };

  const trendColor = trend === "up" ? "text-destructive" : "text-success";
    // --- Number formatter (K, M, B) ---
  const formatNumber = (value: number | string) => {
    // Remove $, commas, whitespace → keep only digits and decimal
    const clean = String(value).replace(/[^0-9.-]+/g, "");

    const n = Number(clean);
    if (isNaN(n)) return value;

    if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + "B";
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(2) + "K";

    return n.toLocaleString();
  };
  return (
    <Card className="p-6 transition-all hover:shadow-lg hover:shadow-primary/5">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="text-3xl font-bold text-foreground">
            {title === "Protected Amount" ? "$" : ""}
            {formatNumber(value)}
          </p>          
          {/* <p className={`text-sm font-medium ${trendColor}`}>{change}</p> */}
        </div>
        <div className={`rounded-lg p-3 ${variantStyles[variant]}`}>
          <Icon className="h-6 w-6" />
        </div>
      </div>
    </Card>
  );
};
