import { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Filter, ChevronDown, ChevronRight } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useToast } from "@/hooks/use-toast";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"

interface MetricDataPoint {
  timestamp: string;
  value: number;
}

interface MetricState {
  data: MetricDataPoint[];
  isSubscribed: boolean;
  unsubscribeTimer?: ReturnType<typeof setTimeout>;
}

// Service configuration: displayName -> backendName
const serviceConfig = {
  "Pathway": "pathway",
  "Django Backend": "fraud-ingest-api"
};

const services = Object.keys(serviceConfig);

// Metrics by service
const metricsByService: Record<string, Array<{ id: string; label: string }>> = {
  "Pathway": [
    { id: "process_cpu_stime_seconds", label: "CPU STime (s)" },
    { id: "process_memory_usage_byte", label: "Memory Usage (bytes)" },
    { id: "process_cpu_utime_seconds", label: "CPU UTime (s)" },
    { id: "latency_input_milliseconds", label: "Latency Input (ms)" },
    { id: "latency_output_milliseconds", label: "Latency Output (ms)" }
  ],
  "Django Backend": [
    { id: "http_server_active_requests", label: "Active HTTP Requests" },
    { id: "asyncio_process_created_total", label: "Asyncio Processes Created (Total)" },
    { id: "asyncio_process_duration_seconds_count", label: "Asyncio Process Duration (Count)" },
    { id: "http_server_duration_milliseconds_count", label: "HTTP Duration (Count)" },
    { id: "http_server_duration_milliseconds_sum", label: "HTTP Duration Sum (ms)" }
  ]
};

const UNSUBSCRIBE_DELAY = 30000; // 30 seconds - wait before unsubscribing when metric is deselected

