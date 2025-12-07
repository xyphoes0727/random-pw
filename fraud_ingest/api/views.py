"""
Django REST Framework Views defining the API endpoints for the fraud detection
and analytics application.

The views handle user registration, global statistics, transaction fetching,
ML explainability (SHAP/RCA), Kafka feedback publishing, metrics calculation,
chatbot interaction, and internal task scheduling.
"""

from .tasks import model_health_task
from .tasks import send_email_task, llm_task
from .shap_runner import get_shap_values, generate_llm_rca
from django.db.models.functions import Cast

from django.conf import settings
import math
import time
from .serializers import (
    EnrichedSerializer, MLPredictionSerializer, UserRegistrationSerializer)
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework import viewsets, status
from django.db.models import Sum,  F, Count, BigIntegerField, Q
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.http import JsonResponse, StreamingHttpResponse
import json
import datetime
from django.views.decorators.csrf import csrf_exempt
from log_config.log_config import get_logger
from .models import Enriched, MLPrediction, Metrics, User
from kafka import KafkaProducer
from kafka.errors import KafkaError
import os
from .doc_verify_agent import analyze_documents
from .chatbot import (
    chat_plot_with_context,
    chat_stream_with_context,
    is_plot_intent,
    clear_conversation,
    get_conversation_context,
    get_or_create_conversation,
    add_to_conversation,
    MAX_INPUT_CHARS
)

DOCUMENT_VERIFICATION_TTL = 86400
logger = get_logger(__name__)


ONE_DAY_MS = 24 * 60 * 60 * 1000
FIVE_MIN_MS = 60*1000


class UserRegistrationView(CreateAPIView):
    """
    API endpoint for **new user registration**.

    Endpoint: `/api/register/` (POST)
    Permission: AllowAny

    Required Data:
        - `username`
        - `email`
        - `password`
        - `password2` (confirmation)
    """
    logger.debug("Came to Signup")
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]


