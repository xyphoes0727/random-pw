"""
Document verification agent for the fraud_ingest application.


This module provides a single public entrypoint `analyze_documents` which:
- saves an uploaded PDF to a temporary file,
- extracts text using pdfminer (and optionally falls back to OCR),
- queries a Pathway-based vector store for similar documents,
- builds a compact RAG context and calls an LLM to produce a JSON verdict,
- returns structured results including similarity metrics and LLM output.


Configuration (via environment variables):
- PATHWAY_VECTORSTORE_URL,
- OPENAI_API_KEY

"""

import os
import json
import tempfile
import traceback
from typing import Optional, List, Dict, Any
from rest_framework.response import Response
from rest_framework import status
from loguru import logger
from openai import OpenAI
from dotenv import load_dotenv
from .constants import system_prompt_doc_agent, MODEL
import time
load_dotenv()


try:
    from .vectorClient import VectorStoreClientModified
except Exception:
    VectorStoreClientModified = None

# ------------------ Helpers function for converting pdf to text------------------
def _save_temp_file(
    uploaded_files: Any
) -> str:
    """Save a Django UploadedFile-like object to a temporary file and return path.
    Storing on disk currently and expect a file path (pdfminer, pdf2image) can access it.
    Cleanup for clearing the temp file using tmp.close().
"""
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        for chunk in uploaded_files.chunks():
            tmp.write(chunk)
        tmp.flush()
        tmp.close()
        logger.debug(f"Saved uploaded file to temporary path:{tmp.name}",)
        return tmp.name
    except Exception:
        logger.exception("Failed to save uploaded file to temp path")
        raise


# ------------------ Actual extraction------------------
def _extract_text_from_pdf(
    path: str
) -> str:
    """
    Try to extract text using pdfminer. Returns empty string on failure.
    """
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(path) or ""
        return text.strip()
    except Exception as e:
        logger.debug(f"pdfminer extraction failed: {e}")
        return ""


def _ocr_fallback_pdf(path: str) -> str:
    """
    Try OCR fallback using pdf2image + pytesseract.
    Returns extracted text or empty string on failure.
    """
    try:
        import pdf2image
        import pytesseract
        from PIL import Image
    except Exception as e:
        logger.debug(f"OCR libs not available or failed import: {e}")
        return ""

    try:
        pages = pdf2image.convert_from_path(path, dpi=300)
        texts = []
        for page in pages:
            texts.append(pytesseract.image_to_string(page))
        return "\n".join(texts).strip()
    except Exception as e:
        logger.debug(f"OCR conversion failed: {e}")
        return ""


def _make_pathway_client() -> Optional[object]:
    """
    Create a Pathway VectorStore client instance. Returns None if not configured.
    """
    url = os.getenv("PATHWAY_VECTORSTORE_URL")
    api_key = os.getenv("PATHWAY_VECTORSTORE_API_KEY", "")
    logger.info(f"Credentials:-------->{url}{api_key}")
    if not url or VectorStoreClientModified is None:
        logger.error(
            "Pathway VectorStore client not configured or not importable.")
        return None
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        return VectorStoreClientModified(
            host=os.environ.get("VECTOR_DB_HOST"),
            port=os.environ.get("VECTOR_DB_PORT"))
    except Exception as e:
        logger.exception(f"Failed to instantiate Pathway client: {e}")
        return None