export function MetricsTab() {
  const { toast } = useToast();
  const [selectedService, setSelectedService] = useState(services[0]); // Display name
  const [selectedMetrics, setSelectedMetrics] = useState<Record<string, boolean>>({});
  const [timeMode, setTimeMode] = useState("timestamp");
  const [timeRange, setTimeRange] = useState("30min");
  const [metricsData, setMetricsData] = useState<Record<string, MetricState>>({});
  const [servicesOpen, setServicesOpen] = useState(true);
  const [timeModeOpen, setTimeModeOpen] = useState(true);
  const [wsReady, setWsReady] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timeModeRef = useRef(timeMode); // Keep track of current mode
  const prevServiceRef = useRef(selectedService);
  const prevTimeRangeRef = useRef(timeRange);

  // Helper function to get backend name from display name
  const getBackendName = (displayName: string): string => {
    return serviceConfig[displayName as keyof typeof serviceConfig] || displayName;
  };

  // Helper function to get display name from backend name
  const getDisplayName = (backendName: string): string => {
    const entry = Object.entries(serviceConfig).find(([_, value]) => value === backendName);
    return entry ? entry[0] : backendName;
  };
  
  // Update refs when values change
  useEffect(() => {
    timeModeRef.current = timeMode;
  }, [timeMode]);

  // Initialize selected metrics when service changes
  useEffect(() => {
    const availableMetrics = metricsByService[selectedService] || [];
    const initialMetrics: Record<string, boolean> = {};
    availableMetrics.forEach(metric => {
      initialMetrics[metric.id] = true;
    });
    setSelectedMetrics(initialMetrics);
  }, [selectedService]);

  // Format timestamp to readable format
  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  };

  // Calculate start time based on selected time range
  const getStartTimeEpochNano = (): number => {
    const now = new Date();
    const minutes = parseInt(timeRange.replace('min', ''));
    const startTime = new Date(now.getTime() - minutes * 60 * 1000);
    return startTime.getTime() / 1000; // Convert to seconds
  };

  // Format large numbers
  const formatValue = (value: number, metricId: string): string => {
    if (metricId === 'process_memory_usage_byte') {
      return (value / 1000000000).toFixed(2) + ' GB';
    } else if (metricId.includes('milliseconds')) {
      return value.toFixed(2) + ' ms';
    } else if (metricId.includes('seconds')) {
      return value.toFixed(2) + ' s';
    } else if (metricId === 'http_server_active_requests') {
      return Math.round(value).toString();
    } else if (metricId.includes('_total') || metricId.includes('_count')) {
      return Math.round(value).toString();
    }
    return value.toFixed(2);
  };

  // WebSocket connection
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        const ws = new WebSocket(`${BASE_URL_WEBSOCKET}/telemetry/ws/metrics`);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log('Metrics WebSocket connected');
          setWsReady(true);
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log('Received metric message:', response);

            if (response.type === 'metric' && response.mode === 'realtime') {
              // Realtime data format - only update if currently in realtime mode
              if (timeModeRef.current === 'realtime') {
                const metricId = response.metric;
                response.data.forEach((dataPoint: any) => {
                  const newPoint: MetricDataPoint = {
                    timestamp: dataPoint.timestamp,
                    value: dataPoint.value
                  };

                  setMetricsData(prev => {
                    const currentMetric = prev[metricId] || { data: [], isSubscribed: true };
                    const updatedData = [...currentMetric.data, newPoint]
                      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
                      .slice(-100); // Keep last 100 points
                    console.log(`Updating ${metricId} with new data point:`, newPoint);
                    return {
                      ...prev,
                      [metricId]: {
                        ...currentMetric,
                        data: updatedData,
                        isSubscribed: true
                      }
                    };
                  });
                });
              } else {
                console.log('Ignoring realtime data while in static mode');
              }
            } else if (response.type === 'metric_data' && response.mode === 'static') {
              // Static data format - flatten nested structure
              const metricId = response.metric;
              const dataPoints: MetricDataPoint[] = [];
              
              response.data.forEach((serviceData: any) => {
                if (serviceData.values && Array.isArray(serviceData.values)) {
                  serviceData.values.forEach((item: any) => {
                    dataPoints.push({
                      timestamp: item.timestamp,
                      value: item.value
                    });
                  });
                }
              });

              // Sort data points by timestamp to ensure chronological order
              dataPoints.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

              setMetricsData(prev => ({
                ...prev,
                [metricId]: {
                  data: dataPoints,
                  isSubscribed: false
                }
              }));
            }
          } catch (error) {
            console.error('Error parsing metric message:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('Metrics WebSocket error:', error);
          toast({
            title: "Connection Error",
            description: "Failed to connect to metrics service",
            variant: "destructive"
          });
        };

        ws.onclose = () => {
          console.log('Metrics WebSocket disconnected');
          wsRef.current = null;
          setWsReady(false);
          
          // Attempt reconnection after 5 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Attempting to reconnect metrics...');
            connectWebSocket();
          }, 5000);
        };
      } catch (error) {
        console.error('Error creating metrics WebSocket:', error);
      }
    };

    connectWebSocket();

    return () => {
      console.log('🔌 Cleaning up Metrics WebSocket...');
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      // Unsubscribe from all metrics before closing
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        Object.keys(metricsData).forEach(metricId => {
          if (metricsData[metricId].isSubscribed) {
            wsRef.current?.send(JSON.stringify({
              action: 'unsubscribe',
              metric: metricId
            }));
          }
        });
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  // Handle metric selection changes - also handles initial fetch after service change populates selectedMetrics
  useEffect(() => {
    if (!wsReady || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.log('WebSocket not ready, waiting...');
      return;
    }
    
    // Skip if no metrics selected yet
    const hasSelectedMetrics = Object.values(selectedMetrics).some(v => v);
    if (!hasSelectedMetrics) {
      console.log('No metrics selected yet, waiting...');
      return;
    }

    const backendName = getBackendName(selectedService);
    console.log('📊 Metric selection effect triggered, fetching for:', backendName);

    Object.entries(selectedMetrics).forEach(([metricId, isSelected]) => {
      const currentState = metricsData[metricId];

      if (isSelected) {
        // Clear any pending unsubscribe timer
        if (currentState?.unsubscribeTimer) {
          clearTimeout(currentState.unsubscribeTimer);
        }

        // Subscribe or fetch if not already subscribed and no data exists
        if (!currentState?.isSubscribed && (!currentState?.data || currentState.data.length === 0)) {
          if (timeMode === 'realtime') {
            const message = {
              action: 'subscribe',
              service_name: backendName,
              metric: metricId
            };
            console.log('Subscribing to metric:', message);
            wsRef.current.send(JSON.stringify(message));
            
            setMetricsData(prev => ({
              ...prev,
              [metricId]: {
                ...(prev[metricId] || { data: [] }),
                isSubscribed: true
              }
            }));
          } else {
            const message = {
              action: 'fetch_static',
              service_name: backendName,
              metric: metricId,
              start: getStartTimeEpochNano()
            };
            console.log('Fetching static metric data:', message);
            wsRef.current.send(JSON.stringify(message));
          }
        }
      } else if (currentState?.isSubscribed) {
        // Schedule unsubscribe after delay
        const timer = setTimeout(() => {
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            const message = {
              action: 'unsubscribe',
              metric: metricId
            };
            console.log('Unsubscribing from metric:', message);
            wsRef.current.send(JSON.stringify(message));
            
            setMetricsData(prev => ({
              ...prev,
              [metricId]: {
                ...prev[metricId],
                isSubscribed: false
              }
            }));
          }
        }, UNSUBSCRIBE_DELAY);

        setMetricsData(prev => ({
          ...prev,
          [metricId]: {
            ...prev[metricId],
            unsubscribeTimer: timer
          }
        }));
      }
    });
  }, [selectedMetrics, timeMode, wsReady]);

  // Handle service, time range, or time mode changes
  useEffect(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    // Determine what changed
    const serviceChanged = prevServiceRef.current !== selectedService;
    const timeRangeChanged = prevTimeRangeRef.current !== timeRange;
    const switchedToStatic = timeMode === 'timestamp';
    
    // Update refs
    prevServiceRef.current = selectedService;
    prevTimeRangeRef.current = timeRange;

    // Unsubscribe from all current subscriptions first
    Object.entries(metricsData).forEach(([metricId, state]) => {
      if (state.isSubscribed) {
        wsRef.current?.send(JSON.stringify({
          action: 'unsubscribe',
          metric: metricId
        }));
      }
    });

    // Clear data when: switching to static, changing service, or changing time range
    // Preserve data when: switching from static to realtime (to continue from where it left off)
    const shouldClearData = switchedToStatic || serviceChanged || timeRangeChanged;
    
    if (shouldClearData) {
      setMetricsData({});
    }

    // Small delay to ensure unsubscribe is processed
    setTimeout(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      const backendName = getBackendName(selectedService);

      Object.entries(selectedMetrics).forEach(([metricId, isSelected]) => {
        if (isSelected) {
          if (timeMode === 'realtime') {
            const message = {
              action: 'subscribe',
              service_name: backendName,
              metric: metricId
            };
            console.log('Subscribing to metric:', message);
            wsRef.current?.send(JSON.stringify(message));
            
            // Mark as subscribed, preserve existing data if switching from static to realtime
            setMetricsData(prev => ({
              ...prev,
              [metricId]: {
                data: prev[metricId]?.data || [], // Keep existing data when switching to realtime
                isSubscribed: true
              }
            }));
          } else {
            const message = {
              action: 'fetch_static',
              service_name: backendName,
              metric: metricId,
              start: getStartTimeEpochNano()
            };
            console.log('Fetching static metric data:', message);
            wsRef.current?.send(JSON.stringify(message));
          }
        }
      });
    }, 100);
  }, [selectedService, timeRange, timeMode]);

  const getLatestValue = (metricId: string): string => {
    const data = metricsData[metricId]?.data;
    if (!data || data.length === 0) return 'No data';
    return formatValue(data[data.length - 1].value, metricId);
  };

  const getMinValue = (data: MetricDataPoint[]): number => {
    if (data.length === 0) return 0;
    return Math.min(...data.map(d => d.value));
  };

  const getMaxValue = (data: MetricDataPoint[]): number => {
    if (data.length === 0) return 0;
    return Math.max(...data.map(d => d.value));
  };

  return (
    <div className="flex gap-4 h-full">
      {/* Left Sidebar - Filters */}
      <Card className="w-64 p-3 flex-shrink-0 overflow-y-auto self-stretch">
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-6">
            <Filter className="h-4 w-4" />
            <h3 className="font-semibold">Filters</h3>
          </div>

          {/* Time Mode Filter */}
          <Collapsible open={timeModeOpen} onOpenChange={setTimeModeOpen}>
            <CollapsibleTrigger className="flex items-center justify-between w-full py-2">
              <span className="text-sm font-medium">Time Mode</span>
              {timeModeOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2 space-y-2">
              <Select value={timeMode} onValueChange={setTimeMode}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="realtime">Real-time</SelectItem>
                  <SelectItem value="timestamp">Static (Time Range)</SelectItem>
                </SelectContent>
              </Select>
              
              {timeMode === "timestamp" && (
                <Select value={timeRange} onValueChange={setTimeRange}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="15min">Last 15 Minutes</SelectItem>
                    <SelectItem value="30min">Last 30 Minutes</SelectItem>
                    <SelectItem value="60min">Last 1 Hour</SelectItem>
                    <SelectItem value="180min">Last 3 Hours</SelectItem>
                    <SelectItem value="360min">Last 6 Hours</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </CollapsibleContent>
          </Collapsible>

          {/* Services Filter */}
          <Collapsible open={servicesOpen} onOpenChange={setServicesOpen}>
            <CollapsibleTrigger className="flex items-center justify-between w-full py-2">
              <span className="text-sm font-medium">Services</span>
              {servicesOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <Select value={selectedService} onValueChange={setSelectedService}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {services.map((service) => (
                    <SelectItem key={service} value={service}>
                      {service}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CollapsibleContent>
          </Collapsible>

        </div>
      </Card>

      {/* Main Content - Metrics Grid */}
      <div className="flex-1 overflow-auto">
        <div className="mb-4">
          <h2 className="text-xl font-bold text-foreground">System Metrics</h2>
          <p className="text-sm text-muted-foreground">
            {timeMode === 'realtime' ? 'Real-time' : 'Historical'} performance metrics for {selectedService}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(metricsByService[selectedService] || []).map((metric) => {
            const data = metricsData[metric.id]?.data || [];
            const hasData = data.length > 0;

            return (
              <Card key={metric.id} className="p-4">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">{metric.label}</h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      {hasData ? `Latest: ${getLatestValue(metric.id)}` : 'Waiting for data...'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {metricsData[metric.id]?.isSubscribed && (
                      <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                    )}
                  </div>
                </div>

                {hasData ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={data}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                      <XAxis 
                        dataKey="timestamp" 
                        stroke="hsl(var(--muted-foreground))"
                        fontSize={10}
                        tickFormatter={formatTimestamp}
                        tick={{ fill: 'hsl(var(--muted-foreground))' }}
                      />
                      <YAxis 
                        stroke="hsl(var(--muted-foreground))"
                        fontSize={10}
                        domain={[
                          (dataMin: number) => Math.floor(getMinValue(data) * 0.95),
                          (dataMax: number) => Math.ceil(getMaxValue(data) * 1.05)
                        ]}
                        tick={{ fill: 'hsl(var(--muted-foreground))' }}
                      />
                      <Tooltip 
                        contentStyle={{
                          backgroundColor: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: '6px',
                          fontSize: '12px'
                        }}
                        labelFormatter={(label) => new Date(label).toLocaleString()}
                        formatter={(value: number) => [formatValue(value, metric.id), metric.label]}
                      />
                      <Line 
                        type="monotone" 
                        dataKey="value" 
                        stroke={
                          metric.id.includes('latency') || metric.id.includes('http') ? '#ef4444' :
                          metric.id.includes('cpu') || metric.id.includes('asyncio') ? '#f59e0b' :
                          '#3b82f6'
                        }
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 4 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-[200px] flex items-center justify-center border-2 border-dashed border-border rounded-lg">
                    <p className="text-sm text-muted-foreground">No data available</p>
                  </div>
                )}
              </Card>
            );
          })}
        </div>

      </div>
    </div>
  );
}