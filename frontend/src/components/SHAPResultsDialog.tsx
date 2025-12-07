import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import axiosInstance from "@/lib/axios";
import { ExternalLink, Loader2 } from "lucide-react";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"

interface SHAPResultsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transactionId: string;
}

interface FeatureImportances {
  amount: number;
  oldbalanceOrg: number;
  newbalanceOrig: number;
  oldbalanceDest: number;
  newbalanceDest: number;
}

interface SHAPData {
  feature_importances: FeatureImportances;
  rca_report_link?: string;
}

export const SHAPResultsDialog = ({ open, onOpenChange, transactionId }: SHAPResultsDialogProps) => {
  const [shapData, setSHAPData] = useState<SHAPData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      fetchSHAPValues();
    }
  }, [open, transactionId]);

  const fetchSHAPValues = async () => {
    setLoading(true);
    try {
      const data={
        "transactionId": transactionId
      }
      const response = await axiosInstance.post(`${BASE_URL_HTTP}/api/shap/values/`,data);
      setSHAPData(response.data);
    } catch (error) {
      console.error("Error fetching SHAP values:", error);
    } finally {
      setLoading(false);
    }
  };

  const getFeatureImportanceData = () => {
    if (!shapData) return [];
    
    const importances = shapData.feature_importances;
    return Object.entries(importances)
      .map(([key, value]) => ({
        feature: key,
        importance: Math.abs(value),
        value: value,
      }))
      .sort((a, b) => b.importance - a.importance);
  };

  const getWaterfallData = () => {
    if (!shapData) return [];
    
    const importances = shapData.feature_importances;
    const sorted = Object.entries(importances)
      .map(([key, value]) => ({ feature: key, value }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

    let cumulative = 0;
    return sorted.map((item) => {
      const start = cumulative;
      cumulative += item.value;
      return {
        feature: item.feature,
        value: item.value,
        start: start,
        end: cumulative,
        color: item.value >= 0 ? "hsl(var(--chart-2))" : "hsl(var(--chart-1))",
      };
    });
  };

  const featureImportanceData = getFeatureImportanceData();
  const waterfallData = getWaterfallData();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>SHAP Feature Importance Analysis</DialogTitle>
          <DialogDescription>
            Transaction #{transactionId} - Understanding prediction factors
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="ml-3 text-muted-foreground">Loading SHAP results...</span>
          </div>
        ) : shapData ? (
          <div className="space-y-8 py-4">
            {/* Feature Importances Bar Chart */}
            {/* <div>
              <h3 className="text-lg font-semibold mb-4 text-foreground">Feature Importances</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart
                  data={featureImportanceData}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 100, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis type="number" stroke="hsl(var(--foreground))" />
                  <YAxis 
                    type="category" 
                    dataKey="feature" 
                    stroke="hsl(var(--foreground))"
                    width={90}
                  />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: "hsl(var(--background))", 
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "6px"
                    }}
                    formatter={(value: number) => value.toFixed(4)}
                  />
                  <Bar dataKey="importance" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div> */}

            {/* Waterfall Chart */}
            <div>
              <h3 className="text-lg font-semibold mb-4 text-foreground">SHAP Waterfall Chart</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart
                  data={waterfallData}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 100, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis type="number" stroke="hsl(var(--foreground))" />
                  <YAxis 
                    type="category" 
                    dataKey="feature" 
                    stroke="hsl(var(--foreground))"
                    width={90}
                  />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: "hsl(var(--background))", 
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "6px"
                    }}
                    formatter={(value: number, name: string) => {
                      if (name === "value") return [`${value.toFixed(4)} (${value >= 0 ? "+" : ""}${value.toFixed(4)})`, "Contribution"];
                      return value;
                    }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {waterfallData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="flex items-center gap-4 mt-4 text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 rounded" style={{ backgroundColor: "hsl(var(--chart-2))" }}></div>
                  <span className="text-muted-foreground">Positive Contribution</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 rounded" style={{ backgroundColor: "hsl(var(--chart-1))" }}></div>
                  <span className="text-muted-foreground">Negative Contribution</span>
                </div>
              </div>
            </div>

            {/* SHAP Report Link (Placeholder) */}
            {shapData.rca_report_link && (
              <div className="pt-4 border-t border-border">
                <Button
                  onClick={() => window.open(shapData.rca_report_link, "_blank")}
                  className="w-full"
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  View Detailed SHAP Report
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            No SHAP data available
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
