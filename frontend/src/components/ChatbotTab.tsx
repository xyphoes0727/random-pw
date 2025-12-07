import { useState, useRef, useEffect, useCallback } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, Trash2, Bot, User, AlertCircle, Loader2, BarChart3, Paperclip, X, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"
import remarkGfm from "remark-gfm";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useToast } from "@/hooks/use-toast";
import { DocumentVerificationResult } from "./DocumentVerificationResult";

interface ChartData {
  chart_type: "line" | "bar" | "pie" | "scatter";
  meta?: { sql?: string };
  chart: {
    labels?: string[];
    datasets: Array<{
      label: string;
      data: number[] | Array<{ x: number; y: number }>;
    }>;
  };
}

interface DocumentVerification {
  type: string;
  conversation_id: string;
  applicant_id: string;
  doc_type: string;
  llm_result: {
    verdict: string;
    confidence: number;
    reasons: string[];
    citations: Array<{
      source: string;
      doc_id: string;
      page_no: number;
      snippet: string;
    }>;
    structured: Record<string, any>;
  };
  similarity_score: number;
  retrieved_count: number;
}

interface Message {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  chart?: ChartData;
  documentVerification?: DocumentVerification;
  fileName?: string;
  timestamp: Date;
}

const COLORS = [
  "hsl(var(--primary))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
];

const EXAMPLE_QUERIES = [
  "Show me the fraud distribution by payment type",
  "What are the top 10 highest value transactions?",
  "Plot transaction amounts over time",
  "How many fraudulent vs legitimate transactions are there?",
  "Show me a scatter plot of amount vs transaction ID",
];