def _query_pathway(text: str, k: int = 6, metadata_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Query Pathway server. Returns list of matches (dicts).
    Pathway server does embedding internally.
    """
    client = _make_pathway_client()
    logger.debug("Instantiated Pathway client")

    if client is None:
        logger.error("Pathway client unavailable")
        raise RuntimeError("Pathway client unavailable")

    logger.debug(
        f"Querying Pathway (k={k}, metadata_filter={metadata_filter}), query_preview={text}")
    try:
        res = client.query(text, k=k, metadata_filter=metadata_filter)
        logger.debug(f"Pathway query returned type={type(res)}")
    except Exception as e:
        logger.exception(f"Pathway client query failed: {e}", e)
        raise
    if isinstance(res, dict):
        logger.info(f"_QUERY PATHWAY1 {res}")
        return res.get("matches", []) or []
    if isinstance(res, list):
        logger.info(f"_QUERY PATHWAY 2{res}")
        return res
    return []


def _truncate(s: str, n: int = 1200) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + " ...(truncated)"


def _compute_similarity_stats(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute a few simple similarity metrics from Pathway matches.
    Returns min_dist, mean_dist, score (0..1 where 1 is best).
    """
    if not matches:
        return {"min_dist": None, "mean_dist": None, "score": 0.0}
    dists = []
    for m in matches:
        try:
            d = float(m.get("dist", 1.0))
        except Exception:
            d = 1.0
        dists.append(d)
    min_dist = min(dists)

    mean_dist = sum(dists) / len(dists) if dists else None
    score = max(0.0, 1.0 - min_dist) if min_dist is not None else 0.0
    logger.info(f"Stats:{min_dist}:{mean_dist}:{score}")
    return {"min_dist": min_dist, "mean_dist": mean_dist, "score": score}


def _build_rag_context(matches: List[Dict[str, Any]], top_n: int = 6) -> Dict[str, Any]:
    """
    Build compact RAG context and citation list from matches returned by Pathway client.
    """
    retrieved = []
    context_parts = []
    citations = []
    top_n = min(top_n, len(matches))
    for m in matches[:top_n]:
        md = m.get("metadata") or {}
        logger.info(f"md:{md}")
        doc_id = md.get("doc_id") or md.get("filepath") or m.get("id")
        logger.info(f"doc_id:{doc_id}")

        page_no = md.get("page_no") or md.get("page")
        logger.info(f"page_no:{page_no}")

        src = md.get("doc_type") or md.get("source") or "doc"
        logger.info(f"src:{src}")

        text = m.get("text") or m.get("content") or m.get("snippet") or ""
        logger.info(f"text:{text}")
        snippet = _truncate(text, 1200)
        retrieved.append({"id": m.get("id"), "dist": m.get(
            "dist"), "metadata": md, "text": snippet})
        context_parts.append(
            f"[{src}][doc_id:{doc_id}][page:{page_no}]\n{snippet}")
        citations.append({"source": src, "doc_id": doc_id,
                        "page_no": page_no, "snippet": snippet})
    rag_context = "\n\n".join(context_parts)[:20000]
    return {"retrieved": retrieved, "citations": citations, "rag_context": rag_context}


def _call_llm(question: str, rag_context: str, similarity_stats: Dict[str, Any], temperature: float = 0.0) -> str:
    """Call OpenAI and return raw text."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    client_chat = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = system_prompt_doc_agent

    # include simple similarity metrics to help LLM reason about closeness
    similarity_text = (
        f"Similarity metrics: min_dist={similarity_stats.get('min_dist')}, "
        f"mean_dist={similarity_stats.get('mean_dist')}, "
        f"score={similarity_stats.get('score')}\n"
    )
    logger.info(f"similarity_text{similarity_text}")
    user_prompt = (
        f"{question}\n\nCONTEXT:\n{rag_context}\n\n{similarity_text}\n"
        "Answer in JSON only."
    )

    try:
        resp = client_chat.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
        )
        logger.info(f"LLM response:{resp}")
        content = None
        try:
            content = resp.choices[0].message.content
        except Exception:
            try:
                content = resp["choices"][0]["message"]["content"]
            except Exception:
                content = str(resp)
        return content

    except Exception as e:
        logger.exception(f"LLM invocation failed: {e}")
        raise


def _parse_json_from_text(text: str) -> Any:
    """ if in any case llm doesn't return proper json, 
    this function tries to extract json from text."""
    if not text:
        return {"raw": ""}
    try:
        return json.loads(text)
    except Exception:
        # Try to find the first JSON object inside text
        try:
            s = text.find("{")
            e = text.rfind("}")
            if s != -1 and e != -1 and e > s:
                candidate = text[s:e+1]
                return json.loads(candidate)
        except Exception:
            logger.debug("Failed to parse LLM JSON")
    # fallback: return raw text packaged
    return {"raw": text}


# ---------- Entrypoint ----------
def analyze_documents(
    uploaded_file,
    applicant_id: Optional[str] = None,
    question: Optional[str] = None,
    k: int = 6,
    metadata_filter: Optional[str] = None,
    ocr_fallback: bool = True,
    doc_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main function to call from views.
    Behavior and logging:
    - Validates inputs early and returns friendly errors for missing parameters.
    - Saves incoming upload to a temp file, extracts text (pdfminer), optionally OCRs.
    - Queries Pathway VectorStore for similar documents using `applicant_id` as filter.
    - Builds RAG context and invokes an LLM to produce a JSON verdict.
    - Returns a structured payload including similarity stats, retrieved items, LLM raw output and parsed JSON.
"""
    start_ts = time.time()
    logger.info(
        f"analyze_documents invoked applicant_id={applicant_id} doc_type={doc_type} k={k} ocr_fallback={ocr_fallback}")

    if not uploaded_file:
        logger.warning("No uploaded_file provided to analyze_documents")
        return {"error": "No file provided"}

    if not question:
        question = "Are the applicant's income documents consistent across the provided files?"

    tmp_path = None
    try:
        # save uploaded file
        tmp_path = _save_temp_file(uploaded_file)

        # extract text
        text = _extract_text_from_pdf(tmp_path)
        if (not text or len(text.strip()) < 50) and ocr_fallback:
            logger.info("PDF text minimal — attempting OCR fallback")
            text = _ocr_fallback_pdf(tmp_path) or text

        if not text or not text.strip():
            logger.warning(
                "No extractable text found in PDF after extraction and OCR fallback")
            return {"error": "No extractable text found in PDF. Provide text PDF or enable OCR."}

        logger.debug(f"Extracted text length={len(text)}")

        mf = metadata_filter
        logger.debug(f"Using metadata_filter={mf}")
        # mf = metadata_filter
        # if not mf and applicant_id:
        #     mf = f"applicant_id=='{applicant_id}'"
        #     if doc_type:
        #         mf += f" and doc_type=='{doc_type}'"

        # query Pathway
        try:
            matches = _query_pathway(text, k=max(1, k), metadata_filter=mf)
            logger.info(f"Pathway returned {len(matches)} matches")
        except RuntimeError:
            logger.error("Pathway client is unavailable (caught RuntimeError)")
            return {"error": "Document retrieval backend not configured. Please contact the administrator"}
        except Exception as e:
            logger.exception("Pathway query failed")
            return {"error": "Document retrieval temporarily unavailable. Please try again later."}

        # similarity metrics
        similarity_stats = _compute_similarity_stats(matches)
        logger.info(f"Printed {similarity_stats}")
        rag = _build_rag_context(matches, top_n=min(6, int(k)))
        logger.info(f"RAG:{rag}")
        # call LLM (pass similarity metrics)
        try:
            llm_raw = _call_llm(
                # <<< CHANGED
                question, rag["rag_context"], similarity_stats, temperature=0.0)
        except Exception as e:
            logger.exception(
                f"LLM call failed while sending docs and similarity stats: {e}")
            return {"error": "Document analysis service temporarily unavailable. Please try again later."}

        llm_parsed = _parse_json_from_text(llm_raw)
        logger.info("LLM response parsed successfully")
        duration = time.time() - start_ts
        logger.info(f"analyze_documents completed in {duration}s")

        # return structured payload
        return {
            "ok": True,
            "applicant_id": applicant_id,
            "doc_type": doc_type,
            "retrieved_count": len(rag["retrieved"]),
            "retrieved": rag["retrieved"],
            "citations": rag["citations"],
            "similarity": similarity_stats,
            "llm_raw": llm_raw,
            "llm_result": llm_parsed,
        }

    except Exception as exc:
        logger.exception(
            f"analyze_documents unexpected error: {traceback.format_exc()}")
        return {"error": "Internal server error", "detail": str(exc)}

    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
                logger.debug(f"Removed temporary file: {tmp_path}")
            except Exception:
                logger.debug(f"Failed to remove temporary file: {tmp_path}")


def verify_loan_documents(request) -> Response:
    """
    Backwards-compatible wrapper.This function returns a DRF Response.
    """
    try:
        uploaded = request.FILES.get("file")
        applicant_id = request.data.get(
            "applicant_id") or request.data.get("applicantId")
        question = request.data.get("question")
        k = int(request.data.get("k", 6)) if request.data.get("k") else 6

        result = analyze_documents(
            uploaded, applicant_id=applicant_id, question=question, k=k)
        # if service returns dict, wrap with Response
        if result.get("error"):
            return Response(result, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.exception("verify_loan_documents wrapper failed")
        return Response({"error": "Internal server error", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