class GlobalStatsAPIView(APIView):
    """
    API endpoint to retrieve high-level aggregated statistics
    for the dashboard.

    Endpoint: `/api/stats/` (GET)

    Returns:
        - `total_transactions`: Total MLPrediction records.
        - `total_fraud_count`: Count of records where `isFraud=1` or
            `ground_truth=1`.
        - `total_suspected_count`: Count of records with label="suspected".
        - `protected_amount`: Total transaction amount associated with
            fraud/suspected fraud.
    """

    def get(self, request, *args, **kwargs):
        try:

            fraud_transactions = MLPrediction.objects.filter(
                Q(isFraud=1) | Q(ground_truth=1)
            )
            suspected_transactions = MLPrediction.objects.filter(
                label="suspected")

            total_transactions = MLPrediction.objects.count()
            total_fraud_count = fraud_transactions.count()
            total_suspected_count = suspected_transactions.count()

            protected_amount_data = fraud_transactions.aggregate(
                total=Sum('amount'))
            protected_amount = protected_amount_data['total'] or 0.0

            stats = {
                'total_transactions': total_transactions,
                'total_fraud_count': total_fraud_count,
                'total_suspected_count': total_suspected_count,
                'protected_amount': protected_amount,
            }
            return Response(stats, status=status.HTTP_200_OK)

        except Exception:
            return Response(
                {"error": "An error occurred while calculating stats."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TimeFilterMixin:
    """
    Mixin to filter querysets based on optional URL query parameters:
    - `start_time` (epoch milliseconds)
    - `end_time` (epoch milliseconds, defaults to now)
    """

    def get_queryset(self):
        queryset = super().get_queryset()

        start_time_str = self.request.query_params.get('start_time')
        end_time_str = self.request.query_params.get('end_time')

        now_ms = int(timezone.now().timestamp() * 1000)

        try:
            end_time = int(end_time_str) if end_time_str else now_ms
        except (ValueError, TypeError):
            end_time = now_ms

        queryset = queryset.filter(time__lte=end_time)

        if start_time_str:
            try:
                start_time = int(start_time_str)
                queryset = queryset.filter(time__gte=start_time)
            except (ValueError, TypeError):
                pass

        return queryset


class EnrichedTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for accessing Enriched transaction data.

    Endpoint: `/api/transactions/` (GET)

    List Action (`/api/transactions/`):
        Returns a time-bucketed histogram of transaction counts.
        - Required Query Param: `start_time` (epoch ms)
        - Optional Query Params: `end_time` (epoch ms), `intervals`
        - Output: List of `{'time': timestamp, 'count': value}`.

    Retrieve Action (`/api/transactions/{id}/`):
        Returns full details of a single enriched transaction.
    """
    queryset = Enriched.objects.all().order_by('-time')
    serializer_class = EnrichedSerializer

    def list(self, request, *args, **kwargs):
        start_time_str = request.query_params.get('start_time')
        end_time_str = request.query_params.get('end_time')
        intervals_str = request.query_params.get('intervals', '180')

        if not start_time_str:
            return Response(
                {"error": "The 'start_time' query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_time = int(start_time_str)
            num_intervals = int(intervals_str)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid 'start_time' or 'intervals'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if num_intervals <= 0:
            return Response(
                {"error": "'intervals' must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST
            )

        now_ms = int(timezone.now().timestamp() * 1000)
        try:
            end_time = int(end_time_str) if end_time_str else now_ms
        except (ValueError, TypeError):
            end_time = now_ms

        if start_time >= end_time:
            return Response(
                {"error": "'start_time' must be less than 'end_time'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        total_duration = end_time - start_time
        interval_size = math.ceil(total_duration / num_intervals)
        end_time += interval_size
        if interval_size == 0:
            interval_size = 1

        logger.debug("Before Db_results")
        db_results = Enriched.objects \
            .filter(time__gte=start_time, time__lte=end_time) \
            .annotate(
                interval_bucket=Cast(
                    (F('time') - start_time) / interval_size,
                    output_field=BigIntegerField()
                ) * interval_size + start_time
            ) \
            .values('interval_bucket') \
            .annotate(count=Count('transactionId')) \
            .order_by('interval_bucket')
        logger.debug(f"After Db_results {db_results}")

        results_map = {
            item["interval_bucket"]: item["count"]
            for item in db_results
        }

        final_data = []
        current_time = start_time

        while current_time < end_time:
            final_data.append({
                'time': current_time,
                'count': results_map.get(current_time, 0)
            })
            current_time += interval_size

        return Response(final_data, status=status.HTTP_200_OK)


class MLPredictionViewSet(TimeFilterMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for accessing Machine Learning Prediction data.

    Endpoint: `/api/predictions/` (GET)

    List/Retrieve actions support time filtering via `TimeFilterMixin`
    (`start_time` and `end_time` query parameters on the `time` field).
    """
    queryset = MLPrediction.objects.all().order_by('-time')
    serializer_class = MLPredictionSerializer


FEATURE_COLS = [
    "transaction_type",
    "amount",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",

    "mean_amount",
    "stddev_amount",
    "max_amount_seen",
    "min_amount_seen",

    "user_txn_count",
    "txn_count_in_step",
    "total_amount_in_step",

    "sender_out_degree",
    "sender_in_degree",
    "sender_fraud_ratio",
    "pagerank",
    "amount_to_profile_ratio",
    "amount_to_balance_ratio",

    "logamount",

    "diff",
    "origMoreSent",
    "destMoreRec",
    "origMoreSentFlag",
    "destMoreRecFlag",
    "step"
]


class ShapValuesView(APIView):
    """
    ShapValuesView(APIView)

    POST endpoint that computes SHAP feature importances for a specified transaction
    and generates an RCA (root-cause analysis) report URL via an LLM helper.

    Request:
        - Expects a JSON body with:
            - transactionId (str): required identifier of the transaction to analyze.

    Responses:
        - 200 OK: JSON with keys:
            - "rca_report_link": str (URL to the generated RCA report)
            - "feature_importances": dict (SHAP-derived importances / explanations)
        - 400 Bad Request: {"error": "transactionId is required"} if transactionId is missing.
        - 500 Internal Server Error: {"error": "<message>"} for parsing, DB, SHAP, LLM errors
          or other unexpected exceptions.  

    Example:
        POST payload: {"transactionId": "txn_12345"}
    """

    def post(self, request, *args, **kwargs):
        logger.info("Received SHAP values request.")

        try:
            data = json.loads(request.body)
            transactionId = data.get("transactionId")

            if not transactionId:
                return Response(
                    {"error": "transactionId is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.debug(f"SHAP values request for ID: {transactionId}")

            enriched = Enriched.objects.filter(
                transactionId=transactionId
            ).first()

            mlPred = MLPrediction.objects.filter(
                transaction=transactionId
            ).first()

            transactionData = {}

            if enriched:
                for col in FEATURE_COLS:
                    if hasattr(enriched, col):
                        transactionData[col] = getattr(enriched, col)
                    else:
                        transactionData[col] = 0

                if hasattr(enriched, "type") and "transaction_type" in FEATURE_COLS:
                    transactionData["transaction_type"] = getattr(
                        enriched, "type")

                logger.debug(f"Enriched txns: {transactionData}")
            else:
                transactionData = {}

            if mlPred:
                mlData = {
                    "fraud_probability": mlPred.fraud_probability,
                    "confidence_score": mlPred.confidence_score,
                    "model_predicted_label": mlPred.isFraud
                }
                logger.debug(f"mlPreds: {mlPred}")
            else:
                mlData = {}

            excludeForShap = ["trust_score"]

            dataForShap = {
                k: v for k, v in transactionData.items()
                if k not in excludeForShap
            }

            logger.debug(f"Data for SHAP: {dataForShap}")

            result = get_shap_values(dataForShap)

            logger.debug(f"SHAP result: {result}")

            report_url = generate_llm_rca(
                transactionData, mlData, result
            )

            logger.debug(f"RCA report url: {report_url}")

            if report_url:
                logger.info("Response 200 by shap")
                return Response(
                    {
                        "rca_report_link": report_url,
                        "feature_importances": result["feature_importances"],
                    },
                    status=status.HTTP_200_OK
                )

            return Response(
                {"error": "Failed to generate RCA report"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except Exception as e:
            logger.error(
                f"Critical error in ShapValuesView: {str(e)}",
                exc_info=True
            )
            return Response(
                {"error": f"Error calculating SHAP values: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class KafkaProducerView(APIView):
    """
    API endpoint to submit human ground truth feedback for a transaction.

    Endpoint: `/api/feedback/` (POST)

    Required Data:
        - `transactionId`: ID of the transaction.
        - `groundTruth`: The true label (0 or 1).

    Action:
        1. Updates the `MLPrediction` record in the database
        (`is_verified_human`, `ground_truth`).
        2. Publishes the updated enriched transaction data and
        `groundTruth` to the Kafka `ground-truth` topic.
    """

    def post(self, request, *args, **kwargs):
        logger.info("Received feedback submission request.")
        transaction_id = request.data.get('transactionId')
        ground_truth = request.data.get('groundTruth')
        logger.info(
            f"Received Message from feedback: {transaction_id} {ground_truth}")

        if not transaction_id:
            logger.warning("KafkaProducerView: Missing 'transactionId'.")
            return Response(
                {"error": "'transactionId' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if ground_truth is None:
            logger.warning("KafkaProducerView: Missing 'groundTruth'.")
            return Response(
                {"error": "'groundTruth' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            MLPrediction.objects.select_related("transaction").filter(
                transaction__transactionId=transaction_id).update(
                    is_verified_human=True,
                    ground_truth=ground_truth,
                    verification_time=int(timezone.now().timestamp() * 1000)
            )
            enriched_obj = Enriched.objects.get(transactionId=transaction_id)
            serializer = EnrichedSerializer(enriched_obj)
            data_to_send = serializer.data

            data_to_send['groundTruth'] = ground_truth

            producer = None
            try:
                producer = KafkaProducer(
                    bootstrap_servers=os.getenv(
                        "KAFKA_BOOTSTRAP", "kafka:9093"),
                    value_serializer=lambda v: json.dumps(v).encode('utf-8')
                )

                topic = os.getenv("KAFKA_FEEDBACK_TOPIC", "ground-truth")

                logger.info(
                    f"Sending feedback for {transaction_id} to topic {topic}")
                producer.send(topic, value=data_to_send)
                producer.flush()
                logger.info(
                    f"Successfully sent feedback for {transaction_id}.")

            except KafkaError as ke:
                logger.error(
                    f"Kafka error while sending feedback for :{ke}")
                return Response(
                    {"error": "Failed to send data to messaging system."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            finally:
                if producer:
                    producer.close()

            return Response(
                {"message": "Feedback submitted successfully."},
                status=status.HTTP_200_OK
            )

        except Enriched.DoesNotExist:
            logger.warning(
                f"Feedback request for non-existent:{transaction_id}"
            )
            return Response(
                {"error": f"Transaction with id {transaction_id} not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(
                f"Unexpected error for {transaction_id}: {e}")
            return Response(
                {"error": "An unexpected error occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@csrf_exempt
def get_transaction_details(request):
    """
    Function-based API endpoint to retrieve a curated list of transactions
    for the fraud review queue.

    Endpoint: `/api/transaction_details/` (GET)

    Filter: Excludes transactions with low confidence score (<=0.4)
    that are non-fraud (isFraud=0).

    Returns: A JSON list of transactions with key fields (ID, amount,
    confidence, fraud label, time, verification status).
    """
    if request.method != "GET":
        return JsonResponse({
            "error": "Only GET Method Allowed"},
            status=405
        )

    try:
        logger.info("Fetching all the transactions")
        required_transactions = (
            MLPrediction.objects
            .select_related("transaction")
            .exclude(confidence_score__gt=0.4, isFraud=0)
            .values(
                "amount",
                "confidence_score",
                "isFraud",
                "is_verified_human",
                "is_verified_system",
                "ground_truth",
                "transaction__transactionId",
                "transaction__nameOrig",
                "transaction__nameDest",
                "transaction__time"
            )
        )

        if not required_transactions:
            return JsonResponse(
                {"message": "Transactions not available"},
                status=404
            )
        result = []

        for transaction in required_transactions:
            if transaction["transaction__time"]:
                try:
                    timestamp_ns = int(transaction["transaction__time"])
                    timestamp_s = timestamp_ns / 1e3
                    transaction["transaction__time"] = (
                        datetime.datetime.fromtimestamp(timestamp_s)
                        .strftime("%Y-%m-%d %H:%M:%S")
                    )
                except Exception:
                    transaction["transaction__time"] = None

            result.append({
                "transaction_id": transaction["transaction__transactionId"],
                "amount": transaction["amount"],
                "confidence_score": transaction["confidence_score"],
                "is_fraud": transaction["isFraud"],
                "nameOrig": transaction["transaction__nameOrig"],
                "nameDest": transaction["transaction__nameDest"],
                "time": transaction["transaction__time"],
                "is_verified": (
                    transaction["is_verified_human"]
                    or transaction["is_verified_system"]
                ),
                "ground_truth": transaction["ground_truth"]
            })

        logger.info(f"Fetched {len(result)} transactions successfully")
        return JsonResponse(result, safe=False)
    except Exception:
        return JsonResponse({
            "error": "Failed to fetch transaction details:"
        }, status=500)


def normalize_epoch_ms(epoch):
    if epoch is None:
        return None
    try:
        v = int(epoch)
        1_762_903_912_738
        if v > 1_000_000_000_000:
            return v // 1_000_000
        elif v > 1_000_000_000:
            return v * 1000
        else:
            return v
    except (ValueError, TypeError):
        return None


def truth_str_to_bool(s):
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in {"fraud", "fraudulent", "1", "true"}:
        return True
    if s in {
            "not_fraud", "not-fraud", "legit",
            "0", "false", "non-fraud", "nonfraud"
    }:
        return False
    return None


class ConfusionMatrixAPI(APIView):
    """
    API endpoint to retrieve ML model performance metrics and
    data distribution insights.

    Endpoint: `/api/metrics/` (GET)

    Action:
        1. Calculates delta metrics (TP, FP, TN, FN) for newly verified
        transactions.
        2. Updates the `Metrics` table with cumulative performance data
        (Accuracy, Precision, Recall, F1, etc.).

    Returns:
        - `CONFUSION_MATRIX`: Latest cumulative TP/FP/TN/FN and calculated
        scores.
        - `ROC_CURVE`: List of TPR/FPR values (historical metrics).
        - `PRECISION_RECALL`: List of Precision/Recall values.
        - `FRAUD_COUNT_TYPE`: Distribution of fraud/suspected fraud
        by transaction type.
        - `FRAUD_PROB_AMOUNT`: Distribution of fraud probability
        vs. transaction amount.
    """

    def get(self, request, *args, **kwargs):
        now_ms = int(timezone.now().timestamp() * 1000)

        last = Metrics.objects.all().order_by('-calculated_at').first()
        logger.info("Last metrics fetched:")
        tp = last.tp or 0 if last else 0
        fp = last.fp or 0 if last else 0
        tn = last.tn or 0 if last else 0
        fn = last.fn or 0 if last else 0
        last_watermark = last.watermark_ms or 0 if last else 0

        logger.info(f"Metrics {tp},{fp},{tn},{fn},{last_watermark}")

        qs = (
            MLPrediction.objects
            .select_related("transaction")
            .filter(is_counted_metrics=False)
            .values(
                "transaction__transactionId",
                "isFraud",
                "is_verified_human",
                "ground_truth",
                "time",
                "verification_time",
            )
        )
        logger.info(
            "Fecthed details from MLprediction for confusion matrix calc."
        )

        d_tp = d_fp = d_tn = d_fn = 0

        processed_ids = []
        for r in qs:

            model_label = bool(r["isFraud"])
            pred_time_ms = (r.get("time"))
            verify_time_ms = (r.get("verification_time"))
            eff_time, eff_gt = None, None
            if r["is_verified_human"]:
                logger.debug("Using human verification for ground truth.")
                eff_time = verify_time_ms
                eff_gt = bool(r.get("ground_truth"))
                logger.debug(
                    f"Effective time: {eff_time}, Effective g truth: {eff_gt}"
                )
                processed_ids.append(r["transaction__transactionId"])

            elif pred_time_ms and now_ms - pred_time_ms >= ONE_DAY_MS:
                logger.debug(f"Prediction time: {pred_time_ms}, Now: {now_ms}")
                logger.debug("Using model prediction after 1 day for g truth.")
                eff_time = pred_time_ms + ONE_DAY_MS
                eff_gt = model_label
                MLPrediction.objects.filter(
                    transaction_id=r["transaction__transactionId"]
                ).update(ground_truth=int(model_label))
                processed_ids.append(r["transaction__transactionId"])

            if model_label is True and eff_gt is True:
                d_tp += 1
            elif model_label is True and eff_gt is False:
                d_fp += 1
            elif model_label is False and eff_gt is False:
                d_tn += 1
            elif model_label is False and eff_gt is True:
                d_fn += 1
        if (processed_ids):
            MLPrediction.objects.filter(
                transaction__transactionId__in=processed_ids
            ).update(is_counted_metrics=True)

        logger.info(
            f"Delta Metrics calc: TP={d_tp}, FP={d_fp}, TN={d_tn}, FN={d_fn}"
        )
        tp += d_tp
        fp += d_fp
        tn += d_tn
        fn += d_fn

        total = tp + fp + tn + fn
        accuracy = (tp+tn)/total if total else 0.0
        precision = tp/(tp+fp) if (tp+fp) else 0.0
        recall = tp/(tp+fn) if (tp+fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        tpr = recall
        fpr = fp/(fp+tn) if (fp+tn) else 0.0

        logger.info(
            f"Overall Metrics: Accuracy={accuracy}, "
            f"Precision={precision}, Recall={recall}, F1={f1}, "
            f"TPR={tpr}, FPR={fpr}"
        )
        if not (d_tp == 0 and d_fp == 0 and d_tn == 0 and d_fn == 0):
            logger.info("Metric tabel created")
            Metrics.objects.create(
                tp=tp, fp=fp, tn=tn, fn=fn,
                accuracy=accuracy,
                precision=precision, recall=recall, f1_score=f1,
                tpr=tpr, fpr=fpr,
                watermark_ms=now_ms
            )

        required_data = (
            Metrics.objects.all()
            .order_by("-calculated_at")
            .values("tpr", "fpr", "precision", "recall")[:40]
        )

        roc_curve = []
        for roc in required_data:
            roc_curve.append({
                "tpr": roc["tpr"],
                "fpr": roc["fpr"]
            })
        logger.info("ROC Curve data prepared.")
        precision_recall_curve = []
        for pr in required_data:
            precision_recall_curve.append({
                "precision": pr["precision"],
                "recall": pr["recall"]
            })
        logger.info("Precision-Recall Curve data prepared.")

        fraud_type_stats = (
            MLPrediction.objects
            .filter(Q(isFraud=1) | Q(ground_truth=1))
            .select_related("transaction")
            .values("transaction__transaction_type")
            .annotate(count=Count("transaction__transaction_type"))
        )
        fraud_counts = {
            item["transaction__transaction_type"]: item["count"]
            for item in fraud_type_stats
        }

        all_transaction_types = (
            Enriched.objects
            .values_list("transaction_type", flat=True)
            .distinct()
        )
        fraud_type_distribution = [
            {
                "transaction_type": t_type,
                "count": fraud_counts.get(t_type, 0)
            }
            for t_type in all_transaction_types
        ]

        logger.info("Fraud Type Distribution data prepared.")

        latest_40 = list(
            MLPrediction.objects.order_by(
                "-time").values("fraud_probability", "amount")[:40]
        )
        sorted_latest = sorted(latest_40, key=lambda x: x["amount"])

        fraud_prob_amount_dist = []
        for fraud in sorted_latest:
            fraud_prob_amount_dist.append({
                "fraud_probability": fraud["fraud_probability"],
                "amount": (fraud["amount"])
            })
        logger.info("Fraud Probability vs Amount data prepared.")
        response = {
            "CONFUSION_MATRIX": {
                "TP": tp,
                "FP": fp,
                "TN": tn,
                "FN": fn,
                "ACCURACY": accuracy,
                "PRECISION": precision,
                "RECALL": recall,
                "F1": f1
            },
            "ROC_CURVE": roc_curve,
            "PRECISION_RECALL": precision_recall_curve,
            "FRAUD_COUNT_TYPE": fraud_type_distribution,
            "FRAUD_PROB_AMOUNT": fraud_prob_amount_dist
        }
        logger.info(f"Sending response for ConfusionMatrixAPI.{response}")
        return JsonResponse(response)


class ChatBotView(APIView):
    """
    The primary API endpoint for interacting with the AI Chatbot.

    Endpoint: `/api/chat/` (POST)
    Permission: AllowAny

    Handles two modes:
    1. Text/SQL/Vector Search: (Streaming Response)
        - Required Data: `text` (or `query`)
        - Optional Data: `conversation_id`
        - If 'plot intent' is detected, it forces the
        `chat_plot_with_context` pipeline.
        - Otherwise, uses `chat_stream_with_context` for multi-tool dialogue.

    2. Document Verification (RAG):
        - Required Data: `file` (uploaded file), `applicant_id`
        - Action: Runs `analyze_documents` and saves the result to
        conversation context.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        if "file" in request.FILES:
            logger.info("Detected PDF verification request")
            return self._handle_document_verification(request)

        user_text = request.data.get("text") or request.data.get("query")
        conversation_id = request.data.get("conversation_id")

        if not user_text or not isinstance(user_text, str):
            return Response(
                {"error": "Missing 'text' field"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if len(user_text) > MAX_INPUT_CHARS:
            return Response(
                {"error": "Input too long"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )

        if is_plot_intent(user_text):
            logger.info(
                "ChatBotView: detected plot intent, using chat_plot pipeline.")

            def event_stream():
                try:
                    payload = chat_plot_with_context(
                        user_text, conversation_id)
                    if isinstance(payload, dict) and payload.get("error"):
                        error_payload = {"error": payload.get("error")}
                        yield f"data: {json.dumps(error_payload)}\n\n"
                        return

                    yield f"data: {json.dumps(payload, default=str)}\n\n"
                except Exception as e:
                    logger.exception(f"Error in plot generation: {e}")
                    error_payload = {"error": str(e)}
                    yield f"data: {json.dumps(error_payload)}\n\n"

            response = StreamingHttpResponse(
                event_stream(),
                content_type="text/event-stream",
            )
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            logger.info("Plot request accepted, streaming...")
            return response

        # Non-plot streaming response with context
        try:
            def event_stream():
                try:
                    for chunk in chat_stream_with_context(
                            user_text, conversation_id):
                        if isinstance(chunk, str) and (
                            (
                                "Guardrails blocked" in chunk or
                                "Guardrails" in chunk or
                                "blocked unsafe SQL" in chunk
                            )
                        ):
                            logger.warning(
                                "Guardrails refusal detected while streaming.")
                            error_msg = (
                                "Request refused by guardrails."
                            )
                            yield (
                                f"data: {json.dumps({'error': error_msg})}"
                                "\n\n"
                            )
                            return

                        if isinstance(chunk, str) and chunk.startswith(
                                "\n__CONVERSATION_ID__:"):
                            conv_id = chunk.split(":")[-1]
                            payload = {"conversation_id": conv_id}
                            yield f"data: {json.dumps(payload)}\n\n"
                            continue

                        try:
                            chunk_text = str(chunk)
                        except Exception:
                            chunk_text = ""

                        payload = {'text': chunk_text}
                        event_data = f"data: {json.dumps(payload)}\n\n"
                        yield event_data

                    yield f"data: {json.dumps({'done': True})}\n\n"

                except Exception as e:
                    logger.exception(f"Error in chat streaming: {e}")
                    error_payload = {"error": str(e)}
                    yield f"data: {json.dumps(error_payload)}\n\n"

            logger.info("ChatBotView: starting streaming chat with context.")
            response = StreamingHttpResponse(
                event_stream(),
                content_type="text/event-stream",
            )
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response

        except Exception as e:
            logger.exception(f"ChatBotView internal error: {e}")
            return Response(
                {"error": "Internal error", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _handle_document_verification(self, request):
        """
        Handle document verification with conversation context.
        Caches the result so LLM can reference it in follow-up questions.
        """
        try:
            uploaded_file = request.FILES.get("file")
            applicant_id = request.data.get(
                "applicant_id") or request.data.get("applicantId")
            question = request.data.get("question")
            conversation_id = request.data.get("conversation_id")

            try:
                k = int(request.data.get("k", 6))
            except (ValueError, TypeError):
                k = 6

            metadata_filter = request.data.get("metadata_filter")
            doc_type = request.data.get("doc_type")

            if not uploaded_file:
                return Response(
                    {"error": "No file provided"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.info(
                f"Document verification request: applicant_id={applicant_id}, "
                f"doc_type={doc_type}, conversation_id={conversation_id}"
            )

            result = analyze_documents(
                uploaded_file=uploaded_file,
                applicant_id=applicant_id,
                question=question,
                k=k,
                metadata_filter=metadata_filter,
                ocr_fallback=True,
                doc_type=doc_type
            )

            if result.get("error"):
                logger.error(
                    f"Document verification error: {result.get('error')}")
                return Response(result, status=status.HTTP_400_BAD_REQUEST)

            conv_id, _ = get_or_create_conversation(conversation_id)

            llm_result = result.get("llm_result", {})

            formatted_response = {
                "type": "document_verification",
                "conversation_id": conv_id,
                "applicant_id": applicant_id,
                "doc_type": doc_type,
                "llm_result": llm_result,
                "similarity_score": result.get("similarity", {}).get("score"),
                "retrieved_count": result.get("retrieved_count", 0),
            }

            verdict = llm_result.get("verdict", "unknown")
            confidence = llm_result.get("confidence", 0)
            reasons = llm_result.get("reasons", [])

            reasons_str = (
                ', '.join(reasons) if reasons else 'None provided'
            )
            summary = (
                f"Document Verification Result:\n"
                f"- Verdict: {verdict}\n"
                f"- Confidence: {confidence}\n"
                f"- Reasons: {reasons_str}\n"
                f"- Retrieved {result.get('retrieved_count', 0)} "
                f"similar documents"
            )

            llm_result_str = json.dumps(llm_result, default=str)
            full_message = (
                f"[DOCUMENT_VERIFICATION_COMPLETED]\n{summary}\n\n"
                f"Full Result: {llm_result_str}"
            )
            add_to_conversation(
                conv_id,
                "system",
                full_message
            )

            logger.info(
                f"Document verification completed: verdict={verdict}, "
                f"confidence={confidence}, conversation_id={conv_id}"
            )

            return Response(formatted_response, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(f"Document verification failed: {e}")
            return Response(
                {"error": "Document verification failed", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ConversationManagementView(APIView):
    """
    API to manage the chatbot's conversation history in the cache.

    Endpoint: `/api/chat/update/{conversation_id}/`

    - DELETE: Clears the specified conversation history.
    - GET: Retrieves the history for the specified conversation.
    """
    permission_classes = [AllowAny]

    def delete(self, request, conversation_id):
        """Clear a specific conversation"""
        clear_conversation(conversation_id)
        return Response({"message": "Conversation cleared"},
                        status=status.HTTP_200_OK)

    def get(self, request, conversation_id):
        """Get conversation history"""
        history = get_conversation_context(conversation_id, max_messages=50)
        return Response({"conversation_id": conversation_id,
                         "history": history}, status=status.HTTP_200_OK)


class SendEmailAPIView(APIView):
    """
    Internal API endpoint for triggering asynchronous
    email sending (Celery Task).

    Endpoint: `/api/send_email/` (POST)
    Permission: Internal (requires `X-API-Key` header
    matching `settings.INTERNAL_API_KEY`).

    Required Data:
        - `address`: Recipient email address.
        - `subject`: Email subject.
        - `message`: Email body content.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if api_key != settings.INTERNAL_API_KEY:
            return Response({"error": "Unauthorized"}, status=401)
        try:
            address = request.data.get('address')
            subject = request.data.get('subject')
            message = request.data.get('message')
            txn_id = request.data.get('transaction_id')
            amount = request.data.get('amount')
            fraud_probability = request.data.get('fraud_probability')
            if not all([address, subject, message]):
                return Response(
                    {'error':
                     'All fields (address, subject, message) are required',
                     'fields': request.data
                     },
                    status=status.HTTP_400_BAD_REQUEST
                )

            send_email_task.delay(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [address]
            )

            return Response(
                {'result': 'Email sent successfully'},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"error occured: {e}")
            return Response(
                {'error': f"An error occurred while sending email: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TransactionRelatedDataToHelpAnalyst(APIView):
    """
    API endpoint to fetch **additional context** about a transaction
    and its participants (sender/receiver) to aid manual analysis.

    Endpoint: `/api/transaction_analysis/` (POST)

    Required Data:
        - `transactionId`

    Returns:
        - Transaction details, counts of prior transactions between the pair,
          fraud counts, and calculated trust scores/fraud ratios
          for participants.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        transaction_id = request.data.get('transactionId')
        txn = (
            Enriched.objects
            .filter(transactionId=transaction_id)
            .select_related("mlprediction")
            .first()
        )

        if not txn:
            return {"error": "transaction not found"}

        sender = txn.nameOrig
        receiver = txn.nameDest

        txn_between = Enriched.objects.filter(
            Q(nameOrig=sender, nameDest=receiver) |
            Q(nameOrig=receiver, nameDest=sender)
        ).count()

        sender_frauds = Enriched.objects.filter(
            nameOrig=sender, isFraud=1
        ).count()

        receiver_frauds = Enriched.objects.filter(
            nameOrig=receiver, isFraud=1
        ).count()

        receiver_for_fraud_ratio = Enriched.objects.filter(
            nameOrig=receiver).order_by("-time").first()
        receiver_fraud_ratio = (
            receiver_for_fraud_ratio.sender_fraud_ratio
            if receiver_for_fraud_ratio else None
        )

        sender_obj = Enriched.objects.filter(
            nameOrig=sender).order_by("-time").first()
        receiver_obj = Enriched.objects.filter(
            nameOrig=receiver).order_by("-time").first()

        trust_score_sender = sender_obj.trust_score if sender_obj else None
        trust_score_receiver = (receiver_obj.trust_score
                                if receiver_obj else None)

        response = {
            "transactionId": txn.transactionId,
            "sender": txn.nameOrig,
            "receiver": txn.nameDest,
            "model_prediction": txn.isFraud,
            "pagerank": txn.pagerank,
            "stddev_amount": txn.stddev_amount,
            "amount": txn.amount,
            "user_txn_count": txn.user_txn_count,
            "mean_amount": txn.mean_amount,
            "timestamp": txn.time,
            "confidence_score": (
                txn.mlprediction.confidence_score if hasattr(
                    txn, "mlprediction") else None
            ),
            "transactions_between_sender_receiver": txn_between,
            "sender_total_frauds": sender_frauds,
            "receiver_total_frauds": receiver_frauds,
            "trust_score_sender": trust_score_sender,
            "trust_score_receiver": trust_score_receiver,
            "sender_fraud_ratio": txn.sender_fraud_ratio,
            "receiver_fraud_ratio": receiver_fraud_ratio,
        }

        return JsonResponse(response)


class LLMReanalyserAPIView(APIView):
    """
    Internal API endpoint to schedule an LLM re-analysis task
    for a transaction.

    Endpoint: `/api/llm_reanalysis/` (POST)
    Permission: Internal (requires `X-API-Key` header).

    Required Data:
        - `transactionId`
        - `isFraud` (Model's prediction)

    Action: Schedules the `llm_task` (Celery task) to run after a countdown.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):

        api_key = request.headers.get("X-API-Key")
        if api_key != settings.INTERNAL_API_KEY:
            return Response({"Error": "Unauthorized"}, status=401)

        try:
            txn_id = request.data.get("transactionId")
            ml_pred = request.data.get("isFraud")

            if isinstance(txn_id, bytes):
                txn_id = txn_id.decode()

            if isinstance(ml_pred, bytes):
                ml_pred = ml_pred.decode()

            tid = str(txn_id)
            ml_prediction = int(ml_pred)

        except Exception as e:
            logger.error(f"Error fetching txn_id or ml_pred from body: {e}, ")
            return Response(
                {"Error": f"Error fetching txn_id or ml_pred from body: {e}"},
                status=400)

        llm_task.apply_async(
            (tid,
             ml_prediction),
            countdown=40
        )
        return Response(
            {'Result': 'LLM Cron sent successfully'},
            status=status.HTTP_200_OK
        )


class ModelHealthAPIView(APIView):
    """
    Internal API endpoint to **schedule the model health check task**.

    Endpoint: `/api/model-health/` (POST)
    Permission: Internal (requires `X-API-Key` header).

    Action: Schedules the `model_health_task` (Celery task).
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):

        api_key = request.headers.get("X-API-Key")
        if api_key != settings.INTERNAL_API_KEY:
            return Response({"Error": "Unauthorized"}, status=401)

        try:
            model_health_task.apply_async(
                countdown=120
            )
        except Exception as e:
            logger.error(f"Error scheduling model health task: {e}")
            return Response(
                {"Error": f"Failed to schedule job: {e}"},
                status=500
            )

        return Response(
            {"Result": "Model health check scheduled"},
            status=200
        )


class HealthCheckAPIView(APIView):
    """
    API endpoint for a simple health check.

    Endpoint: `/api/health/` (GET)
    Permission: AllowAny (required for external monitoring)

    Returns:
        - status: "OK"
        - timestamp: Current server time.
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "status": "OK",
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK
        )