const ChatbotTab = () => {
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const stored = sessionStorage.getItem("chat_messages");
      if (stored) {
        const parsed = JSON.parse(stored);
        return parsed.map((msg: any) => ({
          ...msg,
          timestamp: new Date(msg.timestamp),
        }));
      }
    } catch (error) {
      console.error("Error loading chat messages:", error);
    }
    return [];
  });
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(() => {
    return sessionStorage.getItem("chat_conversation_id");
  });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Save messages to sessionStorage
  useEffect(() => {
    if (messages.length > 0) {
      try {
        sessionStorage.setItem("chat_messages", JSON.stringify(messages));
      } catch (error) {
        console.error("Error saving messages:", error);
      }
    }
  }, [messages]);

  useEffect(() => {
    if (conversationId) {
      sessionStorage.setItem("chat_conversation_id", conversationId);
    } else {
      sessionStorage.removeItem("chat_conversation_id");
    }
  }, [conversationId]);

  const parseSSEData = (line: string): any | null => {
    if (line.startsWith("data: ")) {
      try {
        return JSON.parse(line.slice(6));
      } catch {
        return null;
      }
    }
    return null;
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.type !== "application/pdf") {
        toast({
          title: "Invalid file type",
          description: "Please select a PDF file",
          variant: "destructive",
        });
        return;
      }
      setSelectedFile(file);
    }
  };

  const removeSelectedFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const sendPDFMessage = async () => {
  if (!selectedFile) return;

  const fileName = selectedFile.name; // Save filename before clearing

  const userMessage: Message = {
    id: `user-${Date.now()}`,
    role: "user",
    content: input.trim() || `Uploaded document: ${fileName}`,
    fileName: fileName,
    timestamp: new Date(),
  };

  setMessages((prev) => [...prev, userMessage]);
  setInput("");
  setIsLoading(true);

  const assistantMessageId = `assistant-${Date.now()}`;
  
  setMessages((prev) => [
    ...prev,
    {
      id: assistantMessageId,
      role: "assistant",
      content: "Analyzing document...",
      timestamp: new Date(),
    },
  ]);

  try {
    const formData = new FormData();
    formData.append("file", selectedFile);
    
    // Add conversation_id if exists
    if (conversationId) {
      formData.append("conversation_id", conversationId);
    }
    
    // Optional: Add applicant_id if you have it (can be from user input or form)
    formData.append("applicant_id", "12345"); // Replace with actual applicant ID logic
    
    // Optional: Add custom question if user provided one
    if (input.trim()) {
      formData.append("question", input.trim());
    }
    
    // Optional: Add doc_type if needed
    formData.append("doc_type", "income_verification"); // Or make this dynamic

    const response = await fetch(`${BASE_URL_HTTP}/api/chat/`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
    }

    const data = await response.json();

    if (data.type === "document_verification") {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: "Document analysis complete:",
                documentVerification: data,
                fileName: fileName, // Pass fileName to message
              }
            : msg
        )
      );
      
      // Update conversation ID if new one was created
      if (data.conversation_id && data.conversation_id !== conversationId) {
        setConversationId(data.conversation_id);
      }
    } else if (data.error) {
      // Handle error response
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                role: "error",
                content: data.error || "Document verification failed",
              }
            : msg
        )
      );
    } else {
      // Fallback for unexpected response format
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, content: JSON.stringify(data, null, 2) }
            : msg
        )
      );
    }
  } catch (error) {
    console.error("PDF upload error:", error);
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === assistantMessageId
          ? {
              ...msg,
              role: "error",
              content: error instanceof Error ? error.message : "Failed to upload document",
            }
          : msg
      )
    );
    toast({
      title: "Error",
      description: error instanceof Error ? error.message : "Failed to upload document",
      variant: "destructive",
    });
  } finally {
    setIsLoading(false);
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }
};
  const sendMessage = async () => {
    if (selectedFile) {
      await sendPDFMessage();
      return;
    }

    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    setIsStreaming(true);

    const assistantMessageId = `assistant-${Date.now()}`;
    let accumulatedText = "";
    let receivedChart: ChartData | undefined;
    let newConversationId = conversationId;

    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
      },
    ]);

    try {
      const response = await fetch(`${BASE_URL_HTTP}/api/chat/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text: userMessage.content,
          conversation_id: conversationId,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("No response body");
      }

      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;

          const data = parseSSEData(line.trim());
          if (!data) continue;

          if (data.text) {
            accumulatedText += data.text;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId
                  ? { ...msg, content: accumulatedText }
                  : msg
              )
            );
          }

          if (data.conversation_id && !newConversationId) {
            newConversationId = data.conversation_id;
            setConversationId(data.conversation_id);
          }

          if (data.mode === "plot" && data.response?.result) {
            receivedChart = {
              chart_type: data.response.result.chart_type,
              meta: data.response.result.meta,
              chart: data.response.result.chart,
            };
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId
                  ? { ...msg, chart: receivedChart, content: accumulatedText || data.response.message || "Here's the chart:" }
                  : msg
              )
            );
            if (data.conversation_id) {
              setConversationId(data.conversation_id);
            }
          }

          if (data.done) {
            setIsStreaming(false);
          }

          if (data.error) {
            throw new Error(data.error);
          }
        }
      }

      if (buffer.trim()) {
        const data = parseSSEData(buffer.trim());
        if (data?.text) {
          accumulatedText += data.text;
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: accumulatedText }
                : msg
            )
          );
        }
      }
    } catch (error) {
      console.error("Chat error:", error);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                role: "error",
                content: error instanceof Error ? error.message : "An error occurred",
              }
            : msg
        )
      );
      toast({
        title: "Error",
        description: error instanceof Error ? error.message : "Failed to send message",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
      setIsStreaming(false);
    }
  };

  const clearConversation = async () => {
    if (conversationId) {
      try {
        await fetch(`${BASE_URL_HTTP}/api/chat/update/${conversationId}/`, {
          method: "DELETE",
        });
      } catch (error) {
        console.error("Failed to clear conversation:", error);
      }
    }
    setMessages([]);
    setConversationId(null);
    sessionStorage.removeItem("chat_conversation_id");
    sessionStorage.removeItem("chat_messages");
    toast({
      title: "Conversation cleared",
      description: "Started a new conversation",
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleExampleClick = (query: string) => {
    setInput(query);
    textareaRef.current?.focus();
  };

  const renderChart = (chartData: ChartData) => {
    const { chart_type, chart } = chartData;

    const axisStyle = {
      stroke: "hsl(var(--foreground))",
      fontSize: 12,
    };

    const gridStyle = {
      stroke: "hsl(var(--border))",
      strokeOpacity: 0.3,
    };

    const tooltipStyle = {
      backgroundColor: "hsl(var(--popover))",
      border: "1px solid hsl(var(--border))",
      borderRadius: "8px",
      color: "white",
    };

    switch (chart_type) {
      case "line":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chart.labels?.map((label, i) => ({
              name: label,
              ...chart.datasets.reduce((acc, ds, idx) => ({
                ...acc,
                [`series${idx}`]: Array.isArray(ds.data) && typeof ds.data[0] === 'number' ? ds.data[i] : 0,
              }), {}),
            }))}>
              <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
              <XAxis 
                dataKey="name" 
                {...axisStyle}
                tick={{ fill: "hsl(var(--foreground))" }}
              />
              <YAxis 
                {...axisStyle}
                tick={{ fill: "hsl(var(--foreground))" }}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={{ color: "white" }}
                itemStyle={{ color: "white" }}
              />
              <Legend 
                wrapperStyle={{ color: "hsl(var(--foreground))" }}
              />
              {chart.datasets.map((ds, idx) => (
                <Line
                  key={idx}
                  type="monotone"
                  dataKey={`series${idx}`}
                  name={ds.label}
                  stroke={COLORS[idx % COLORS.length]}
                  strokeWidth={2}
                  dot={{ fill: COLORS[idx % COLORS.length] }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case "bar":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chart.labels?.map((label, i) => ({
              name: label,
              ...chart.datasets.reduce((acc, ds, idx) => ({
                ...acc,
                [`series${idx}`]: Array.isArray(ds.data) && typeof ds.data[0] === 'number' ? ds.data[i] : 0,
              }), {}),
            }))}>
              <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
              <XAxis 
                dataKey="name" 
                {...axisStyle}
                tick={{ fill: "hsl(var(--foreground))" }}
              />
              <YAxis 
                {...axisStyle}
                tick={{ fill: "hsl(var(--foreground))" }}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={{ color: "white" }}
                itemStyle={{ color: "white" }}
              />
              <Legend 
                wrapperStyle={{ color: "hsl(var(--foreground))" }}
              />
              {chart.datasets.map((ds, idx) => (
                <Bar
                  key={idx}
                  dataKey={`series${idx}`}
                  name={ds.label}
                  fill={COLORS[idx % COLORS.length]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );

      case "pie":
        const pieData = chart.labels?.map((label, i) => ({
          name: label,
          value: Array.isArray(chart.datasets[0]?.data) && typeof chart.datasets[0].data[0] === 'number'
            ? (chart.datasets[0].data as number[])[i]
            : 0,
        })) || [];
        return (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="hsl(var(--primary))"
                dataKey="value"
              >
                {pieData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={{ color: "white" }}
                itemStyle={{ color: "white" }}
              />
              <Legend 
                wrapperStyle={{ color: "hsl(var(--foreground))" }}
              />
            </PieChart>
          </ResponsiveContainer>
        );

      case "scatter":
        const scatterData = chart.datasets[0]?.data as Array<{ x: number; y: number }> || [];
        return (
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
              <XAxis 
                type="number" 
                dataKey="x" 
                name="X" 
                {...axisStyle}
                tick={{ fill: "hsl(var(--foreground))" }}
              />
              <YAxis 
                type="number" 
                dataKey="y" 
                name="Y" 
                {...axisStyle}
                tick={{ fill: "hsl(var(--foreground))" }}
              />
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                contentStyle={tooltipStyle}
                labelStyle={{ color: "white" }}
                itemStyle={{ color: "white" }}
              />
              <Legend 
                wrapperStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Scatter
                name={chart.datasets[0]?.label || "Data"}
                data={scatterData}
                fill="hsl(var(--primary))"
              />
            </ScatterChart>
          </ResponsiveContainer>
        );

      default:
        return <p className="text-muted-foreground">Unsupported chart type: {chart_type}</p>;
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-180px)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">AI Assistant</h2>
          {conversationId && (
            <span className="text-xs text-muted-foreground bg-muted px-2 py-1 rounded">
              ID: {conversationId.slice(0, 8)}...
            </span>
          )}
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="outline" size="sm" disabled={messages.length === 0}>
              <Trash2 className="h-4 w-4 mr-2" />
              Clear Chat
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Clear conversation?</AlertDialogTitle>
              <AlertDialogDescription>
                This will delete all messages in this conversation. This action cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={clearConversation}>Clear</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      {/* Messages Area */}
      <Card className="flex-1 overflow-hidden">
        <ScrollArea className="h-full p-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center space-y-6 py-8">
              <div className="bg-primary/10 p-4 rounded-full">
                <Bot className="h-12 w-12 text-primary" />
              </div>
              <div>
                <h3 className="text-xl font-semibold mb-2">Welcome to AI Assistant</h3>
                <p className="text-muted-foreground max-w-md">
                  Ask questions about your transaction data, request visualizations, or upload PDF documents for verification.
                </p>
              </div>
              <div className="space-y-2 w-full max-w-lg">
                <p className="text-sm font-medium text-muted-foreground">Try asking:</p>
                <div className="flex flex-wrap gap-2 justify-center">
                  {EXAMPLE_QUERIES.map((query, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleExampleClick(query)}
                      className="text-xs bg-muted hover:bg-muted/80 px-3 py-2 rounded-full transition-colors text-left"
                    >
                      {query}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`flex gap-3 max-w-[80%] ${
                      message.role === "user" ? "flex-row-reverse" : "flex-row"
                    }`}
                  >
                    <div
                      className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : message.role === "error"
                          ? "bg-destructive text-destructive-foreground"
                          : "bg-muted"
                      }`}
                    >
                      {message.role === "user" ? (
                        <User className="h-4 w-4" />
                      ) : message.role === "error" ? (
                        <AlertCircle className="h-4 w-4" />
                      ) : (
                        <Bot className="h-4 w-4" />
                      )}
                    </div>
                    <div
                      className={`rounded-lg px-4 py-2 ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : message.role === "error"
                          ? "bg-destructive/10 text-destructive border border-destructive/20"
                          : "bg-muted"
                      }`}
                    >
                      {message.fileName && (
                        <div className="flex items-center gap-2 mb-2 text-sm opacity-80">
                          <FileText className="h-4 w-4" />
                          <span>{message.fileName}</span>
                        </div>
                      )}
                      {message.role === "assistant" ? (
                        <div className="prose prose-sm dark:prose-invert max-w-none">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              table: ({ children }) => (
                                <div className="overflow-x-auto my-4">
                                  <table className="min-w-full border-collapse border border-border">
                                    {children}
                                  </table>
                                </div>
                              ),
                              thead: ({ children }) => (
                                <thead className="bg-muted">{children}</thead>
                              ),
                              th: ({ children }) => (
                                <th className="border border-border px-4 py-2 text-left font-semibold">
                                  {children}
                                </th>
                              ),
                              td: ({ children }) => (
                                <td className="border border-border px-4 py-2">{children}</td>
                              ),
                              tr: ({ children }) => (
                                <tr className="hover:bg-muted/50">{children}</tr>
                              ),
                              code: ({ children, className }) => {
                                const isInline = !className;
                                return isInline ? (
                                  <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono">
                                    {children}
                                  </code>
                                ) : (
                                  <pre className="bg-muted p-3 rounded overflow-x-auto my-2">
                                    <code className="text-sm font-mono">{children}</code>
                                  </pre>
                                );
                              },
                            }}
                          >
                            {message.content}
                          </ReactMarkdown>
                          {isStreaming && messages[messages.length - 1]?.id === message.id && (
                            <span className="inline-block w-2 h-4 bg-primary animate-pulse ml-1" />
                          )}
                        </div>
                      ) : (
                        <p className="whitespace-pre-wrap">{message.content}</p>
                      )}
                      {message.chart && (
                        <div className="mt-4 p-4 bg-background rounded-lg border">
                          <div className="flex items-center gap-2 mb-3">
                            <BarChart3 className="h-4 w-4 text-primary" />
                            <span className="text-xs font-medium uppercase bg-primary/10 text-primary px-2 py-1 rounded">
                              {message.chart.chart_type} Chart
                            </span>
                          </div>
                          {renderChart(message.chart)}
                        </div>
                      )}
                      {message.documentVerification && (
                        <DocumentVerificationResult 
                          result={message.documentVerification} 
                          fileName={message.fileName}
                        />
                      )}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </ScrollArea>
      </Card>

      {/* Selected File Preview */}
      {selectedFile && (
        <div className="mt-2 flex items-center gap-2 bg-muted px-3 py-2 rounded-lg">
          <FileText className="h-4 w-4 text-primary" />
          <span className="text-sm flex-1 truncate">{selectedFile.name}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={removeSelectedFile}
            className="h-6 w-6 p-0"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Input Area */}
      <div className="mt-4 flex gap-2">
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileSelect}
          accept=".pdf"
          className="hidden"
        />
        <Button
          variant="outline"
          size="icon"
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading}
          className="h-auto aspect-square"
        >
          <Paperclip className="h-5 w-5" />
        </Button>
        <Textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={selectedFile ? "Add a message (optional) or send the document..." : "Ask about your transaction data..."}
          className="min-h-[60px] max-h-[120px] resize-none"
          disabled={isLoading}
        />
        <Button
          onClick={sendMessage}
          disabled={(!input.trim() && !selectedFile) || isLoading}
          className="h-auto px-6"
        >
          {isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Send className="h-5 w-5" />
          )}
        </Button>
      </div>
    </div>
  );
};

export default ChatbotTab;
