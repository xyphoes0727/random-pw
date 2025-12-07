import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";

interface Transaction {
  id: string;
  transactionId: string;
  description: string;
  amount: string;
  time: string;
  date: string;
  risk: "high" | "medium" | "low";
  sender: string;
  receiver: string;
  location: string;
}

interface SARReportDialogProps {
  transaction: Transaction;
  open: boolean;
  onClose: () => void;
}

export const SARReportDialog = ({ transaction, open, onClose }: SARReportDialogProps) => {
  const getRiskBadgeVariant = (risk: string) => {
    switch (risk) {
      case "high":
        return "destructive";
      case "medium":
        return "default";
      case "low":
        return "secondary";
      default:
        return "default";
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[90vh]">
        <DialogHeader>
          <DialogTitle className="text-2xl">Suspicious Activity Report (SAR)</DialogTitle>
        </DialogHeader>
        <ScrollArea className="max-h-[calc(90vh-120px)]">
          <div className="space-y-6 pr-4">
            {/* Transaction Overview */}
            <div>
              <h3 className="text-lg font-semibold mb-3 text-foreground">Transaction Overview</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Transaction ID</p>
                  <p className="font-medium text-foreground">{transaction.transactionId}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Risk Level</p>
                  <Badge variant={getRiskBadgeVariant(transaction.risk)} className="mt-1">
                    {transaction.risk.toUpperCase()}
                  </Badge>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Amount</p>
                  <p className="font-medium text-foreground">{transaction.amount}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Date</p>
                  <p className="font-medium text-foreground">{transaction.date}</p>
                </div>
              </div>
            </div>

            <Separator />

            {/* Parties Involved */}
            <div>
              <h3 className="text-lg font-semibold mb-3 text-foreground">Parties Involved</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Sender</p>
                  <p className="font-medium text-foreground">{transaction.sender}</p>
                  <p className="text-xs text-muted-foreground mt-1">Account: ACC-{transaction.id}001</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Receiver</p>
                  <p className="font-medium text-foreground">{transaction.receiver}</p>
                  <p className="text-xs text-muted-foreground mt-1">Account: ACC-{transaction.id}002</p>
                </div>
                <div className="col-span-2">
                  <p className="text-sm text-muted-foreground">Location</p>
                  <p className="font-medium text-foreground">{transaction.location}</p>
                </div>
              </div>
            </div>

            <Separator />

            {/* Suspicious Activity Details */}
            <div>
              <h3 className="text-lg font-semibold mb-3 text-foreground">Suspicious Activity Details</h3>
              <div className="space-y-3">
                <div>
                  <p className="text-sm font-medium text-foreground">Description</p>
                  <p className="text-sm text-muted-foreground mt-1">{transaction.description}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">Red Flags Identified</p>
                  <ul className="list-disc list-inside text-sm text-muted-foreground mt-1 space-y-1">
                    {transaction.risk === "high" && (
                      <>
                        <li>Transaction amount exceeds typical pattern by 300%</li>
                        <li>High-risk jurisdiction involved in transaction</li>
                        <li>Rapid succession of similar transactions detected</li>
                        <li>Incomplete beneficiary information</li>
                      </>
                    )}
                    {transaction.risk === "medium" && (
                      <>
                        <li>Transaction pattern slightly unusual</li>
                        <li>First-time transaction with this beneficiary</li>
                        <li>Amount slightly above normal threshold</li>
                      </>
                    )}
                    {transaction.risk === "low" && (
                      <>
                        <li>Transaction within normal parameters</li>
                        <li>Established relationship with beneficiary</li>
                        <li>All documentation complete</li>
                      </>
                    )}
                  </ul>
                </div>
              </div>
            </div>

            <Separator />

            {/* Risk Assessment */}
            <div>
              <h3 className="text-lg font-semibold mb-3 text-foreground">Risk Assessment</h3>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">ML Model Score</p>
                    <p className="font-medium text-foreground">
                      {transaction.risk === "high" ? "0.89" : transaction.risk === "medium" ? "0.65" : "0.23"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Rule Engine Score</p>
                    <p className="font-medium text-foreground">
                      {transaction.risk === "high" ? "0.92" : transaction.risk === "medium" ? "0.58" : "0.18"}
                    </p>
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">Recommended Actions</p>
                  <ul className="list-disc list-inside text-sm text-muted-foreground mt-1 space-y-1">
                    {transaction.risk === "high" && (
                      <>
                        <li>Immediate manual review required</li>
                        <li>Contact compliance team</li>
                        <li>File SAR with regulatory authorities</li>
                        <li>Consider transaction hold</li>
                      </>
                    )}
                    {transaction.risk === "medium" && (
                      <>
                        <li>Enhanced monitoring for 30 days</li>
                        <li>Request additional documentation</li>
                        <li>Secondary review recommended</li>
                      </>
                    )}
                    {transaction.risk === "low" && (
                      <>
                        <li>Standard processing</li>
                        <li>Routine monitoring</li>
                        <li>No immediate action required</li>
                      </>
                    )}
                  </ul>
                </div>
              </div>
            </div>

            <Separator />

            {/* Historical Context */}
            <div>
              <h3 className="text-lg font-semibold mb-3 text-foreground">Historical Context</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Previous Transactions (30 days)</span>
                  <span className="font-medium text-foreground">
                    {transaction.risk === "high" ? "23" : transaction.risk === "medium" ? "45" : "127"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Average Transaction Value</span>
                  <span className="font-medium text-foreground">
                    {transaction.risk === "high" ? "$2,450" : transaction.risk === "medium" ? "$3,120" : "$1,850"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Account Age</span>
                  <span className="font-medium text-foreground">
                    {transaction.risk === "high" ? "2 months" : transaction.risk === "medium" ? "8 months" : "3 years"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Previous Alerts</span>
                  <span className="font-medium text-foreground">
                    {transaction.risk === "high" ? "3" : transaction.risk === "medium" ? "1" : "0"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
};
