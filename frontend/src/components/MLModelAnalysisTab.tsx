import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"

// ML Analysis Data
const confusionMatrixData = [
  { predicted: "Fraud", actual: "Fraud", value: 847, color: "hsl(var(--success))" },
  { predicted: "Fraud", actual: "Legitimate", value: 23, color: "hsl(var(--destructive-light))" },
  { predicted: "Legitimate", actual: "Fraud", value: 45, color: "hsl(var(--destructive-light))" },
  { predicted: "Legitimate", actual: "Legitimate", value: 3285, color: "hsl(var(--success))" },
];

const rocData = Array.from({ length: 20 }, (_, i) => ({
  fpr: i / 20,
  tpr: Math.min(1, (i / 20) + 0.3 + Math.random() * 0.1),
}));

const prData = Array.from({ length: 20 }, (_, i) => ({
  recall: i / 20,
  precision: Math.max(0.5, 1 - (i / 30) + Math.random() * 0.1),
}));

const calibrationData = Array.from({ length: 10 }, (_, i) => ({
  predicted: (i + 1) / 10,
  actual: (i + 1) / 10 + (Math.random() - 0.5) * 0.1,
}));

const driftMetrics = {
  psi: 0.087,
  jsDivergence: 0.042,
  status: "stable",
};

export const MLModelAnalysisTab = () => {
  return (
    <div className="space-y-8">
      <div>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-foreground">ML Model Analysis</h2>
            <p className="text-sm text-muted-foreground mt-1">Comprehensive model performance and quality metrics</p>
          </div>
          <Badge variant="outline" className="text-sm">Model v2.3.1</Badge>
        </div>

        <div className="space-y-6">
          {/* Confusion Matrix & Performance */}
          <div className="grid gap-6 md:grid-cols-2">
            <Card className="p-6">
              <h3 className="mb-4 text-lg font-semibold text-foreground">Confusion Matrix</h3>
              <div className="space-y-2">
                <div className="grid grid-cols-3 gap-2 text-xs font-medium text-muted-foreground">
                  <div></div>
                  <div className="text-center">Pred: Fraud</div>
                  <div className="text-center">Pred: Legit</div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="text-xs font-medium text-muted-foreground flex items-center">Act: Fraud</div>
                  <div className="bg-success/20 border-2 border-success p-4 rounded text-center">
                    <div className="text-2xl font-bold text-success">847</div>
                    <div className="text-xs text-muted-foreground">True Positive</div>
                  </div>
                  <div className="bg-destructive/20 border-2 border-destructive/50 p-4 rounded text-center">
                    <div className="text-2xl font-bold text-destructive">45</div>
                    <div className="text-xs text-muted-foreground">False Negative</div>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="text-xs font-medium text-muted-foreground flex items-center">Act: Legit</div>
                  <div className="bg-destructive/20 border-2 border-destructive/50 p-4 rounded text-center">
                    <div className="text-2xl font-bold text-destructive">23</div>
                    <div className="text-xs text-muted-foreground">False Positive</div>
                  </div>
                  <div className="bg-success/20 border-2 border-success p-4 rounded text-center">
                    <div className="text-2xl font-bold text-success">3285</div>
                    <div className="text-xs text-muted-foreground">True Negative</div>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-4 pt-4 border-t">
                  <div>
                    <div className="text-xs text-muted-foreground">Accuracy</div>
                    <div className="text-lg font-bold">98.4%</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Precision</div>
                    <div className="text-lg font-bold">97.4%</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Recall</div>
                    <div className="text-lg font-bold">95.0%</div>
                  </div>
                </div>
              </div>
            </Card>

            <Card className="p-6">
              <h3 className="mb-4 text-lg font-semibold text-foreground">Data & Concept Drift</h3>
              <div className="space-y-6">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium">Population Stability Index (PSI)</span>
                    <Badge variant={driftMetrics.psi < 0.1 ? "default" : driftMetrics.psi < 0.2 ? "secondary" : "destructive"}>
                      {driftMetrics.status}
                    </Badge>
                  </div>
                  <div className="flex items-end gap-2">
                    <div className="text-3xl font-bold">{driftMetrics.psi.toFixed(3)}</div>
                    <div className="text-sm text-muted-foreground mb-1">(&lt; 0.1 stable)</div>
                  </div>
                  <div className="mt-2 h-2 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-success" style={{ width: `${Math.min(100, (1 - driftMetrics.psi / 0.25) * 100)}%` }}></div>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium">JS Divergence</span>
                    <Badge variant={driftMetrics.jsDivergence < 0.05 ? "default" : "secondary"}>
                      Low
                    </Badge>
                  </div>
                  <div className="flex items-end gap-2">
                    <div className="text-3xl font-bold">{driftMetrics.jsDivergence.toFixed(3)}</div>
                    <div className="text-sm text-muted-foreground mb-1">(&lt; 0.05 stable)</div>
                  </div>
                  <div className="mt-2 h-2 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-success" style={{ width: `${Math.min(100, (1 - driftMetrics.jsDivergence / 0.1) * 100)}%` }}></div>
                  </div>
                </div>

                <div className="pt-4 border-t">
                  <div className="text-xs text-muted-foreground mb-2">Drift Status</div>
                  <div className="text-sm">No significant drift detected. Model performance remains stable across recent data distributions.</div>
                </div>
              </div>
            </Card>
          </div>

          {/* ROC & PR Curves */}
          <div className="grid gap-6 md:grid-cols-2">
            <Card className="p-6">
              <h3 className="mb-4 text-lg font-semibold text-foreground">ROC Curve</h3>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={rocData}>
                  <defs>
                    <linearGradient id="rocGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis dataKey="fpr" label={{ value: "False Positive Rate", position: "insideBottom", offset: -5 }} stroke="hsl(var(--muted-foreground))" />
                  <YAxis label={{ value: "True Positive Rate", angle: -90, position: "insideLeft" }} stroke="hsl(var(--muted-foreground))" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                  <ReferenceLine stroke="hsl(var(--muted-foreground))" strokeDasharray="5 5" segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} />
                  <Area type="monotone" dataKey="tpr" stroke="hsl(var(--primary))" strokeWidth={3} fill="url(#rocGradient)" />
                </AreaChart>
              </ResponsiveContainer>
              <div className="mt-2 text-center">
                <span className="text-sm text-muted-foreground">AUC-ROC: </span>
                <span className="text-lg font-bold text-success">0.967</span>
              </div>
            </Card>

            <Card className="p-6">
              <h3 className="mb-4 text-lg font-semibold text-foreground">Precision-Recall Curve</h3>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={prData}>
                  <defs>
                    <linearGradient id="prGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--chart-2))" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="hsl(var(--chart-2))" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis dataKey="recall" label={{ value: "Recall", position: "insideBottom", offset: -5 }} stroke="hsl(var(--muted-foreground))" />
                  <YAxis label={{ value: "Precision", angle: -90, position: "insideLeft" }} stroke="hsl(var(--muted-foreground))" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                  <Area type="monotone" dataKey="precision" stroke="hsl(var(--chart-2))" strokeWidth={3} fill="url(#prGradient)" />
                </AreaChart>
              </ResponsiveContainer>
              <div className="mt-2 text-center">
                <span className="text-sm text-muted-foreground">AUC-PR: </span>
                <span className="text-lg font-bold text-success">0.953</span>
              </div>
            </Card>
          </div>

          {/* Calibration Curve */}
          <Card className="p-6">
            <h3 className="mb-4 text-lg font-semibold text-foreground">Calibration Curve</h3>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={calibrationData}>
                <defs>
                  <linearGradient id="calibrationGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                <XAxis 
                  dataKey="predicted" 
                  label={{ value: "Predicted Probability", position: "insideBottom", offset: -5 }} 
                  stroke="hsl(var(--muted-foreground))"
                  tickFormatter={(value) => value.toFixed(1)}
                />
                <YAxis 
                  label={{ value: "Actual Fraction of Positives", angle: -90, position: "insideLeft" }} 
                  stroke="hsl(var(--muted-foreground))"
                  tickFormatter={(value) => value.toFixed(1)}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "var(--radius)",
                  }}
                  formatter={(value: any) => value.toFixed(3)}
                />
                <ReferenceLine stroke="hsl(var(--muted-foreground))" strokeDasharray="5 5" segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} />
                <Area type="monotone" dataKey="actual" stroke="hsl(var(--primary))" strokeWidth={3} fill="url(#calibrationGradient)" dot={{ r: 4 }} name="Model" />
              </AreaChart>
            </ResponsiveContainer>
            <div className="mt-2 text-center text-sm text-muted-foreground">
              Model predictions are well-calibrated (close to diagonal reference line)
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
