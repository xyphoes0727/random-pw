import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { CheckCircle, XCircle, AlertTriangle, FileText, Quote } from "lucide-react";
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"

interface Citation {
  source: string;
  doc_id: string;
  page_no: number;
  snippet: string;
}

interface LLMResult {
  verdict: string;
  confidence: number;
  reasons: string[];
  citations: Citation[];
  structured: Record<string, any>;
}

interface DocumentVerificationResultProps {
  result: {
    type: string;
    conversation_id: string;
    applicant_id: string;
    doc_type: string;
    llm_result: LLMResult;
    similarity_score: number;
    retrieved_count: number;
  };
  fileName?: string; // Passed from parent component
}

export const DocumentVerificationResult = ({ 
  result, 
  fileName 
}: DocumentVerificationResultProps) => {
  const { llm_result, doc_type, similarity_score, retrieved_count } = result;
  
  const getVerdictIcon = () => {
    const verdict = llm_result.verdict.toLowerCase();
    if (verdict === "approve" || verdict === "approved") {
      return <CheckCircle className="h-6 w-6 text-green-600" />;
    } else if (verdict === "reject" || verdict === "deny" || verdict === "denied") {
      return <XCircle className="h-6 w-6 text-red-600" />;
    } else {
      return <AlertTriangle className="h-6 w-6 text-yellow-600" />;
    }
  };

  const getVerdictColor = () => {
    const verdict = llm_result.verdict.toLowerCase();
    if (verdict === "approve" || verdict === "approved") {
      return "bg-green-600";
    } else if (verdict === "reject" || verdict === "deny" || verdict === "denied") {
      return "bg-red-600";
    } else {
      return "bg-yellow-600";
    }
  };

  const formatDocType = (docType: string) => {
    return docType.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  };

  return (
    <div className="space-y-4 mt-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <FileText className="h-5 w-5 text-primary" />
        <span className="font-medium">{fileName || "Uploaded Document"}</span>
        {doc_type && (
          <Badge variant="outline" className="text-xs">
            {formatDocType(doc_type)}
          </Badge>
        )}
      </div>

      {/* Verdict */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {getVerdictIcon()}
            <div>
              <h4 className="font-semibold text-foreground">Verdict</h4>
              <Badge className={getVerdictColor()}>
                {llm_result.verdict.toUpperCase()}
              </Badge>
            </div>
          </div>
          <div className="text-right">
            <p className="text-sm text-muted-foreground">Confidence</p>
            <p className="text-lg font-semibold">
              {(llm_result.confidence * 100).toFixed(0)}%
            </p>
          </div>
        </div>

        <div className="flex gap-4 text-sm text-muted-foreground">
          <span>
            Similarity: {similarity_score !== null && similarity_score !== undefined 
              ? (similarity_score * 100).toFixed(0) 
              : 'N/A'}%
          </span>
          <span>•</span>
          <span>{retrieved_count} documents retrieved</span>
        </div>
      </Card>

      {/* Reasons */}
      {llm_result.reasons && llm_result.reasons.length > 0 && (
        <Card className="p-4">
          <h4 className="font-semibold text-foreground mb-3">Analysis Reasons</h4>
          <ul className="space-y-2">
            {llm_result.reasons.map((reason, idx) => (
              <li key={idx} className="flex items-start gap-2 text-sm">
                <CheckCircle className="h-4 w-4 text-green-600 mt-0.5 flex-shrink-0" />
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Citations */}
      {llm_result.citations && llm_result.citations.length > 0 && (
        <Card className="p-4">
          <h4 className="font-semibold text-foreground mb-3 flex items-center gap-2">
            <Quote className="h-4 w-4" />
            Citations
          </h4>
          <div className="space-y-3">
            {llm_result.citations.map((citation, idx) => (
              <div key={idx} className="bg-muted/50 rounded-lg p-3 text-sm">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="outline" className="text-xs">
                    {citation.source}
                  </Badge>
                  <span className="text-muted-foreground">
                    Page {citation.page_no}
                  </span>
                </div>
                <p className="text-foreground italic">"{citation.snippet}"</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};