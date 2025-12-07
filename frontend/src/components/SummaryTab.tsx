// --- IMPORTS ---
import { useState, useEffect, useRef } from "react";
import { faro } from "@grafana/faro-web-sdk";
import { AlertTriangle, Shield, TrendingUp, ArrowRight, Activity } from "lucide-react";
import { useNavigate } from "react-router-dom";
import "axios";
import { MetricCard } from "./MetricCard";
import { Card } from "@/components/ui/card";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/contexts/AuthContext";
import axiosInstance from "@/lib/axios";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

interface SummaryTabProps {
  onNavigateToSystem: () => void;
}

interface RealtimeTransaction {
  transactionId: string;
  amount: number;
  fraud_probability: number;
  isFraud: number;
  fraud_label: string;
  time: number;
}

interface TransactionChartDataPoint {
  time: string;
  transactions: number;
  timestamp: number;
}

export const SummaryTab = ({ onNavigateToSystem }: SummaryTabProps) => {
  const { isAuthenticated } = useAuth();
  const [timeWindow, setTimeWindow] = useState("15m"); // Default to 15 minutes
  const [realtimeTransactions, setRealtimeTransactions] = useState<RealtimeTransaction[]>([]);
  const [isLoadingStorage, setIsLoadingStorage] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 30;
  const navigate = useNavigate();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [fraudNo, setFraudNo] = useState(0);
  const [protectedAmount, setProtectedAmount] = useState(0);
  const [totalTransactions, setTotalTransactions] = useState(0);
  const [suspectedTransactions, setSuspectedTransactions] = useState(0);
  const [transactionChartData, setTransactionChartData] = useState<TransactionChartDataPoint[]>([]);
  const [isLoadingChart, setIsLoadingChart] = useState(false);
  const wsTransactionTimeRef = useRef<WebSocket | null>(null);
  const reconnectTransactionTimeRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bucketMetadataRef = useRef<{
    bucketDuration: number; // Duration of each bucket in ms
    bucketCount: number; // Total number of buckets (180)
    lastBucketEndTime: number; // End time of the last bucket
  } | null>(null);
  const accumulatedDeltaRef = useRef<number>(0); // Accumulator for real-time deltas within current bucket

  const getStartTimeForWindow = (window: string): number => {
    const now = Date.now();

    switch (window) {
      case "15m":
        return now - 15 * 60 * 1000;
      case "30m":
        return now - 30 * 60 * 1000;
      case "1h":
        return now - 1 * 60 * 60 * 1000;
      case "6h":
        return now - 6 * 60 * 60 * 1000;
      case "12h":
        return now - 12 * 60 * 60 * 1000;
      case "24h":
        return now - 24 * 60 * 60 * 1000;
      default:
        return now - 1 * 60 * 60 * 1000;
    }
  };

  const formatTimeLabel = (timestamp: number, window: string, totalPoints: number): string => {
    const date = new Date(timestamp); // Timestamp is already in milliseconds
    
    switch (window) {
      case "15m":
      case "30m":
      case "1h":
        return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
      case "6h":
      case "12h":
      case "24h":
        return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
      default:
        return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
  };

  // Custom tick formatter to show only every Nth tick for cleaner X-axis based on time window
  const getXAxisInterval = (dataLength: number, window: string): number => {
    if (dataLength <= 10) return 0; // Show all if 10 or fewer points
    
    // Show approximately 6-8 ticks regardless of data length
    const targetTicks = 6;
    const interval = Math.ceil(dataLength / targetTicks);
    
    // Ensure we show first and last, with even spacing
    return interval > 1 ? interval : 1;
  };
const cleanupTransactionWS = () => {
    // Clear reconnection timeout first
    if (reconnectTransactionTimeRef.current) {
      clearTimeout(reconnectTransactionTimeRef.current);
      reconnectTransactionTimeRef.current = null;
    }
    
    console.log("Came for clean up");
    
    if (wsTransactionTimeRef.current) {
      console.log("🔌 Cleaning up existing TransactionTime WS");

      try {
        // Remove event listeners to prevent reconnection
        wsTransactionTimeRef.current.onclose = null;
        wsTransactionTimeRef.current.onerror = null;
        
        if (wsTransactionTimeRef.current.readyState === WebSocket.OPEN) {
          console.log("Sending backend to stop websocket");
          wsTransactionTimeRef.current.send(JSON.stringify({ action: "stop_stream" }));
        }
      } catch (err) {
        console.warn("Could not send stop_stream:", err);
      }

      wsTransactionTimeRef.current.close();
      wsTransactionTimeRef.current = null;
    }
  };

  const fetchTransactionData = async (window: string) => {
    if (!isAuthenticated) {
      setTransactionChartData([]);
      setIsLoadingChart(false);
      return;
    }

    setIsLoadingChart(true);
    try {
      const startTime = getStartTimeForWindow(window);
      const response = await axiosInstance.get(`/api/transactions?start_time=${startTime}`);

      const data = response.data;
      console.log('📊 Historical transaction data received:', data.length, 'buckets');
      
      if (data.length === 0) {
        setTransactionChartData([]);
        bucketMetadataRef.current = null;
        return;
      }
      
      // Calculate bucket metadata from actual data
      const firstBucketTime = data[0].time;
      const lastBucketTime = data[data.length - 1].time;
      const bucketDuration = data.length > 1 
        ? (lastBucketTime - firstBucketTime) / (data.length - 1) 
        : getStartTimeForWindow(window) / 180;
      
      // The last bucket ends at lastBucketTime + bucketDuration
      const lastBucketEndTime = lastBucketTime + bucketDuration;
      
      bucketMetadataRef.current = {
        bucketDuration,
        bucketCount: data.length,
        lastBucketEndTime
      };
      
      // Reset real-time delta accumulator
      accumulatedDeltaRef.current = 0;
      
      console.log('📦 Bucket metadata:', {
        bucketDuration: `${(bucketDuration / 1000).toFixed(1)}s`,
        bucketCount: data.length,
        firstBucket: new Date(firstBucketTime).toLocaleString(),
        lastBucket: new Date(lastBucketTime).toLocaleString(),
        lastBucketEndTime: new Date(lastBucketEndTime).toLocaleString()
      });
      
      // Transform API data to chart format
      const chartData = data.map((item: { time: number; count: number }, index: number) => ({
        time: formatTimeLabel(item.time, window, data.length),
        transactions: item.count,
        timestamp: item.time, // Keep original timestamp for bucket tracking
      }));

      console.log(`✅ Plotted ${chartData.length} data points on chart`);
      setTransactionChartData(chartData);
    } catch (error) {
      console.error("Error fetching transaction data:", error);
      setTransactionChartData([]);
    } finally {
      setIsLoadingChart(false);
    }
  };

  // Load transactions from sessionStorage on mount
  useEffect(() => {
    faro.api.pushLog(['Starting the Processes'], {
      context: {
        route: window.location.pathname,
        timestamp: Date.now().toString(),
      },
    });
    const existing = sessionStorage.getItem("startTime");
    faro.api.pushLog(['Getting the start time'], {
      context: {
        route: window.location.pathname,
        timestamp: Date.now().toString(),
      },
    });
    if (!existing) {
      const now = Date.now();
      sessionStorage.setItem("startTime", String(now));
      console.log("Session start time stored:", now);
    } else {
      console.log("Session start time already exists:", existing);
    }

    // Only load transactions from sessionStorage if authenticated
    faro.api.pushLog(['Loading transactions from session storage'], {
      context: {
        route: window.location.pathname,
        timestamp: Date.now().toString(),
      },
    });
    if (isAuthenticated) {
      try {
        const stored = sessionStorage.getItem("realtime-transactions");
        if (stored) {
          const parsedTransactions = JSON.parse(stored);
          setRealtimeTransactions(parsedTransactions);
        }
      } catch (error) {
        console.log('No stored transactions found or error parsing:', error);
      }
    }
    setIsLoadingStorage(false);
  }, [isAuthenticated]);

  // Fetch transaction data when time window changes or auth status changes
  faro.api.pushLog(['Receiving transactiosn in realtime'], {
      context: {
        route: window.location.pathname,
        timestamp: Date.now().toString(),
      },
    });
  useEffect(() => {
    fetchTransactionData(timeWindow);
  }, [timeWindow, isAuthenticated]);

 useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    // Clean up any existing connection before creating a new one
    cleanupTransactionWS();

    let isCurrentEffect = true; // Flag to track if this effect is still valid

    const connectTransactionTimeWebSocket = () => {
      // Don't connect if this effect has been cleaned up
      if (!isCurrentEffect) {
        console.log("Effect cleaned up, skipping connection");
        return;
      }

      try {
        const ws = new WebSocket(`${BASE_URL_WEBSOCKET}/ws/transaction_time`);
        wsTransactionTimeRef.current = ws;

        ws.onopen = () => {
            faro.api.pushLog(['Transaction Time Websocket connected'], {
          context: {
            route: window.location.pathname,
            timestamp: Date.now().toString(),
          },
        });
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log('🔔 Received transaction time update:', response);
              faro.api.pushLog(['Receiving transaction in realtime'], {
              context: {
                route: window.location.pathname,
                timestamp: Date.now().toString(),
              },
            });
            
            if (response.type === 'reatime_delta_data' && response.timestamp && response.delta !== undefined) {
              const realtimeTimestamp = response.timestamp;
              const newDelta = response.delta;

              setTransactionChartData(prevData => {
                if (prevData.length === 0 || !bucketMetadataRef.current) {
              faro.api.pushLog(['No previous data or bucket metadata, skipping update'], {
              context: {
                route: window.location.pathname,
                timestamp: Date.now().toString(),
              },
            });
                  return prevData;
                }

                const { bucketDuration, lastBucketEndTime } = bucketMetadataRef.current;
                const now = Date.now();
                
                const lastBucketTimestamp = prevData[prevData.length - 1]?.timestamp || 0;
                
                console.log('🔍 Bucket analysis:', {
                  now: new Date(now).toLocaleTimeString(),
                  realtimeTimestamp: new Date(realtimeTimestamp).toLocaleTimeString(),
                  lastBucketTimestamp: new Date(lastBucketTimestamp).toLocaleTimeString(),
                  lastBucketEndTime: new Date(lastBucketEndTime).toLocaleTimeString(),
                  bucketDurationSec: `${(bucketDuration / 1000).toFixed(1)}s`,
                  newDelta,
                  accumulatedDelta: accumulatedDeltaRef.current
                });
                
                if (now >= lastBucketEndTime) {
                  const bucketsPassed = Math.floor((now - lastBucketEndTime) / bucketDuration) + 1;
                  console.log(`🔄 Creating ${bucketsPassed} new bucket(s)`);
                  
                  const newBucketStartTime = lastBucketTimestamp + (bucketsPassed * bucketDuration);
                  
                  const newDataPoint: TransactionChartDataPoint = {
                    time: formatTimeLabel(newBucketStartTime, timeWindow, prevData.length + 1),
                    transactions: newDelta,
                    timestamp: newBucketStartTime
                  };
                  
                  accumulatedDeltaRef.current = newDelta;
                  
                  bucketMetadataRef.current = {
                    ...bucketMetadataRef.current,
                    lastBucketEndTime: newBucketStartTime + bucketDuration
                  };
                  
                  console.log('✨ New bucket created:', {
                    time: newDataPoint.time,
                    transactions: newDataPoint.transactions,
                    newLastBucketEndTime: new Date(newBucketStartTime + bucketDuration).toLocaleTimeString()
                  });
                    faro.api.pushLog("New bucket created", {
                    context: {
                      route: window.location.pathname,
                      timestamp: Date.now().toString(),
                    },
                  });
                  
                  
                  const cutoffTime = getStartTimeForWindow(timeWindow);
                  const updatedData = [...prevData, newDataPoint].filter(
                    item => item.timestamp >= cutoffTime
                  );
                  
                  const finalData = updatedData.slice(-180);
                  console.log(`📊 Total buckets after update: ${finalData.length}`);
                  return finalData;
                } else {
                  accumulatedDeltaRef.current += newDelta;
                  
                  const updatedData = [...prevData];
                  if (updatedData.length > 0) {
                    const lastIndex = updatedData.length - 1;
                    const previousValue = updatedData[lastIndex].transactions;
                    
                    updatedData[lastIndex] = {
                      ...updatedData[lastIndex],
                      transactions: previousValue + newDelta
                    };
                    
                
                    faro.api.pushLog(` Updated last bucket: ${previousValue} + ${newDelta} = ${updatedData[lastIndex].transactions} (accumulated: ${accumulatedDeltaRef.current})`, {
                    context: {
                      route: window.location.pathname,
                      timestamp: Date.now().toString(),
                    },
                  });
                  }
                  
                  return updatedData;
                }
              });
            }
          } catch (error) {
            console.error("Error parsing transaction time message:", error);
          }
        };

        ws.onerror = (error) => {
          console.error("Transaction time WebSocket error:", error);
        };

        ws.onclose = () => {
          console.log("Transaction time WebSocket disconnected");
          wsTransactionTimeRef.current = null;

          // Only reconnect if this effect is still valid and user is authenticated
          if (isCurrentEffect && isAuthenticated) {
            reconnectTransactionTimeRef.current = setTimeout(() => {
              console.log("Attempting to reconnect to transaction time WebSocket...");
              connectTransactionTimeWebSocket();
            }, 5000);
          }
        };
      } catch (error) {
        console.error("Error creating transaction time WebSocket:", error);
      }
    };

    connectTransactionTimeWebSocket();

    return () => {
      console.log("🧹 Cleaning up transaction time effect");
      isCurrentEffect = false; // Mark this effect as invalid
      cleanupTransactionWS();
    };
  }, [isAuthenticated, timeWindow]);
  // Save transactions to sessionStorage whenever they change
  useEffect(() => {
    if (!isLoadingStorage && realtimeTransactions.length > 0) {
      try {
        sessionStorage.setItem("realtime-transactions", JSON.stringify(realtimeTransactions));
      } catch (error) {
        console.error("Error saving transactions to localStorage:", error);
      }
    }
  }, [realtimeTransactions, isLoadingStorage]);

  // WebSocket connection for real-time transactions
  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    const connectWebSocket = () => {
      try {
        const token = localStorage.getItem("access_token");
        const ws = new WebSocket(`${BASE_URL_WEBSOCKET}/ws/kafka/?token=${token}`);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("Kafka WebSocket connected");
          ws.send(JSON.stringify({ action: "start_stream" }));
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log("Received transaction:", response);

            if (response.type === "ml_prediction" && response.data) {
              const newTransaction: RealtimeTransaction = {
                transactionId: response.data.transactionId,
                amount: response.data.amount,
                fraud_probability: response.data.fraud_probability,
                isFraud: response.data.isFraud,
                fraud_label: response.data.fraud_label,
                time: response.data.time,
              };

              setRealtimeTransactions(prev => [newTransaction, ...prev].slice(0, 100));
            }
          } catch (error) {
            console.error("Error parsing transaction message:", error);
          }
        };

        ws.onerror = (error) => {
          console.error("Kafka WebSocket error:", error);
        };

        ws.onclose = () => {
          console.log("Kafka WebSocket disconnected");
          wsRef.current = null;

          reconnectTimeoutRef.current = setTimeout(() => {
            console.log("Attempting to reconnect to Kafka...");
            connectWebSocket();
          }, 5000);
        };
      } catch (error) {
        console.error("Error creating Kafka WebSocket:", error);
      }
    };

    const getStaticParameter = async () => {
      if (!isAuthenticated) return;

      try {
        const token = localStorage.getItem("access_token");

        const response = await axiosInstance.get(`${BASE_URL_HTTP}/api/stats/`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });
        const data = response.data;
        console.log("Fetched static parameters:", data);
        setFraudNo(data.total_fraud_count);
        setProtectedAmount(data.protected_amount);
        setTotalTransactions(data.total_transactions);
        setSuspectedTransactions(data.total_suspected_count);
      } catch (error) {
        console.error("Error fetching static parameters:", error);
      }
    };

    connectWebSocket();
    getStaticParameter();
    console.log("Details:", fraudNo, protectedAmount, totalTransactions, suspectedTransactions);
    return () => {
      console.log("🔌 Cleaning up Kafka WebSocket...");
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        // Send stop_stream before closing
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ action: "stop_stream" }));
        }
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [isAuthenticated]);

  const formatTimestamp = (timestamp: number): string => {
    return new Date(timestamp).toLocaleString();
  };

  return (
    <div className="space-y-6">
      {/* Metric Cards */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Fraud Alerts"
          value={fraudNo.toLocaleString()}
          change="+23% from last week"
          icon={AlertTriangle}
          trend="up"
          variant="destructive"
        />
        <MetricCard
          title="Protected Amount"
          value={"$" + protectedAmount.toLocaleString()}
          change="+12% from last week"
          icon={Shield}
          trend="down"
          variant="success"
        />
        <MetricCard
          title="Transactions"
          value={totalTransactions.toString()}
          change="+8% from last week"
          icon={TrendingUp}
          trend="up"
          variant="default"
        />
        <MetricCard
          title="Suspected Transactions"
          value={suspectedTransactions.toString()}
          change="-5% from last week"
          icon={Activity}
          trend="down"
          variant="warning"
        />
      </div>

      {/* Transaction Chart */}
      <Card className="p-6">
        <div className="mb-6 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground">Total Transactions</h3>
          <Select value={timeWindow} onValueChange={setTimeWindow}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="15m">15 Minutes</SelectItem>
              <SelectItem value="30m">30 Minutes</SelectItem>
              <SelectItem value="1h">1 Hour</SelectItem>
              <SelectItem value="6h">6 Hours</SelectItem>
              <SelectItem value="12h">12 Hours</SelectItem>
              <SelectItem value="24h">24 Hours</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {isLoadingChart ? (
          <div className="h-[300px] flex items-center justify-center">
            <p className="text-sm text-muted-foreground">Loading chart data...</p>
          </div>
        ) : transactionChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={transactionChartData}>
              <defs>
                <linearGradient id="transactionGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis 
                dataKey="time" 
                stroke="hsl(var(--muted-foreground))"
                interval={getXAxisInterval(transactionChartData.length, timeWindow)}
                tick={{ fontSize: 11 }}
                tickFormatter={(value, index) => {
                  // Avoid duplicate labels by checking if this label was already shown
                  return value;
                }}
              />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  padding: "8px 12px",
                }}
                labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 500 }}
                itemStyle={{ color: "hsl(var(--primary))" }}
                formatter={(value: number) => [`Count : ${value} transactions`, '']}
                labelFormatter={(label) => `Time: ${label}`}
                cursor={{ stroke: 'hsl(var(--primary))', strokeWidth: 1 }}
              />
              <Area
                type="monotone"
                dataKey="transactions"
                stroke="hsl(var(--primary))"
                fill="url(#transactionGradient)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "hsl(var(--primary))" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[300px] flex items-center justify-center">
            <p className="text-sm text-muted-foreground">
              {!isAuthenticated ? "Please login to view transaction data" : "No transaction data available"}
            </p>
          </div>
        )}
      </Card>

      {/* Real-time Transactions */}
      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-foreground">Real-time Transactions</h3>
            <p className="text-sm text-muted-foreground mt-1">Live transaction stream with fraud detection</p>
          </div>
          <button
            onClick={() => navigate("/transaction-details")}
            className="flex items-center gap-2 text-sm font-medium text-primary hover:text-primary/80 transition-colors"
          >
            <span>Transaction Details</span>
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>

      {!isAuthenticated ? (
          <div className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              Please login to view real-time transactions
            </p>
          </div>
        ) : realtimeTransactions.length > 0 ? (
          <>
            <div className="overflow-x-auto max-h-[500px] overflow-y-auto scrollbar-thin scrollbar-thumb-primary/20 scrollbar-track-transparent hover:scrollbar-thumb-primary/40">
              <table className="w-full">
                <thead className="sticky top-0 bg-card z-10">
              <tr className="border-b border-border">
                    <th className="text-left py-3 px-4 text-sm font-semibold text-foreground">Transaction ID</th>
                    <th className="text-left py-3 px-4 text-sm font-semibold text-foreground">Amount</th>
                    <th className="text-left py-3 px-4 text-sm font-semibold text-foreground">Fraud Probability</th>
                    <th className="text-left py-3 px-4 text-sm font-semibold text-foreground">Label</th>
                    <th className="text-left py-3 px-4 text-sm font-semibold text-foreground">Status</th>
                    <th className="text-left py-3 px-4 text-sm font-semibold text-foreground">Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {realtimeTransactions
                    .slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
                    .map((transaction, index) => {
                      // Determine status label based on fraud classification
                      const getStatusLabel = () => {
                        if (transaction.isFraud === 1 && transaction.fraud_probability >= 0.4) {
                          // High confidence fraud = Blocked
                          return { label: "Blocked", className: "bg-red-900 text-white" };
                        } else if (transaction.isFraud === 1 && transaction.fraud_probability < 0.4) {
                          // Low confidence fraud = Suspected (darker)
                          return { label: "Suspected", className: "bg-orange-600 text-white" };
                        } else if (transaction.isFraud === 0 && transaction.fraud_probability < 0.4) {
                          // Uncertain legitimate = Suspected (lighter)
                          return { label: "Suspected", className: "bg-orange-400 text-white" };
                        }
                        return null; // High confidence legitimate - no label
                      };
                      const statusLabel = getStatusLabel();
                      
                      return (
                        <tr
                          key={`${transaction.transactionId}-${index}`}
                          className="border-b border-border last:border-0 hover:bg-muted/50 transition-colors cursor-pointer"
                          onClick={() => navigate(`/transaction-details?id=${transaction.transactionId}`)}
                        >
                          <td className="py-3 px-4 text-sm text-foreground font-mono">{transaction.transactionId}</td>
                          <td className="py-3 px-4 text-sm text-foreground">${transaction.amount.toFixed(2)}</td>
                          <td className="py-3 px-4 text-sm">
                            <Badge
                              variant={
                                transaction.fraud_probability > 0.7
                                  ? "destructive"
                                  : transaction.fraud_probability > 0.4
                                    ? "secondary"
                                    : "default"
                              }
                            >
                              {(transaction.fraud_probability * 100).toFixed(1)}%
                            </Badge>
                          </td>
                          <td className="py-3 px-4 text-sm">
                            <Badge variant={transaction.fraud_label === "fraudulent" ? "destructive" : "default"}>
                              {transaction.fraud_label}
                            </Badge>
                          </td>
                          <td className="py-3 px-4 text-sm">
                            {statusLabel ? (
                              <Badge className={statusLabel.className}>
                                {statusLabel.label}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-sm text-muted-foreground">{formatTimestamp(transaction.time)}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
            {Math.ceil(realtimeTransactions.length / itemsPerPage) > 1 && (
              <Pagination className="mt-4">
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        if (currentPage > 1) setCurrentPage(currentPage - 1);
                      }}
                    />
                  </PaginationItem>
                  {[...Array(Math.min(Math.ceil(realtimeTransactions.length / itemsPerPage), 5))].map((_, i) => {
                    const pageNum = i + 1;
                    return (
                      <PaginationItem key={pageNum}>
                        <PaginationLink
                          href="#"
                          onClick={(e) => {
                            e.preventDefault();
                            setCurrentPage(pageNum);
                          }}
                          isActive={currentPage === pageNum}
                        >
                          {pageNum}
                        </PaginationLink>
                      </PaginationItem>
                    );
                  })}
                  {Math.ceil(realtimeTransactions.length / itemsPerPage) > 5 && <PaginationEllipsis />}
                  <PaginationItem>
                    <PaginationNext
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        if (currentPage < Math.ceil(realtimeTransactions.length / itemsPerPage))
                          setCurrentPage(currentPage + 1);
                      }}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            )}
          </>
        ) : (
          <div className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              {isLoadingStorage
                ? "Loading transactions..."
                : "Waiting for real-time transactions..."}
            </p>
          </div>
        )}
      </Card>
    </div>
  );
};
