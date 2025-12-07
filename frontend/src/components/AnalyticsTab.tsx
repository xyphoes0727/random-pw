import { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { Activity, AlertTriangle, CheckCircle, XCircle, Info } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { BASE_URL_HTTP, BASE_URL_WEBSOCKET } from "../config";
// Note: Import axios in your project
// import axios from "axios";

// CONFIG: Set to true to use API, false to use static data
const USE_API = true;

// Static data fallbacks
const staticFraudByPaymentData = [
  { type: "Credit Card", fraud_count: 234 },
  { type: "Debit Card", fraud_count: 187 },
  { type: "Bank Transfer", fraud_count: 89 },
  { type: "Digital Wallet", fraud_count: 156 },
];

const staticPartialDependenceData = Array.from({ length: 30 }, (_, i) => ({
  amount: i * 1000,
  fraud_probability: Math.min(0.9, 0.1 + (i / 30) * 0.7 + Math.random() * 0.1),
}));

const staticROCData = Array.from({ length: 20 }, (_, i) => ({
  fpr: i / 20,
  tpr: Math.min(1, (i / 20) + 0.3 + Math.random() * 0.1),
}));

const staticPRData = Array.from({ length: 20 }, (_, i) => ({
  recall: i / 20,
  precision: Math.max(0.5, 1 - (i / 30) + Math.random() * 0.1),
}));

const staticConfusionMatrix = {
  TP: 847,
  FP: 23,
  TN: 3285,
  FN: 45,
  Accuracy: 98.4,
  Precision: 97.4,
  Recall: 95.0,
  F1: 96.2,
};

interface MetricsData {
  CONFUSION_MATRIX: {
    TP: number;
    FP: number;
    TN: number;
    FN: number;
    ACCURACY: number;
    PRECISION: number;
    RECALL: number;
    F1: number;
  };
  ROC_CURVE: Array<{ tpr: number; fpr: number }>;
  PRECISION_RECALL: Array<{ precision: number; recall: number }>;
  FRAUD_COUNT_TYPE: Array<{ transaction_type: number; count: number }>;
  FRAUD_PROB_AMOUNT: Array<{ fraud_probability: number; amount: number }>;
}

// Helper function to format large numbers
const formatAmount = (value: number): string => {
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(1)}M`;
  } else if (value >= 1000) {
    return `${(value / 1000).toFixed(0)}K`;
  }
  return `${value.toFixed(0)}`;
};

// Helper function to generate logarithmic tick values for better distribution
const generateLogTicks = (min: number, max: number): number[] => {
  if (min <= 0) min = 1; // Ensure positive values for log
  
  const logMin = Math.log10(min);
  const logMax = Math.log10(max);
  const ticks: number[] = [];
  
  // Generate ticks at powers of 10 and their midpoints
  let currentLog = Math.floor(logMin);
  const maxLog = Math.ceil(logMax);
  
  while (currentLog <= maxLog) {
    const tickValue = Math.pow(10, currentLog);
    if (tickValue >= min && tickValue <= max) {
      ticks.push(tickValue);
    }
    
    // Add mid-point (e.g., 5K between 1K and 10K)
    const midValue = tickValue * 5;
    if (midValue >= min && midValue <= max && currentLog < maxLog) {
      ticks.push(midValue);
    }
    
    currentLog++;
  }
  
  // Ensure we have min and max
  if (ticks[0] !== min) ticks.unshift(min);
  if (ticks[ticks.length - 1] !== max) ticks.push(max);
  
  return ticks.sort((a, b) => a - b);
};

export function AnalyticsTab() {
  const [metricsData, setMetricsData] = useState<MetricsData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  
  // ML Health WebSocket state
  const [mlHealth, setMlHealth] = useState<{
    status: string;
    severity: number;
    explanation: string;
  } | null>(null);
  const [showHealthDialog, setShowHealthDialog] = useState(false);
  const wsHealthRef = useRef<WebSocket | null>(null);
  const reconnectHealthTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ML Health WebSocket connection
  useEffect(() => {
    const connectHealthWebSocket = () => {
      try {
        console.log('🏥 Connecting to ML Health WebSocket...');
        const ws = new WebSocket(`${BASE_URL_WEBSOCKET}/ws/ml_health`);
        wsHealthRef.current = ws;

        ws.onopen = () => {
          console.log('🏥 ML Health WebSocket connected');
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log('🏥 Received ML Health update:', response);

            if (response.result) {
              setMlHealth({
                status: response.result.status || 'unknown',
                severity: response.result.severity ?? 0.5,
                explanation: response.result.explanation || 'No explanation available',
              });
            }
          } catch (error) {
            console.error('Error parsing ML Health message:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('ML Health WebSocket error:', error);
        };

        ws.onclose = () => {
          console.log('🏥 ML Health WebSocket disconnected');
          wsHealthRef.current = null;

          reconnectHealthTimeoutRef.current = setTimeout(() => {
            console.log('🏥 Attempting to reconnect to ML Health WebSocket...');
            connectHealthWebSocket();
          }, 5000);
        };
      } catch (error) {
        console.error('Error creating ML Health WebSocket:', error);
      }
    };

    connectHealthWebSocket();

    return () => {
      if (reconnectHealthTimeoutRef.current) {
        clearTimeout(reconnectHealthTimeoutRef.current);
      }
      if (wsHealthRef.current) {
        wsHealthRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (USE_API) {
      fetchMetrics();
    }
  }, []);

  const fetchMetrics = async () => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem("access_token");
      
      // Replace with your axios implementation
      const response = await fetch(`${BASE_URL_HTTP}/api/metrics/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) throw new Error("Failed to fetch metrics");

      const data = await response.json();
      console.log("Fetched metrics data:", data);
      setMetricsData(data);
    } catch (error) {
      console.error("Error fetching metrics:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // Use API data if available, otherwise use static data
  const fraudByPaymentData = USE_API && metricsData 
    ? metricsData.FRAUD_COUNT_TYPE.map(item => ({
        type: `Type ${item.transaction_type}`,
        fraud_count: item.count
      }))
    : staticFraudByPaymentData;

  const partialDependenceData = USE_API && metricsData
    ? metricsData.FRAUD_PROB_AMOUNT
    : staticPartialDependenceData;

  // Calculate min and max amounts for proper axis scaling
  const minAmount = partialDependenceData.length > 0 
    ? partialDependenceData[0].amount 
    : 0;
  const maxAmount = partialDependenceData.length > 0 
    ? partialDependenceData[partialDependenceData.length - 1].amount 
    : 100000;

  // Generate logarithmic tick values for better visual distribution
  const amountTicks = generateLogTicks(minAmount, maxAmount);

  // ROC Curve: Sort by fpr ascending to avoid loops, start from (0,0)
  const rocData = USE_API && metricsData
    ? (() => {
        if (metricsData.ROC_CURVE.length === 0) {
          return [{ fpr: 0, tpr: 0 }, { fpr: 1, tpr: 1 }];
        }
        
        // Copy and sort by fpr ascending to ensure proper curve drawing
        const data = [...metricsData.ROC_CURVE].sort((a, b) => a.fpr - b.fpr);
        
        // Ensure starting point (0, 0) exists
        if (data.length === 0 || data[0].fpr !== 0 || data[0].tpr !== 0) {
          data.unshift({ fpr: 0, tpr: 0 });
        }
        
        return data;
      })()
    : staticROCData;

  // Precision-Recall Curve: Sort by recall ascending to avoid loops, start from (0, 1)
  const prData = USE_API && metricsData
    ? (() => {
        if (metricsData.PRECISION_RECALL.length === 0) {
          return [{ recall: 0, precision: 1 }, { recall: 1, precision: 0 }];
        }
        
        // Copy and sort by recall ascending to ensure proper curve drawing
        const data = [...metricsData.PRECISION_RECALL].sort((a, b) => a.recall - b.recall);
        
        // Ensure starting point (recall=0, precision=1) exists
        if (data.length === 0 || data[0].recall !== 0 || data[0].precision !== 1) {
          data.unshift({ recall: 0, precision: 1 });
        }
        
        return data;
      })()
    : staticPRData;

  const confusionMatrix = USE_API && metricsData
    ? {
        TP: metricsData.CONFUSION_MATRIX.TP,
        FP: metricsData.CONFUSION_MATRIX.FP,
        TN: metricsData.CONFUSION_MATRIX.TN,
        FN: metricsData.CONFUSION_MATRIX.FN,
        Accuracy: (metricsData.CONFUSION_MATRIX.ACCURACY * 100).toFixed(1),
        Precision: (metricsData.CONFUSION_MATRIX.PRECISION * 100).toFixed(1),
        Recall: (metricsData.CONFUSION_MATRIX.RECALL * 100).toFixed(1),
        F1: (metricsData.CONFUSION_MATRIX.F1 * 100).toFixed(1),
      }
    : staticConfusionMatrix;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading analytics data...</p>
      </div>
    );
  }

  // Get health status styling
  const getHealthColor = (status: string, severity: number) => {
    if (status === 'improved' || status === 'stable') {
      return 'bg-green-500/20 border-green-500 text-green-600';
    } else if (status === 'declined') {
      if (severity >= 0.5) {
        return 'bg-red-500/20 border-red-500 text-red-600';
      }
      return 'bg-orange-500/20 border-orange-500 text-orange-600';
    }
    return 'bg-blue-500/20 border-blue-500 text-blue-600';
  };

  const getHealthIcon = (status: string) => {
    switch (status) {
      case 'improved':
        return <CheckCircle className="h-4 w-4" />;
      case 'declined':
        return <AlertTriangle className="h-4 w-4" />;
      case 'stable':
        return <Activity className="h-4 w-4" />;
      default:
        return <Info className="h-4 w-4" />;
    }
  };

  return (
    <div className="space-y-8 p-6 bg-background">
      <div>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-foreground">Analytics & Model Performance</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Comprehensive fraud analytics and ML model evaluation metrics
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* ML Health Status */}
            {mlHealth && (
              <button
                onClick={() => setShowHealthDialog(true)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all hover:scale-105 cursor-pointer ${getHealthColor(mlHealth.status, mlHealth.severity)}`}
              >
                {getHealthIcon(mlHealth.status)}
                <span className="text-sm font-medium capitalize">{mlHealth.status}</span>
                <span className="text-xs opacity-70">({(mlHealth.severity * 100).toFixed(0)}%)</span>
              </button>
            )}
            <Badge variant="outline" className="text-sm">Model v2.3.1</Badge>
          </div>
        </div>

        {/* ML Health Dialog */}
        <Dialog open={showHealthDialog} onOpenChange={setShowHealthDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {mlHealth && getHealthIcon(mlHealth.status)}
                Model Health Status
              </DialogTitle>
              <DialogDescription>
                Current ML model performance status
              </DialogDescription>
            </DialogHeader>
            {mlHealth && (
              <div className="space-y-4">
                <div className="flex items-center gap-4">
                  <div className={`px-4 py-2 rounded-lg border ${getHealthColor(mlHealth.status, mlHealth.severity)}`}>
                    <span className="text-lg font-semibold capitalize">{mlHealth.status}</span>
                  </div>
                  <div className="flex-1">
                    <div className="text-sm text-muted-foreground">Severity Score</div>
                    <div className="text-2xl font-bold">{(mlHealth.severity * 100).toFixed(1)}%</div>
                  </div>
                </div>
                <div className="p-4 bg-muted/50 rounded-lg">
                  <div className="text-sm font-medium mb-2">Explanation</div>
                  <p className="text-sm text-muted-foreground">{mlHealth.explanation}</p>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>

        <div className="space-y-6">
          {/* Fraud Analytics Section */}
          <div className="grid gap-6 md:grid-cols-2">
            <Card className="p-6">
              <h3 className="mb-4 text-lg font-semibold text-foreground">
                Fraud by Payment Method
              </h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={fraudByPaymentData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="type" stroke="hsl(var(--muted-foreground))" />
                  <YAxis stroke="hsl(var(--muted-foreground))" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "8px",
                    }}
                  />
                  <Bar dataKey="fraud_count" fill="hsl(var(--chart-1))" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card className="p-3">
              <h3 className="mb-4 text-lg font-semibold text-foreground">
                Partial Dependence: Amount vs Fraud Probability
              </h3>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart
                  data={partialDependenceData}
                >
                  <defs>
                    <linearGradient id="partialGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--chart-3))" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="hsl(var(--chart-3))" stopOpacity={0} />
                    </linearGradient>
                  </defs>

                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />

                  <XAxis
                    dataKey="amount"
                    type="number"
                    scale="log"
                    domain={[minAmount, maxAmount]}
                    ticks={amountTicks}
                    tickFormatter={formatAmount}
                    stroke="hsl(var(--muted-foreground))"
                    label={{ value: "Transaction Amount ($)", position: "insideBottom", offset: -5 }}
                  />

                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(value) => `${(value * 100).toFixed(0)}%`}
                    stroke="hsl(var(--muted-foreground))"
                    label={{ value: "Fraud Probability", angle: -90, position: "insideLeft" }}

                  />

                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "8px",
                    }}
                    formatter={(value: any, name: string) => {
                      if (name === 'fraud_probability') {
                        return [(value * 100).toFixed(1) + '%', 'Fraud Probability'];
                      }
                      return [value, name];
                    }}
                    labelFormatter={(value) => `Amount: ${formatAmount(Number(value))}`}
                  />

                  <Area
                    type="monotone"
                    dataKey="fraud_probability"
                    stroke="hsl(var(--chart-3))"
                    fill="url(#partialGradient)"
                    strokeWidth={2}
                  />
                </AreaChart>

              </ResponsiveContainer>
            </Card>
          </div>

          {/* ML Model Performance Section */}
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
                  <div className="bg-green-500/20 border-2 border-green-500 p-4 rounded text-center">
                    <div className="text-2xl font-bold text-green-600">{confusionMatrix.TP}</div>
                    <div className="text-xs text-muted-foreground">True Positive</div>
                  </div>
                  <div className="bg-red-500/20 border-2 border-red-500/50 p-4 rounded text-center">
                    <div className="text-2xl font-bold text-red-600">{confusionMatrix.FN}</div>
                    <div className="text-xs text-muted-foreground">False Negative</div>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="text-xs font-medium text-muted-foreground flex items-center">Act: Legit</div>
                  <div className="bg-red-500/20 border-2 border-red-500/50 p-4 rounded text-center">
                    <div className="text-2xl font-bold text-red-600">{confusionMatrix.FP}</div>
                    <div className="text-xs text-muted-foreground">False Positive</div>
                  </div>
                  <div className="bg-green-500/20 border-2 border-green-500 p-4 rounded text-center">
                    <div className="text-2xl font-bold text-green-600">{confusionMatrix.TN}</div>
                    <div className="text-xs text-muted-foreground">True Negative</div>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-4 gap-4 pt-4 border-t">
                  <div>
                    <div className="text-xs text-muted-foreground">Accuracy</div>
                    <div className="text-lg font-bold">{confusionMatrix.Accuracy}%</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Precision</div>
                    <div className="text-lg font-bold">{confusionMatrix.Precision}%</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Recall</div>
                    <div className="text-lg font-bold">{confusionMatrix.Recall}%</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">F1 Score</div>
                    <div className="text-lg font-bold">{confusionMatrix.F1}%</div>
                  </div>
                </div>
              </div>
            </Card>

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
                  <XAxis 
                    dataKey="fpr" 
                    type="number"
                    domain={[0, 1]}
                    ticks={[0, 0.2, 0.4, 0.6, 0.8, 1.0]}
                    label={{ value: "False Positive Rate", position: "insideBottom", offset: -5 }} 
                    stroke="hsl(var(--muted-foreground))" 
                  />
                  <YAxis 
                    domain={[0, 1]}
                    label={{ value: "True Positive Rate", angle: -90, position: "insideLeft" }} 
                    stroke="hsl(var(--muted-foreground))" 
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                  {/* Reference line for random classifier (diagonal) */}
                  <ReferenceLine 
                    segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} 
                    stroke="hsl(var(--muted-foreground))" 
                    strokeDasharray="5 5"
                    strokeOpacity={0.5}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="tpr" 
                    stroke="hsl(var(--primary))" 
                    strokeWidth={3} 
                    fill="url(#rocGradient)" 
                    connectNulls={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Card>
          </div>

          {/* Precision-Recall Curve */}
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
                <XAxis 
                  dataKey="recall" 
                  type="number"
                  domain={[0, 1]}
                  ticks={[0, 0.2, 0.4, 0.6, 0.8, 1.0]}
                  label={{ value: "Recall", position: "insideBottom", offset: -5 }} 
                  stroke="hsl(var(--muted-foreground))" 
                />
                <YAxis 
                  type="number"
                  domain={[0, 1]}
                  ticks={[0, 0.2, 0.4, 0.6, 0.8, 1.0]}
                  label={{ value: "Precision", angle: -90, position: "insideLeft" }} 
                  stroke="hsl(var(--muted-foreground))" 
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "var(--radius)",
                  }}
                />
                <Area 
                  type="monotone" 
                  dataKey="precision" 
                  stroke="hsl(var(--chart-2))" 
                  strokeWidth={3} 
                  fill="url(#prGradient)" 
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        </div>
      </div>
    </div>
  );
}