import { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AlertCircle, CheckCircle2, AlertTriangle, Info, Search, X } from "lucide-react";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

interface WebVitals {
  ttfb: number;
  fcp: number;
  lcp: number;
  cls: number;
  inp: number;
}

interface PagePerformance {
  page_id: string;
  avg_ttfb: number;
  avg_fcp: number;
  avg_lcp: number;
  avg_cls: number;
  avg_inp: number;
  error_count: number;
}

interface ApiLatency {
  endpoint: string;
  calls: number;
  p50: number;
  p90: number;
  p99: number;
}

interface LogEntry {
  timestamp: string;
  route: string;
  level: string;
  message: string;
}

interface ObservabilityData {
  overall_web_vitals: WebVitals;
  page_performance: PagePerformance[];
  api_latency: ApiLatency[];
  logs: LogEntry[];
}

const getVitalStatus = (
  metric: string,
  value: number,
): { status: "good" | "needs-improvement" | "poor"; color: string } => {
  const thresholds: Record<string, { good: number; poor: number }> = {
    ttfb: { good: 800, poor: 1800 },
    fcp: { good: 1800, poor: 3000 },
    lcp: { good: 2500, poor: 4000 },
    cls: { good: 0.1, poor: 0.25 },
    inp: { good: 200, poor: 500 },
  };

  const threshold = thresholds[metric];
  if (!threshold) return { status: "good", color: "text-success" };

  if (value <= threshold.good) {
    return { status: "good", color: "text-success" };
  } else if (value <= threshold.poor) {
    return { status: "needs-improvement", color: "text-warning" };
  } else {
    return { status: "poor", color: "text-destructive" };
  }
};

const VitalCard = ({
  title,
  subtitle,
  value,
  unit,
  metric,
}: {
  title: string;
  subtitle: string;
  value: number;
  unit: string;
  metric: string;
}) => {
  const { status, color } = getVitalStatus(metric, value);
  const thresholds: Record<string, { good: number; poor: number }> = {
    ttfb: { good: 800, poor: 1800 },
    fcp: { good: 1800, poor: 3000 },
    lcp: { good: 2500, poor: 4000 },
    cls: { good: 0.1, poor: 0.25 },
    inp: { good: 200, poor: 500 },
  };
  const threshold = thresholds[metric];
  const min = 0;
  const max = threshold.poor * 1.5;
  const position = Math.min((value / max) * 100, 100);

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="text-sm font-medium text-foreground">{title}</h4>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <Info className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mb-3">
        <div className="flex items-baseline gap-1">
          <span className={`text-2xl font-bold ${color}`}>{value.toFixed(metric === "cls" ? 2 : 0)}</span>
          <span className="text-sm text-muted-foreground">{unit}</span>
        </div>
        <p className={`text-xs ${color} capitalize`}>({status.replace("-", " ")})</p>
      </div>
      <div className="relative h-2 bg-muted rounded-full overflow-hidden">
        <div
          className="absolute left-0 top-0 h-full bg-gradient-to-r from-success via-warning to-destructive"
          style={{ width: "100%" }}
        />
        <div className="absolute top-0 h-full w-1 bg-foreground" style={{ left: `${position}%` }} />
      </div>
      <div className="flex justify-between text-xs text-muted-foreground mt-1">
        <span>
          {min}
          {unit}
        </span>
        <span>
          {threshold.good}
          {unit}
        </span>
        <span>
          {max.toFixed(0)}
          {unit}
        </span>
      </div>
    </Card>
  );
};

