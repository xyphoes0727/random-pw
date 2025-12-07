import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Loader2, User, Users, TrendingUp, Shield, AlertTriangle } from "lucide-react";
import axiosInstance from "@/lib/axios";

interface TransactionAnalysis {
  transactionId: string;
  sender: string;
  receiver: string;
  model_prediction: number;
  pagerank: number;
  stddev_amount: number;
  amount: number;
  user_txn_count: number;
  mean_amount: number;
  timestamp: string;
  confidence_score: number | null;
  transactions_between_sender_receiver: number;
  sender_total_frauds: number;
  receiver_total_frauds: number;
  trust_score_sender: number;
  trust_score_receiver: number;
  sender_fraud_ratio: number;
  receiver_fraud_ratio: number;
}

interface TransactionAnalysisDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transactionId: string;
}

export const TransactionAnalysisDialog = ({
  open,
  onOpenChange,
  transactionId,
}: TransactionAnalysisDialogProps) => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<TransactionAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && transactionId) {
      fetchAnalysis();
    }
  }, [open, transactionId]);

  const fetchAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axiosInstance.post("/api/transaction_analysis/", {
        transactionId: transactionId,
      });
      setData(response.data);
    } catch (err: any) {
      console.error("Error fetching transaction analysis:", err);
      setError(err.response?.data?.message || "Failed to fetch transaction analysis");
    } finally {
      setLoading(false);
    }
  };

  const getTrustScoreColor = (score: number) => {
    if (score >= 0.7) return "text-green-600";
    if (score >= 0.4) return "text-yellow-600";
    return "text-red-600";
  };

  const getFraudRatioColor = (ratio: number) => {
    if (ratio <= 0.1) return "text-green-600";
    if (ratio <= 0.3) return "text-yellow-600";
    return "text-red-600";
  };
  const formatTimestamp = (nsTimestamp: string | number) => {
    const ts = Number(nsTimestamp);              // convert to number
    const date = new Date(Number(ts));       // ns → ms
    return date.toLocaleString();                // human-readable (local timezone)
  };
  const getPredictionBadge = (isFraud: number, confidence: number | null) => {
    if (confidence == null) {
      return { label: "Unknown", className: "bg-gray-500 text-white" };
    }

    if (isFraud === 1 && confidence >= 0.4) {
      return { label: "Fraud", className: "bg-red-900 text-white" };
    }

    if (isFraud === 1 && confidence < 0.4) {
      return { label: "Fraud", className: "bg-orange-600 text-white" }; 
    }

    if (isFraud === 0 && confidence < 0.4) {
      return { label: "Not Fraud", className: "bg-orange-400 text-white" }; 
    }
    return { label: "Not Fraud", className: "bg-green-600 text-white" };
  };


  return (
    <>
      <style>
        {`
          .hide-scrollbar::-webkit-scrollbar {
            display: none;
          }
          .hide-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
          }
        `}
      </style>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto hide-scrollbar">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-primary" />
              Transaction Analysis
            </DialogTitle>
          </DialogHeader>

          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          )}

          {error && (
            <div className="text-center py-8 text-destructive">
              <AlertTriangle className="h-8 w-8 mx-auto mb-2" />
              <p>{error}</p>
            </div>
          )}

          {data && !loading && (
            <div className="space-y-4">
              {/* Transaction Overview */}
              <Card className="p-4">
                <h4 className="font-semibold text-foreground mb-3">Transaction Overview</h4>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Transaction ID:</span>
                    <p className="font-mono font-medium">{data.transactionId}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Amount:</span>
                    <p className="font-semibold text-lg">${data.amount.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Timestamp:</span>
                    <p>{formatTimestamp(data.timestamp)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground mr-2">Model Prediction:</span>
                    {(() => {
                      const badge = getPredictionBadge(data.model_prediction, data.confidence_score);
                      return (
                        <Badge className={badge.className}>
                          {badge.label}
                        </Badge>
                      );
                    })()}
                  </div>
                  {data.confidence_score !== null && (
                    <div>
                      <span className="text-muted-foreground">Confidence Score:</span>
                      <p className="font-medium">{(data.confidence_score * 100).toFixed(1)}%</p>
                    </div>
                  )}
                  <div>
                    <span className="text-muted-foreground">PageRank:</span>
                    <p className="font-medium">{data.pagerank.toFixed(4)}</p>
                  </div>
                </div>
              </Card>

              {/* Sender Information */}
              <Card className="p-4">
                <h4 className="font-semibold text-foreground mb-3 flex items-center gap-2">
                  <User className="h-4 w-4" />
                  Sender: {data.sender}
                </h4>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Trust Score:</span>
                    <p className={`font-semibold ${getTrustScoreColor(data.trust_score_sender)}`}>
                      {(data.trust_score_sender).toFixed(1)}%
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Total Frauds:</span>
                    <p className={`font-medium ${data.sender_total_frauds > 0 ? "text-red-600" : "text-green-600"}`}>
                      {data.sender_total_frauds}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Fraud Ratio:</span>
                    <p className={`font-medium ${getFraudRatioColor(data.sender_fraud_ratio)}`}>
                      {(data.sender_fraud_ratio).toFixed(2)}%
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Transaction Count:</span>
                    <p className="font-medium">{data.user_txn_count}</p>
                  </div>
                </div>
              </Card>

              {/* Receiver Information */}
              <Card className="p-4">
                <h4 className="font-semibold text-foreground mb-3 flex items-center gap-2">
                  <User className="h-4 w-4" />
                  Receiver: {data.receiver}
                </h4>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Trust Score:</span>
                    <p className={`font-semibold ${getTrustScoreColor(data.trust_score_receiver)}`}>
                      {(data.trust_score_receiver * 100).toFixed(1)}%
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Total Frauds:</span>
                    <p className={`font-medium ${data.receiver_total_frauds > 0 ? "text-red-600" : "text-green-600"}`}>
                      {data.receiver_total_frauds}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Fraud Ratio:</span>
                    <p className={`font-medium ${getFraudRatioColor(data.receiver_fraud_ratio)}`}>
                      {(data.receiver_fraud_ratio * 100).toFixed(2)}%
                    </p>
                  </div>
                </div>
              </Card>

              {/* Relationship Stats */}
              <Card className="p-4">
                <h4 className="font-semibold text-foreground mb-3 flex items-center gap-2">
                  <Users className="h-4 w-4" />
                  Relationship Statistics
                </h4>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Transactions Between Parties:</span>
                    <p className="font-medium">{data.transactions_between_sender_receiver}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Mean Amount:</span>
                    <p className="font-medium">${data.mean_amount.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Std Dev Amount:</span>
                    <p className="font-medium">${data.stddev_amount.toFixed(2)}</p>
                  </div>
                </div>
              </Card>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
};