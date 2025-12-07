import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
export const SystemStatusTab = () => {
  const [showAmbientDetails, setShowAmbientDetails] = useState(false);
  const metricsData = [
    { 
      time: "00:00", 
      ingestion: 45, model: 55, apiGateway: 35, storage: 25,
      ingestionRam: 62, modelRam: 68, apiGatewayRam: 52, storageRam: 42,
      ingestionThroughput: 1200, modelThroughput: 850, apiGatewayThroughput: 1500, storageThroughput: 600,
      ingestionErrors: 2, modelErrors: 1, apiGatewayErrors: 3, storageErrors: 1
    },
    { 
      time: "04:00", 
      ingestion: 32, model: 42, apiGateway: 22, storage: 18,
      ingestionRam: 58, modelRam: 64, apiGatewayRam: 48, storageRam: 40,
      ingestionThroughput: 800, modelThroughput: 600, apiGatewayThroughput: 900, storageThroughput: 400,
      ingestionErrors: 1, modelErrors: 0, apiGatewayErrors: 2, storageErrors: 0
    },
    { 
      time: "08:00", 
      ingestion: 68, model: 78, apiGateway: 58, storage: 48,
      ingestionRam: 71, modelRam: 81, apiGatewayRam: 61, storageRam: 51,
      ingestionThroughput: 2400, modelThroughput: 1800, apiGatewayThroughput: 2800, storageThroughput: 1200,
      ingestionErrors: 5, modelErrors: 3, apiGatewayErrors: 7, storageErrors: 2
    },
    { 
      time: "12:00", 
      ingestion: 78, model: 88, apiGateway: 68, storage: 58,
      ingestionRam: 75, modelRam: 85, apiGatewayRam: 65, storageRam: 55,
      ingestionThroughput: 3100, modelThroughput: 2400, apiGatewayThroughput: 3500, storageThroughput: 1600,
      ingestionErrors: 8, modelErrors: 5, apiGatewayErrors: 10, storageErrors: 3
    },
    { 
      time: "16:00", 
      ingestion: 65, model: 75, apiGateway: 55, storage: 45,
      ingestionRam: 69, modelRam: 79, apiGatewayRam: 59, storageRam: 49,
      ingestionThroughput: 2600, modelThroughput: 2000, apiGatewayThroughput: 2900, storageThroughput: 1300,
      ingestionErrors: 6, modelErrors: 4, apiGatewayErrors: 8, storageErrors: 2
    },
    { 
      time: "20:00", 
      ingestion: 52, model: 62, apiGateway: 42, storage: 32,
      ingestionRam: 64, modelRam: 74, apiGatewayRam: 54, storageRam: 44,
      ingestionThroughput: 1800, modelThroughput: 1400, apiGatewayThroughput: 2000, storageThroughput: 900,
      ingestionErrors: 4, modelErrors: 2, apiGatewayErrors: 5, storageErrors: 1
    },
  ];

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h3 className="mb-6 text-lg font-semibold text-foreground">System Overview</h3>
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <div className="mb-4 flex items-center justify-between">
              <span className="text-sm font-medium text-muted-foreground">Uptime</span>
              <span className="text-lg font-bold text-success">99.98%</span>
            </div>
            <p className="text-xs text-muted-foreground">Last restart: 12 days ago</p>
          </div>

          <div className="space-y-3">
            <h4 className="text-sm font-semibold text-foreground">Modules</h4>
            {[
              { name: "API Gateway", status: "online" },
              { name: "Payment Processor", status: "online" },
              { name: "Risk Engine", status: "online" },
              { name: "Analytics", status: "online" },
              { name: "Notifications", status: "degraded" },
            ].map((module) => (
              <div key={module.name} className="flex items-center justify-between">
                <span className="text-sm text-foreground">{module.name}</span>
                <Badge
                  variant={module.status === "online" ? "default" : "secondary"}
                  className={module.status === "online" ? "bg-success" : "bg-warning"}
                >
                  {module.status}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* Ambient Agent Block */}
      <Card className="p-6">
        <div 
          className="flex items-center justify-between cursor-pointer"
          onClick={() => setShowAmbientDetails(!showAmbientDetails)}
        >
          <div>
            <h3 className="text-lg font-semibold text-foreground">Ambient Agent</h3>
            <p className="text-sm text-muted-foreground mt-1">System monitoring and network statistics</p>
          </div>
          {showAmbientDetails ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
        </div>

        <div className="grid gap-4 md:grid-cols-4 mt-6">
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">CPU Monitoring</div>
            <div className="text-2xl font-bold text-foreground">Active</div>
            <Badge variant="default" className="bg-success">Running</Badge>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">CPU Usage</div>
            <div className="text-2xl font-bold text-foreground">68.4%</div>
            <div className="text-xs text-muted-foreground">of total capacity</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Memory</div>
            <div className="text-2xl font-bold text-foreground">12.8 GB</div>
            <div className="text-xs text-muted-foreground">of 16 GB used</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">CPU Count</div>
            <div className="text-2xl font-bold text-foreground">8 cores</div>
            <div className="text-xs text-muted-foreground">available</div>
          </div>
        </div>

        {showAmbientDetails && (
          <div className="mt-6 pt-6 border-t space-y-6">
            <div>
              <h4 className="text-sm font-semibold text-foreground mb-4">Network I/O Statistics</h4>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Bytes Sent</div>
                  <div className="text-xl font-bold text-foreground">2.4 GB</div>
                  <div className="text-xs text-success">↑ 12.3 MB/s</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Bytes Received</div>
                  <div className="text-xl font-bold text-foreground">5.8 GB</div>
                  <div className="text-xs text-success">↓ 28.7 MB/s</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Packets Sent</div>
                  <div className="text-xl font-bold text-foreground">1.8M</div>
                  <div className="text-xs text-muted-foreground">total</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Packets Received</div>
                  <div className="text-xl font-bold text-foreground">3.2M</div>
                  <div className="text-xs text-muted-foreground">total</div>
                </div>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold text-foreground mb-4">Error Statistics</h4>
              <div className="grid gap-4 md:grid-cols-4">
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Errors In</div>
                  <div className="text-xl font-bold text-destructive">23</div>
                  <div className="text-xs text-muted-foreground">incoming errors</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Errors Out</div>
                  <div className="text-xl font-bold text-destructive">12</div>
                  <div className="text-xs text-muted-foreground">outgoing errors</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Drop In</div>
                  <div className="text-xl font-bold text-warning">8</div>
                  <div className="text-xs text-muted-foreground">dropped packets</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Drop Out</div>
                  <div className="text-xl font-bold text-warning">5</div>
                  <div className="text-xs text-muted-foreground">dropped packets</div>
                </div>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold text-foreground mb-4">CPU Details</h4>
              <div className="space-y-2">
                {[
                  { core: 1, usage: 72 },
                  { core: 2, usage: 65 },
                  { core: 3, usage: 78 },
                  { core: 4, usage: 60 },
                  { core: 5, usage: 68 },
                  { core: 6, usage: 71 },
                  { core: 7, usage: 64 },
                  { core: 8, usage: 69 },
                ].map((cpu) => (
                  <div key={cpu.core} className="flex items-center gap-4">
                    <span className="text-xs text-muted-foreground w-12">Core {cpu.core}</span>
                    <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-primary transition-all" 
                        style={{ width: `${cpu.usage}%` }}
                      ></div>
                    </div>
                    <span className="text-xs font-medium w-12 text-right">{cpu.usage}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <h4 className="text-lg font-semibold text-foreground mb-4">CPU Usage (%)</h4>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={metricsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                }}
              />
              <Line type="monotone" dataKey="ingestion" stroke="hsl(var(--primary))" strokeWidth={2} name="Ingestion" />
              <Line type="monotone" dataKey="model" stroke="hsl(var(--chart-2))" strokeWidth={2} name="Model" />
              <Line type="monotone" dataKey="apiGateway" stroke="hsl(var(--chart-3))" strokeWidth={2} name="API Gateway" />
              <Line type="monotone" dataKey="storage" stroke="hsl(var(--chart-4))" strokeWidth={2} name="Storage" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card className="p-6">
          <h4 className="text-lg font-semibold text-foreground mb-4">RAM Usage (%)</h4>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={metricsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                }}
              />
              <Line type="monotone" dataKey="ingestionRam" stroke="hsl(var(--primary))" strokeWidth={2} name="Ingestion" />
              <Line type="monotone" dataKey="modelRam" stroke="hsl(var(--chart-2))" strokeWidth={2} name="Model" />
              <Line type="monotone" dataKey="apiGatewayRam" stroke="hsl(var(--chart-3))" strokeWidth={2} name="API Gateway" />
              <Line type="monotone" dataKey="storageRam" stroke="hsl(var(--chart-4))" strokeWidth={2} name="Storage" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card className="p-6">
          <h4 className="text-lg font-semibold text-foreground mb-4">Throughput (req/s)</h4>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={metricsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                }}
              />
              <Line type="monotone" dataKey="ingestionThroughput" stroke="hsl(var(--primary))" strokeWidth={2} name="Ingestion" />
              <Line type="monotone" dataKey="modelThroughput" stroke="hsl(var(--chart-2))" strokeWidth={2} name="Model" />
              <Line type="monotone" dataKey="apiGatewayThroughput" stroke="hsl(var(--chart-3))" strokeWidth={2} name="API Gateway" />
              <Line type="monotone" dataKey="storageThroughput" stroke="hsl(var(--chart-4))" strokeWidth={2} name="Storage" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card className="p-6">
          <h4 className="text-lg font-semibold text-foreground mb-4">Errors Encountered</h4>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={metricsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                }}
              />
              <Line type="monotone" dataKey="ingestionErrors" stroke="hsl(var(--primary))" strokeWidth={2} name="Ingestion" />
              <Line type="monotone" dataKey="modelErrors" stroke="hsl(var(--chart-2))" strokeWidth={2} name="Model" />
              <Line type="monotone" dataKey="apiGatewayErrors" stroke="hsl(var(--chart-3))" strokeWidth={2} name="API Gateway" />
              <Line type="monotone" dataKey="storageErrors" stroke="hsl(var(--chart-4))" strokeWidth={2} name="Storage" />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
};
