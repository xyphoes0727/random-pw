import { useState, useEffect } from "react";
import { ArrowLeft, CheckCircle, BarChart3, Info } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import axiosInstance from "@/lib/axios";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { DashboardHeader } from "@/components/DashboardHeader";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { SHAPResultsDialog } from "@/components/SHAPResultsDialog";
import { TransactionAnalysisDialog } from "@/components/TransactionAnalysisDialog";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

interface Transaction {
  transaction_id: string;
  amount: number;
  confidence_score: number;
  is_fraud: number;
  nameOrig: string;
  nameDest: string;
  time: string;
  is_verified: boolean;
  ground_truth: number | null;
}

const TransactionDetails = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { isAuthenticated } = useAuth();
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [fraudFilter, setFraudFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("");
  const [verifyingTransaction, setVerifyingTransaction] = useState<string | null>(null);
  const [selectedTransactionForVerify, setSelectedTransactionForVerify] = useState<Transaction | null>(null);
  const [verificationValue, setVerificationValue] = useState<number | null>(null);
  const [analystMessage, setAnalystMessage] = useState("");
  const [shapDialogOpen, setSHAPDialogOpen] = useState(false);
  const [selectedTransactionForSHAP, setSelectedTransactionForSHAP] = useState<string | null>(null);
  const [analysisDialogOpen, setAnalysisDialogOpen] = useState(false);
  const [selectedTransactionForAnalysis, setSelectedTransactionForAnalysis] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const itemsPerPage = 30;

  useEffect(() => {
    if (isAuthenticated) {
      fetchTransactions();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated]);

  const fetchTransactions = async () => {
    try {
      const response = await axiosInstance.get("/api/transaction_details/");
      setTransactions(response.data);
      console.log("No of transactions:", transactions.length);
    } catch (error: any) {
      if (error.response?.status === 404) {
        toast({
          title: "No Transactions",
          description: "Transactions don't exist",
          variant: "destructive",
        });
        setTransactions([]);
      } else {
        console.error("Error fetching transactions:", error);
        toast({
          title: "Error",
          description: "Failed to fetch transactions",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const filteredTransactions = transactions.filter((transaction) => {
    const matchesFraud = fraudFilter === "all" ||
      (fraudFilter === "high-confidence-fraud" && transaction.is_fraud === 1 && transaction.confidence_score >= 0.4) ||
      (fraudFilter === "low-confidence-fraud" && transaction.is_fraud === 1 && transaction.confidence_score < 0.4) ||
      (fraudFilter === "uncertain-legitimate" && transaction.is_fraud === 0 && transaction.confidence_score < 0.4);

    const matchesDate = !dateFilter || transaction.time.split(" ")[0] === dateFilter;

    const matchesSearch = !searchQuery ||
      transaction.transaction_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      transaction.nameOrig.toLowerCase().includes(searchQuery.toLowerCase()) ||
      transaction.nameDest.toLowerCase().includes(searchQuery.toLowerCase()) ||
      transaction.amount.toString().includes(searchQuery);

    return matchesFraud && matchesDate && matchesSearch;
  });

  const getPredictionColor = (isFraud: number, confidence: number) => {
    if (isFraud === 1 && confidence >= 0.4) {
      return "bg-red-600 text-white"; // High confidence fraud
    } else if (isFraud === 1 && confidence < 0.4) {
      return "bg-red-400 text-white"; // Low confidence fraud
    } else if (isFraud === 0 && confidence < 0.4) {
      return "bg-orange-500 text-white"; // Uncertain legitimate
    } else {
      return "bg-green-600 text-white"; // High confidence legitimate
    }
  };

  const getPredictionText = (isFraud: number, confidence: number) => {
    return isFraud === 1 ? `Fraud (${(confidence * 100).toFixed(1)}%)` : `Not Fraud (${(confidence * 100).toFixed(1)}%)`;
  };

  // Get status label based on fraud classification
  const getStatusLabel = (isFraud: number, confidence: number): { label: string; className: string } | null => {
    if (isFraud === 1 && confidence >= 0.4) {
      // High confidence fraud = Blocked
      return { label: "Blocked", className: "bg-red-900 text-white" };
    } else if (isFraud === 1 && confidence < 0.4) {
      // Low confidence fraud = Suspected (darker)
      return { label: "Suspected", className: "bg-orange-600 text-white" };
    } else if (isFraud === 0 && confidence < 0.4) {
      // Uncertain legitimate = Suspected (lighter)
      return { label: "Suspected", className: "bg-orange-400 text-white" };
    }
    return null; // High confidence legitimate - no label
  };

  const handleVerifyClick = (transaction: Transaction) => {
    setSelectedTransactionForVerify(transaction);
  };

  const handleAnalysisClick = (transactionId: string) => {
    setSelectedTransactionForAnalysis(transactionId);
    setAnalysisDialogOpen(true);
  };

  const handleVerifySubmit = async () => {
    if (!selectedTransactionForVerify || verificationValue === null) return;

    const message = analystMessage.trim();
    setVerifyingTransaction(selectedTransactionForVerify.transaction_id);
    setSelectedTransactionForVerify(null);
    setVerificationValue(null);
    setAnalystMessage("");

    try {
      await axiosInstance.post("/api/feedback/", {
        transactionId: selectedTransactionForVerify.transaction_id,
        groundTruth: verificationValue,
        analyst_message: message || undefined,
      });
      console.log("Transaction count:", transactions.length);

      toast({
        title: "Success",
        description: "Transaction verified successfully",
      });
      // Refresh transactions
      await fetchTransactions();
    } catch (error) {
      console.error("Error verifying transaction:", error);
      toast({
        title: "Error",
        description: "Failed to verify transaction",
        variant: "destructive",
      });
    } finally {
      setVerifyingTransaction(null);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader />
      <main className="container mx-auto px-6 py-4">
        <div className="mb-6">
          <Button
            variant="ghost"
            onClick={() => navigate("/")}
            className="mb-4"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Dashboard
          </Button>
          <h1 className="text-3xl font-bold text-foreground">Transaction Details</h1>
          <p className="text-muted-foreground mt-2">View and analyze all recent transactions by risk level</p>
        </div>

        <Card className="p-6 mb-6">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="flex-1">
              <label className="text-sm font-medium text-foreground mb-2 block">Search Transactions</label>
              <Input
                placeholder="Search by ID, origin, destination, or amount..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setCurrentPage(1);
                }}
                className="w-full"
              />
            </div>
            <div className="flex-1">
              <label className="text-sm font-medium text-foreground mb-2 block">Filter by Classification</label>
              <Select value={fraudFilter} onValueChange={setFraudFilter}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Transactions</SelectItem>
                  <SelectItem value="high-confidence-fraud">High Confidence Fraud (Blocked)</SelectItem>
                  <SelectItem value="low-confidence-fraud">Low Confidence Fraud (Suspected)</SelectItem>
                  <SelectItem value="uncertain-legitimate">Uncertain Legitimate (Suspected)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <label className="text-sm font-medium text-foreground mb-2 block">Filter by Date</label>
              <Input
                type="date"
                value={dateFilter}
                onChange={(e) => setDateFilter(e.target.value)}
                className="w-full cursor-pointer"
                onClick={(e) => {
                  const target = e.target as HTMLInputElement;
                  target.showPicker?.();
                }}
              />
            </div>
          </div>
        </Card>

        <Card className="p-6">
          {!isAuthenticated ? (
            <div className="text-center py-8 text-muted-foreground">Please login to view transaction details</div>
          ) : loading ? (
            <div className="text-center py-8 text-muted-foreground">Loading transactions...</div>
          ) : filteredTransactions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No transactions found</div>
          ) : (
            <>
              <div className="space-y-4">
                {filteredTransactions
                  .slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
                  .map((transaction) => {
                    const statusLabel = getStatusLabel(transaction.is_fraud, transaction.confidence_score);
                    return (
                      <div
                        key={transaction.transaction_id}
                        className="flex items-center justify-between border-b border-border pb-4 last:border-0 last:pb-0 rounded-lg p-4 hover:bg-muted/30 transition-colors cursor-pointer"
                        onClick={() => handleAnalysisClick(transaction.transaction_id)}
                      >
                        <div className="flex items-center gap-4 flex-1">
                          <div className="flex flex-col gap-2 min-w-[160px]">
                            <div className="flex items-center gap-2 flex-wrap">
                              <Badge className={getPredictionColor(transaction.is_fraud, transaction.confidence_score)}>
                                {getPredictionText(transaction.is_fraud, transaction.confidence_score)}
                              </Badge>
                              {statusLabel && (
                                <Badge className={statusLabel.className}>
                                  {statusLabel.label}
                                </Badge>
                              )}
                            </div>
                            {transaction.is_verified ? (
                              <div className="flex items-center gap-2">
                                <Badge className={transaction.ground_truth === 1 ? "bg-red-600 text-white" : "bg-green-600 text-white"}>
                                  {transaction.ground_truth === 1 ? "Fraud" : "Not Fraud"}
                                </Badge>
                                <div className="flex items-center gap-1 text-green-600 text-xs font-medium">
                                  <CheckCircle className="h-3 w-3" />
                                  Verified
                                </div>
                              </div>
                            ) : (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleVerifyClick(transaction);
                                }}
                                disabled={verifyingTransaction === transaction.transaction_id}
                                className="text-xs"
                              >
                                {verifyingTransaction === transaction.transaction_id ? "Validating..." : "Verify Here"}
                              </Button>
                            )}
                          </div>
                          <div className="flex-1">
                            <p className="font-medium text-foreground">
                              Transaction #
                              <span dangerouslySetInnerHTML={{
                                __html: searchQuery ? transaction.transaction_id.replace(
                                  new RegExp(`(${searchQuery})`, 'gi'),
                                  '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                                ) : transaction.transaction_id
                              }} />
                            </p>
                            <p className="text-sm text-muted-foreground mt-1">
                              From: <span className="font-medium">
                                <span dangerouslySetInnerHTML={{
                                  __html: searchQuery ? transaction.nameOrig.replace(
                                    new RegExp(`(${searchQuery})`, 'gi'),
                                    '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                                  ) : transaction.nameOrig
                                }} />
                              </span> → To: <span className="font-medium">
                                <span dangerouslySetInnerHTML={{
                                  __html: searchQuery ? transaction.nameDest.replace(
                                    new RegExp(`(${searchQuery})`, 'gi'),
                                    '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                                  ) : transaction.nameDest
                                }} />
                              </span>
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                              {transaction.time}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleAnalysisClick(transaction.transaction_id);
                            }}
                            className="text-xs"
                          >
                            <Info className="mr-2 h-3 w-3" />
                            Analysis
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedTransactionForSHAP(transaction.transaction_id);
                              setSHAPDialogOpen(true);
                            }}
                            className="text-xs"
                          >
                            <BarChart3 className="mr-2 h-3 w-3" />
                            RCA Report
                          </Button>
                          <p className="font-semibold text-foreground text-lg">
                            $<span dangerouslySetInnerHTML={{
                              __html: searchQuery ? transaction.amount.toFixed(2).replace(
                                new RegExp(`(${searchQuery})`, 'gi'),
                                '<mark class="bg-yellow-300 dark:bg-yellow-600">$1</mark>'
                              ) : transaction.amount.toFixed(2)
                            }} />
                          </p>
                        </div>
                      </div>
                    );
                  })}
              </div>
              {Math.ceil(filteredTransactions.length / itemsPerPage) > 1 && (
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
                      const totalPages = Math.ceil(filteredTransactions.length / itemsPerPage);
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
                    {Math.ceil(filteredTransactions.length / itemsPerPage) > 5 && <PaginationEllipsis />}
                    <PaginationItem>
                      <PaginationNext
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          if (currentPage < Math.ceil(filteredTransactions.length / itemsPerPage)) setCurrentPage(currentPage + 1);
                        }}
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              )}
            </>
          )}
        </Card>

        <Dialog open={!!selectedTransactionForVerify} onOpenChange={(open) => !open && setSelectedTransactionForVerify(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Verify Transaction</DialogTitle>
              <DialogDescription>
                Please verify if this transaction is fraudulent or legitimate.
              </DialogDescription>
            </DialogHeader>
            <div className="py-4">
              <p className="text-sm text-foreground mb-4">
                Transaction #{selectedTransactionForVerify?.transaction_id}
              </p>
              <p className="text-sm text-muted-foreground mb-4">
                Amount: ${selectedTransactionForVerify?.amount.toFixed(2)}
              </p>
              <p className="text-sm text-muted-foreground mb-6">
                {selectedTransactionForVerify?.nameOrig} → {selectedTransactionForVerify?.nameDest}
              </p>
              <div className="space-y-3">
                <Button
                  variant={verificationValue === 1 ? "default" : "outline"}
                  className={verificationValue === 1 ? "w-full bg-red-600 hover:bg-red-700" : "w-full"}
                  onClick={() => setVerificationValue(1)}
                >
                  Mark as Fraud
                </Button>
                <Button
                  variant={verificationValue === 0 ? "default" : "outline"}
                  className={verificationValue === 0 ? "w-full bg-green-600 hover:bg-green-700" : "w-full"}
                  onClick={() => setVerificationValue(0)}
                >
                  Mark as Not Fraud
                </Button>
              </div>
              <div className="mt-4">
                <label className="text-sm font-medium text-foreground mb-2 block">
                  Analyst Notes (optional)
                </label>
                <Textarea
                  placeholder="Add any notes or observations about this transaction..."
                  value={analystMessage}
                  onChange={(e) => setAnalystMessage(e.target.value)}
                  className="min-h-[80px]"
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => {
                setSelectedTransactionForVerify(null);
                setVerificationValue(null);
                setAnalystMessage("");
              }}>
                Cancel
              </Button>
              <Button onClick={handleVerifySubmit} disabled={verificationValue === null}>
                Submit Verification
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <SHAPResultsDialog
          open={shapDialogOpen}
          onOpenChange={setSHAPDialogOpen}
          transactionId={selectedTransactionForSHAP || ""}
        />

        <TransactionAnalysisDialog
          open={analysisDialogOpen}
          onOpenChange={setAnalysisDialogOpen}
          transactionId={selectedTransactionForAnalysis || ""}
        />
      </main>
    </div>
  );
};

export default TransactionDetails;
