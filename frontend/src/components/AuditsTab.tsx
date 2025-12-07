import { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Filter, Search, RefreshCw, ChevronDown, ChevronRight, X, AlertTriangle, Bell, Trash2 } from "lucide-react";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { BASE_URL_HTTP, BASE_URL_WEBSOCKET } from "../config";
import { useAlerts } from "@/contexts/AlertContext";

interface LogEntry {
  id: string;
  timestamp: string;
  timestampFormatted: string;
  serviceName: string;
  logLevel: string;
  log: string;
  isError: boolean;
}

// Service mapping: display name -> actual backend name
const serviceMapping: Record<string, string> = {
  "Pathway": "pathway",
  "Django Backend": "fraud-ingest-api",
  "Neo4j": "neo4j",
  "ML Engine": "ml-engine",
};

// Get display names for dropdown
const services = Object.keys(serviceMapping);

// Reverse mapping for displaying backend service names
const reverseServiceMapping: Record<string, string> = Object.entries(serviceMapping).reduce(
  (acc, [display, backend]) => {
    acc[backend] = display;
    return acc;
  },
  {} as Record<string, string>
);

export default function AuditsTab() {
  const { alerts, markAllAsRead, clearAlerts } = useAlerts();
  const [selectedService, setSelectedService] = useState(services[0]);
  const [isLive, setIsLive] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [servicesOpen, setServicesOpen] = useState(true);
  const [alertsOpen, setAlertsOpen] = useState(true);
  const [timeMode, setTimeMode] = useState("timestamp");
  const [timeRange, setTimeRange] = useState("30min");
  const [expandedLog, setExpandedLog] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const itemsPerPage = 50;
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Mark alerts as read when the audits tab is viewed
  useEffect(() => {
    markAllAsRead();
  }, [markAllAsRead]);

  // Convert nanosecond timestamp to readable format
  const formatTimestamp = (timestamp: string | number): string => {
    let date: Date;
    
    if (typeof timestamp === 'string' && timestamp.includes('T')) {
      // ISO format: "2025-11-08T16:22:20.558786"
      date = new Date(timestamp);
    } else {
      // Nanosecond timestamp: "1762640887075222272"
      const nanoseconds = typeof timestamp === 'string' ? parseInt(timestamp) : timestamp;
      const milliseconds = nanoseconds / 1000000;
      date = new Date(milliseconds);
    }
    
    return date.toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).toUpperCase();
  };

  // Calculate start time based on selected time range
  const getStartTimeEpochNano = (): number => {
    const now = new Date();
    const minutes = parseInt(timeRange.replace('min', ''));
    const startTime = new Date(now.getTime() - minutes * 60 * 1000);
    return startTime.getTime()*1000000
  };


  // WebSocket connection
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        const ws = new WebSocket(`${BASE_URL_WEBSOCKET}/telemetry/ws/logs/`);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log('WebSocket connected');
          // Send initial message based on mode
          const actualServiceName = serviceMapping[selectedService];
          console.log("service and actual 1:",selectedService,actualServiceName)
          const message = timeMode === 'realtime' 
            ? { service_name: actualServiceName }
            : { service_name: actualServiceName, start: getStartTimeEpochNano() };
          
          console.log('Sending initial message:', message);
          ws.send(JSON.stringify(message));
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log('Received message:', response);

            if (response.type === 'log_data') {
              const newLogs: LogEntry[] = [];

              if (response.mode === 'static') {
                response.data.forEach((serviceData: any) => {
                  serviceData.values.forEach((logEntry: any, index: number) => {
                    // Convert backend service name to display name
                    const displayName = reverseServiceMapping[serviceData.service_name] || serviceData.service_name;
                    console.log("Display Name 1",displayName)
                    newLogs.push({
                      id: `${serviceData.service_name}-${logEntry.timestamp}-${index}`,
                      timestamp: logEntry.timestamp, // raw
                      timestampFormatted: formatTimestamp(logEntry.timestamp),
                      serviceName: displayName,
                      logLevel: logEntry.severity_text,
                      log: logEntry.log,
                      isError: logEntry.severity_text === 'ERROR'
                    });
                  });
                });
                setLogs(newLogs);
              } else if (response.mode === 'realtime') {
                response.data.forEach((streamData: any) => {
                  streamData.values.forEach((valueArray: [string, string], index: number) => {
                    const [timestamp, logText] = valueArray;
                    // Convert backend service name to display name
                    const displayName = reverseServiceMapping[streamData.stream.service_name] || streamData.stream.service_name;
                    console.log("Display Name 1",displayName)

                    newLogs.push({
                      id: `${streamData.stream.service_name}-${timestamp}-${index}`,
                      timestamp: timestamp,  // raw epoch string
                      timestampFormatted: formatTimestamp(timestamp),
                      serviceName: displayName,
                      logLevel: 'INFO',
                      log: logText,
                      isError: false
                    });
                  });
                });
                setLogs(prev => {
                  const merged = [...newLogs, ...prev];

                  merged.sort((a, b) => {
                    const t1 = Number(a.timestamp);
                    const t2 = Number(b.timestamp);
                    return t2 - t1; // DESCENDING: newest first
                  });

                  return merged.slice(0, 100); // keep last 300 logs
                });

              }
            }
          } catch (error) {
            console.error('Error parsing message:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
        };

        ws.onclose = () => {
          console.log('WebSocket disconnected');
          wsRef.current = null;
          
          // Attempt reconnection after 5 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Attempting to reconnect...');
            connectWebSocket();
          }, 5000);
        };
      } catch (error) {
        console.error('Error creating WebSocket:', error);
      }
    };

    connectWebSocket();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Send message when service or time mode changes
  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const actualServiceName = serviceMapping[selectedService];
      console.log("service and actual :",selectedService,actualServiceName)

      const message = timeMode === 'realtime' 
        ? { service_name: actualServiceName }
        : { service_name: actualServiceName, start: getStartTimeEpochNano() };
      
      console.log('Sending filter change message:', message);
      wsRef.current.send(JSON.stringify(message));
      setIsLive(timeMode === 'realtime');
    }
  }, [selectedService, timeMode, timeRange]);

  const getStatusBadge = (logLevel: string) => {
    switch (logLevel.toUpperCase()) {
      case "INFO":
        return <Badge className="bg-success text-success-foreground">INFO</Badge>;
      case "ERROR":
        return <Badge variant="destructive">ERROR</Badge>;
      case "WARNING":
      case "WARN":
        return <Badge className="bg-warning text-warning-foreground">WARNING</Badge>;
      default:
        return <Badge variant="secondary">{logLevel}</Badge>;
    }
  };

  const getStatusColor = (logLevel: string) => {
    const level = logLevel.toUpperCase();
    if (level === "INFO") return "text-success";
    if (level === "WARNING" || level === "WARN") return "text-warning";
    if (level === "ERROR") return "text-destructive";
    return "text-foreground";
  };

  // Format alert timestamp
  const formatAlertTimestamp = (timestamp: number) => {
    return new Date(timestamp).toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });
  };

  return (
    <div className="flex gap-4 h-screen p-4">
      {/* Left Sidebar - Filters */}
      <Card className="w-64 p-3 flex-shrink-0 overflow-y-auto">
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-6">
            <Filter className="h-4 w-4" />
            <h3 className="font-semibold">Filters</h3>
          </div>

          {/* Time Mode Filter */}
          <Collapsible open={timelineOpen} onOpenChange={setTimelineOpen}>
            <CollapsibleTrigger className="flex items-center justify-between w-full py-2">
              <span className="text-sm font-medium">Time Mode</span>
              {timelineOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
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

      {/* Main Content */}
      <div className="flex-1 flex flex-col gap-3 overflow-hidden min-w-0">
        {/* System Alerts Section */}
        {alerts.length > 0 && (
          <Collapsible open={alertsOpen} onOpenChange={setAlertsOpen} className="flex-shrink-0">
            <Card className="p-3">
              <CollapsibleTrigger className="flex items-center justify-between w-full">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-destructive" />
                  <h3 className="font-semibold text-sm">System Alerts ({alerts.length})</h3>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      clearAlerts();
                    }}
                    className="h-7 text-xs"
                  >
                    <Trash2 className="h-3 w-3 mr-1" />
                    Clear
                  </Button>
                  {alertsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </div>
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-3">
                <div className="max-h-48 overflow-auto space-y-2">
                  {alerts.map((alert) => (
                    <div
                      key={alert.id}
                      className="p-3 bg-destructive/10 border border-destructive/30 rounded-lg"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge variant="destructive" className="text-xs">
                              {alert.category}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {formatAlertTimestamp(alert.timestamp)}
                            </span>
                          </div>
                          <p className="text-sm font-medium text-foreground mb-1 line-clamp-2">
                            {alert.summary}
                          </p>
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {alert.cause}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CollapsibleContent>
            </Card>
          </Collapsible>
        )}
        {/* Search and Controls */}
        <div className="flex items-center gap-3 bg-card/50 backdrop-blur border border-border rounded-lg p-2 flex-shrink-0">
          <div className="relative flex-1 min-w-0">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input 
              placeholder="Search logs..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              className="pl-10 bg-background/50 border-0 focus-visible:ring-1"
            />
            {searchQuery && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-2 top-1/2 transform -translate-y-1/2 h-6 w-6"
                onClick={() => {
                  setSearchQuery("");
                  setCurrentPage(1);
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
          <Button
            variant={isLive ? "ghost" : "outline"}
            size="sm"
            onClick={() => {
              if (timeMode === 'realtime') {
                setTimeMode('timestamp');
              } else {
                setTimeMode('realtime');
              }
            }}
            className="gap-2 flex-shrink-0"
          >
            <div className={`h-2 w-2 rounded-full ${isLive ? 'bg-success animate-pulse' : 'bg-muted-foreground'}`} />
            {isLive ? 'Live' : 'Static'}
          </Button>
          <Button 
            variant="outline" 
            size="icon" 
            className="h-9 w-9 flex-shrink-0"
            onClick={() => {
              if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                const actualServiceName = serviceMapping[selectedService];
                console.log("service and actual :",selectedService,actualServiceName)
                const message = timeMode === 'realtime' 
                  ? { service_name: actualServiceName }
                  : { service_name: actualServiceName, start: getStartTimeEpochNano() };
                wsRef.current.send(JSON.stringify(message));
              }
            }}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>

        {/* Logs Section */}
        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          <div className="mb-3 flex-shrink-0">
            <h2 className="text-xl font-bold text-foreground">Audit Logs</h2>
            <p className="text-sm text-muted-foreground">Real-time transaction monitoring and activity tracking</p>
          </div>
          <div className="flex-1 overflow-auto bg-card rounded-lg border border-border min-h-0 [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-track]:bg-muted/20 [&::-webkit-scrollbar-thumb]:bg-muted-foreground/30 [&::-webkit-scrollbar-thumb]:rounded-full hover:[&::-webkit-scrollbar-thumb]:bg-muted-foreground/50">
            <Table>
              <TableHeader className="sticky top-0 bg-card z-10">
                <TableRow className="border-b border-border/50 hover:bg-transparent">
                  <TableHead className="h-8 text-xs py-2">Timestamp</TableHead>
                  <TableHead className="h-8 text-xs py-2">Service Name</TableHead>
                  <TableHead className="h-8 text-xs py-2">Log Level</TableHead>
                  <TableHead className="h-8 text-xs py-2">Log</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs
                  .filter(log => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      log.timestampFormatted.toLowerCase().includes(query) ||
                      log.serviceName.toLowerCase().includes(query) ||
                      log.logLevel.toLowerCase().includes(query) ||
                      log.log.toLowerCase().includes(query)
                    );
                  })
                  .slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
                  .map((log, index) => (
                  <TableRow 
                    key={log.id} 
                    className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                    style={{
                      animation: log.isError 
                        ? `slideInFlashError 1s ease-out ${Math.min(index * 0.05, 1)}s both`
                        : `slideInFlashSuccess 1s ease-out ${Math.min(index * 0.05, 1)}s both`
                    }}
                    onClick={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                  >
                    <TableCell className="text-muted-foreground whitespace-nowrap py-2 text-xs font-mono">
                      <span dangerouslySetInnerHTML={{ 
                        __html: log.timestampFormatted.replace(
                          new RegExp(`(${searchQuery})`, 'gi'),
                          '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                        )
                      }} />
                    </TableCell>
                    <TableCell className="py-2 text-xs font-medium whitespace-nowrap">
                      <span dangerouslySetInnerHTML={{ 
                        __html: log.serviceName.replace(
                          new RegExp(`(${searchQuery})`, 'gi'),
                          '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                        )
                      }} />
                    </TableCell>
                    <TableCell className="py-2 whitespace-nowrap">{getStatusBadge(log.logLevel)}</TableCell>
                    <TableCell className="py-2 text-xs">
                      <div className={`font-mono ${getStatusColor(log.logLevel)} truncate`}>
                        <span dangerouslySetInnerHTML={{ 
                          __html: log.log.substring(0, 100).replace(
                            new RegExp(`(${searchQuery})`, 'gi'),
                            '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                          )
                        }} />
                        {log.log.length > 100 ? '...' : ''}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {logs.filter(log => {
                  if (!searchQuery) return true;
                  const query = searchQuery.toLowerCase();
                  return (
                    log.timestampFormatted.toLowerCase().includes(query) ||
                    log.serviceName.toLowerCase().includes(query) ||
                    log.logLevel.toLowerCase().includes(query) ||
                    log.log.toLowerCase().includes(query)
                  );
                }).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                      {searchQuery ? 'No logs match your search.' : 'No logs available. Waiting for data...'}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {Math.ceil(logs.filter(log => {
            if (!searchQuery) return true;
            const query = searchQuery.toLowerCase();
            return (
              log.timestampFormatted.toLowerCase().includes(query) ||
              log.serviceName.toLowerCase().includes(query) ||
              log.logLevel.toLowerCase().includes(query) ||
              log.log.toLowerCase().includes(query)
            );
          }).length / itemsPerPage) > 1 && (
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
                {(() => {
                  const filteredLogs = logs.filter(log => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      log.timestampFormatted.toLowerCase().includes(query) ||
                      log.serviceName.toLowerCase().includes(query) ||
                      log.logLevel.toLowerCase().includes(query) ||
                      log.log.toLowerCase().includes(query)
                    );
                  });
                  const totalPages = Math.ceil(filteredLogs.length / itemsPerPage);
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
                            setCurrentPage(pageNum);
                          }}
                          isActive={currentPage === pageNum}
                        >
                          {pageNum}
                        </PaginationLink>
                      </PaginationItem>
                    );
                  });
                })()}
                {(() => {
                  const filteredLogs = logs.filter(log => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      log.timestampFormatted.toLowerCase().includes(query) ||
                      log.serviceName.toLowerCase().includes(query) ||
                      log.logLevel.toLowerCase().includes(query) ||
                      log.log.toLowerCase().includes(query)
                    );
                  });
                  return Math.ceil(filteredLogs.length / itemsPerPage) > 5 ? <PaginationEllipsis /> : null;
                })()}
                <PaginationItem>
                  <PaginationNext 
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      if (currentPage < Math.ceil(logs.length / itemsPerPage)) setCurrentPage(currentPage + 1);
                    }}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          )}
        </div>
      </div>

      {/* Expanded Log Modal */}
      {expandedLog && (
        <div 
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 backdrop-blur-sm"
          onClick={() => setExpandedLog(null)}
        >
          <div 
            className="bg-card border-2 border-border rounded-lg shadow-2xl w-[90vw] max-w-3xl max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {(() => {
              const log = logs.find(l => l.id === expandedLog);
              if (!log) return null;
              
              return (
                <>
                  <div className="flex items-center justify-between p-4 border-b border-border">
                    <h3 className="text-lg font-semibold">Log Details</h3>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setExpandedLog(null)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="p-6 space-y-3 border-b border-border">
                    <div className="text-sm text-muted-foreground">
                      <span className="font-semibold">Service:</span> {log.serviceName}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      <span className="font-semibold">Time:</span> {log.timestampFormatted}
                    </div>
                    <div className="text-sm">
                      <span className="font-semibold">Level:</span> {getStatusBadge(log.logLevel)}
                    </div>
                  </div>
                  <div className="flex-1 overflow-auto p-6 [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-track]:bg-muted/20 [&::-webkit-scrollbar-thumb]:bg-muted-foreground/30 [&::-webkit-scrollbar-thumb]:rounded-full">
                    <pre className={`text-sm whitespace-pre-wrap font-mono ${getStatusColor(log.logLevel)}`}>
                      {log.log}
                    </pre>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}``