export default function ObservabilityTab() {
  const [data, setData] = useState<ObservabilityData | null>(null);
  const [currentPagePerf, setCurrentPagePerf] = useState(1);
  const [currentApiPage, setCurrentApiPage] = useState(1);
  const [currentLogsPage, setCurrentLogsPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const itemsPerPage = 30;
  
  const getStartTimeEpochNano = (): number => {
    const now = Date.now(); // ms
    const oneDayAgoMs = now - 24 * 60 * 60 * 1000; // 1 day in ms
    const oneHourAgoMs = now - 60 * 60 * 1000; // 1 hour in ms
    const sessionStart = parseInt(sessionStorage.getItem("startTime")); // in ms
    let actualStartTimeMs;

    // CASE 1: sessionStorage has a timestamp
    if (sessionStart) {
      // If it is newer than 1 day ago → cap to 1 day
      if (sessionStart > oneDayAgoMs) {
        actualStartTimeMs = sessionStart;
      } else {
        actualStartTimeMs = oneDayAgoMs; // cap at 1 day
      }

    } else {
      // CASE 2: No sessionStorage timestamp → use 1 hour ago
      actualStartTimeMs = oneHourAgoMs;
    }
    const actualStartTimeNs=actualStartTimeMs*1000000
    console.log("Actual start time (ns):", actualStartTimeNs);
    return actualStartTimeNs;
    
  };

  useEffect(() => {
    const connectWebSocket = () => {
      try {
        const ws = new WebSocket(`${BASE_URL_WEBSOCKET}/ws/logs/`);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("Observability WebSocket connected");
          ws.send(
            JSON.stringify({
              service_name: "fraud_detection_frontend",
              start: getStartTimeEpochNano(),
            }),
          );
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log("Received observability data:", response);

            if (
              response.type === "log_data" &&
              response.mode === "static" &&
              response.service === "fraud_detection_frontend"
            ) {
              setData(response.data);
            }
          } catch (error) {
            console.error("Error parsing observability message:", error);
          }
        };

        ws.onerror = (error) => {
          console.error("Observability WebSocket error:", error);
        };

        ws.onclose = () => {
          console.log("Observability WebSocket disconnected");
          wsRef.current = null;
        };
      } catch (error) {
        console.error("Error creating observability WebSocket:", error);
      }
    };

    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const paginatedPagePerf =
    data?.page_performance.slice((currentPagePerf - 1) * itemsPerPage, currentPagePerf * itemsPerPage) || [];

  const paginatedApiLatency =
    data?.api_latency.slice((currentApiPage - 1) * itemsPerPage, currentApiPage * itemsPerPage) || [];

  const filteredLogs =
    data?.logs.filter((log) => {
      if (!searchQuery) return true;
      const query = searchQuery.toLowerCase();
      return (
        log.timestamp.toLowerCase().includes(query) ||
        log.route.toLowerCase().includes(query) ||
        log.level.toLowerCase().includes(query) ||
        log.message.toLowerCase().includes(query)
      );
    }) || [];

  const paginatedLogs = filteredLogs.slice((currentLogsPage - 1) * itemsPerPage, currentLogsPage * itemsPerPage);

  const totalPagePerfPages = Math.ceil((data?.page_performance.length || 0) / itemsPerPage);
  const totalApiPages = Math.ceil((data?.api_latency.length || 0) / itemsPerPage);
  const totalLogsPages = Math.ceil(filteredLogs.length / itemsPerPage);

  const renderPagination = (currentPage: number, totalPages: number, onPageChange: (page: number) => void) => {
    if (totalPages <= 1) return null;

    return (
      <Pagination className="mt-4">
        <PaginationContent>
          <PaginationItem>
            <PaginationPrevious
              href="#"
              onClick={(e) => {
                e.preventDefault();
                if (currentPage > 1) onPageChange(currentPage - 1);
              }}
            />
          </PaginationItem>
          {(() => {
            let startPage = Math.max(1, currentPage - 2);
            let endPage = Math.min(totalPages, startPage + 4);
            
            if (endPage - startPage < 4) {
              startPage = Math.max(1, endPage - 4);
            }
            
            return [...Array(endPage - startPage + 1)].map((_, i) => {
              const pageNum = startPage + i;
            return (
              <PaginationItem key={pageNum}>
                <PaginationLink
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    onPageChange(pageNum);
                  }}
                  isActive={currentPage === pageNum}
                >
                  {pageNum}
                </PaginationLink>
              </PaginationItem>
            );
            });
          })()}
          {totalPages > 5 && <PaginationEllipsis />}
          <PaginationItem>
            <PaginationNext
              href="#"
              onClick={(e) => {
                e.preventDefault();
                if (currentPage < totalPages) onPageChange(currentPage + 1);
              }}
            />
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    );
  };

  const getLogIcon = (level: string) => {
    switch (level.toLowerCase()) {
      case "error":
        return <AlertCircle className="h-4 w-4 text-destructive" />;
      case "warning":
      case "warn":
        return <AlertTriangle className="h-4 w-4 text-warning" />;
      case "info":
        return <CheckCircle2 className="h-4 w-4 text-success" />;
      default:
        return <Info className="h-4 w-4 text-muted-foreground" />;
    }
  };

  if (!data) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading observability data...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Web Vitals */}
      <div>
        <h3 className="text-lg font-semibold mb-4">Web Vitals</h3>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          <VitalCard
            title="TTFB"
            subtitle="Time to First Byte"
            value={data.overall_web_vitals.ttfb}
            unit="ms"
            metric="ttfb"
          />
          <VitalCard
            title="FCP"
            subtitle="First Contentful Paint"
            value={data.overall_web_vitals.fcp}
            unit="ms"
            metric="fcp"
          />
          <VitalCard
            title="LCP"
            subtitle="Largest Contentful Paint"
            value={data.overall_web_vitals.lcp}
            unit="ms"
            metric="lcp"
          />
          <VitalCard
            title="CLS"
            subtitle="Cumulative Layout Shift"
            value={data.overall_web_vitals.cls}
            unit=""
            metric="cls"
          />
          <VitalCard
            title="INP"
            subtitle="Interaction to Next Paint"
            value={data.overall_web_vitals.inp}
            unit="ms"
            metric="inp"
          />
        </div>
      </div>

      {/* Page Performance */}
      <Card className="p-6">
        <h3 className="text-lg font-semibold mb-4">Page Performance</h3>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Page ID</TableHead>
                <TableHead className="text-right">TTFB</TableHead>
                <TableHead className="text-right">FCP</TableHead>
                <TableHead className="text-right">LCP</TableHead>
                <TableHead className="text-right">CLS</TableHead>
                <TableHead className="text-right">INP</TableHead>
                <TableHead className="text-right">Errors</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedPagePerf.map((page, index) => (
                <TableRow key={index}>
                  <TableCell className="font-mono">{page.page_id}</TableCell>
                  <TableCell className="text-right">{page.avg_ttfb.toFixed(0)} ms</TableCell>
                  <TableCell className="text-right">{page.avg_fcp.toFixed(0)} ms</TableCell>
                  <TableCell className="text-right">
                    {page.avg_lcp === 0 ? "-" : `${page.avg_lcp.toFixed(0)} ms`}
                  </TableCell>
                  <TableCell className="text-right">{page.avg_cls.toFixed(3)}</TableCell>
                  <TableCell className="text-right">
                    {page.avg_inp === 0 ? "-" : `${page.avg_inp.toFixed(0)} ms`}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant={page.error_count > 0 ? "destructive" : "secondary"}>{page.error_count}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {renderPagination(currentPagePerf, totalPagePerfPages, setCurrentPagePerf)}
      </Card>

      {/* API Latency */}
      <Card className="p-6">
        <h3 className="text-lg font-semibold mb-4">Frontend API Latency</h3>
        <div className="space-y-4">
          {paginatedApiLatency.map((api, index) => (
            <div key={index} className="p-4 bg-muted/30 rounded-lg">
              <div className="flex justify-between items-start mb-2">
                <div className="font-mono text-sm font-semibold">{api.endpoint}</div>
                <div className="text-sm text-muted-foreground">{api.calls} calls</div>
              </div>
              <div className="flex justify-end gap-4 text-sm">
                <span className="text-muted-foreground">
                  p50: <span className="text-foreground font-medium">{api.p50} ms</span>
                </span>
                <span className="text-muted-foreground">
                  p90: <span className="text-foreground font-medium">{api.p90} ms</span>
                </span>
                <span className="text-muted-foreground">
                  p99: <span className="text-foreground font-medium">{api.p99} ms</span>
                </span>
              </div>
            </div>
          ))}
        </div>
        {renderPagination(currentApiPage, totalApiPages, setCurrentApiPage)}
      </Card>

      {/* Logs */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Logs</h3>
          <div className="relative w-64">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search logs..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentLogsPage(1);
              }}
              className="pl-10 pr-10"
            />
            {searchQuery && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-2 top-1/2 transform -translate-y-1/2 h-6 w-6"
                onClick={() => {
                  setSearchQuery("");
                  setCurrentLogsPage(1);
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
        <div className="overflow-x-auto">
          <Table className="w-full">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[200px]">Timestamp</TableHead>
                <TableHead className="w-[120px]">Route</TableHead>
                <TableHead className="w-[150px]">Level</TableHead>
                <TableHead>Message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedLogs.length > 0 ? (
                paginatedLogs.map((log, index) => (
                  <TableRow key={index}>
                    <TableCell className="font-mono text-xs whitespace-nowrap">
                      <span dangerouslySetInnerHTML={{ 
                        __html: searchQuery ? log.timestamp.replace(
                          new RegExp(`(${searchQuery})`, 'gi'),
                          '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                        ) : log.timestamp
                      }} />
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      <span dangerouslySetInnerHTML={{ 
                        __html: searchQuery ? log.route.replace(
                          new RegExp(`(${searchQuery})`, 'gi'),
                          '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                        ) : log.route
                      }} />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {getLogIcon(log.level)}
                        <span className="text-sm capitalize">
                          <span dangerouslySetInnerHTML={{ 
                            __html: searchQuery ? log.level.replace(
                              new RegExp(`(${searchQuery})`, 'gi'),
                              '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                            ) : log.level
                          }} />
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">
                      <span dangerouslySetInnerHTML={{ 
                        __html: searchQuery ? log.message.replace(
                          new RegExp(`(${searchQuery})`, 'gi'),
                          '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                        ) : log.message
                      }} />
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                    {searchQuery ? "No logs match your search." : "No logs available."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        {renderPagination(currentLogsPage, totalLogsPages, setCurrentLogsPage)}
      </Card>
    </div>
  );
}
