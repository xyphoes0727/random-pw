from celery import shared_task
from django.core.mail import send_mail
from .llm_analyser import llm_reanalyser, analyze_model_health
from .models import Enriched, MLPrediction, Metrics
from loguru import logger
from telemetry_provider.consumers import MLHealth
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django import setup


def serialize_row(row):
    """
    Convert Metrics ORM instance → clean JSON-serializable dict.
    Only DB fields are included.
    """
    data = {}
    for field in row._meta.fields:
        name = field.attname  # actual DB column name
        value = getattr(row, name)
        data[name] = value
    return data


@shared_task(name="api.tasks.send_email_task")
def send_email_task(subject, message, from_email, recipient_list):
    logger.debug("=== CELERY TASK ARGS ===")
    logger.debug(f"subject: {subject}")
    logger.debug(f"message: {message}")
    logger.debug(f"from: {from_email}")
    logger.debug(f"recipients: {recipient_list}")
    logger.debug("========================")

    send_mail(
        subject,
        message,
        from_email,
        recipient_list,
        fail_silently=False,
    )


@shared_task(name="api.tasks.llm_task")
def llm_task(tid: str, ml_prediction: int):
    """
    Re-evaluate classifier decision using LLM
    and update DB prediction accordingly.
    """

    try:
        enriched = Enriched.objects.filter(
            transactionId=tid
        ).first()

        if enriched is None:
            logger.warning(f"No txn found with given txn_id: {tid}")
            return {"Error": f"No txn with given txn_id: {tid}"}

    except Exception as e:
        exc = {"Error while fetching enriched:": str(e)}
        logger.error(exc)
        return exc

    enriched_data = {
        "transaction_type": enriched.transaction_type,
        "amount": enriched.amount,
        "oldBalanceOrg": enriched.oldbalanceOrg,
        "newbalanceOrig": enriched.newbalanceOrig,
        "oldbalanceDest": enriched.oldbalanceDest,
        "newbalanceDest": enriched.newbalanceDest,
        "user_mean_amount_of_transactions": enriched.mean_amount,
        "user_stddev_amount_of_transactions": enriched.stddev_amount,
        "user_min_amount_seen": enriched.min_amount_seen,
        "user_max_amount_seen": enriched.max_amount_seen,
        "user_txn_count": enriched.user_txn_count,
        "user_amount_to_balance_ratio": enriched.amount_to_balance_ratio,
        "isFraud": ml_prediction
    }

    try:
        ml_pred = MLPrediction.objects.get(
            transaction=tid
        )

        ml_pred_conf_score = ml_pred.confidence_score
        if (not ml_pred_conf_score):
            ml_pred_conf_score = 0.5

        new_conf_score = ml_pred_conf_score
        new_label = llm_reanalyser(enriched_data)
        if (new_label != ml_prediction):
            new_conf_score = ml_pred_conf_score*0.90
        else:
            new_conf_score = min(1, ml_pred_conf_score*1.1)
        MLPrediction.objects.filter(
            transaction=tid
        ).update(
            confidence_score=new_conf_score
        )

    except Exception as e:
        exc = {"Error while updating ML Prediction:": str(e)}
        logger.error(exc)
        return exc

    return {"Successful llm reanalysis": new_label}


# @shared_task(name="api.tasks.model_health_task")
# def model_health_task():
#     """
#     Fetch last 2 metrics rows → convert to JSON-safe dicts → send to LLM → log the result.
#     """

#     rows = list(Metrics.objects.order_by("-calculated_at")[:2])

#     if len(rows) < 2:
#         logger.warning("Not enough metrics rows for comparison")
#         return None

#     prev_row = rows[1]
#     curr_row = rows[0]

#     try:
#         prev = serialize_row(prev_row)
#         curr = serialize_row(curr_row)

#         result = analyze_model_health(prev, curr)
#         logger.info(f"Model Health LLM Result: {result}")

#         return result

#     except Exception as e:
#         logger.error(f"LLM model health analysis failed: {e}")
#         return {"error": str(e)}

@shared_task(name="api.tasks.model_health_task")
def model_health_task():
    """
    Fetch last 2 metrics rows → convert to JSON-safe dicts →
    send to LLM → log the result.
    """
    logger.info("Started ml health task")
    logger.info("Started ml")

    rows = list(Metrics.objects.order_by("-calculated_at")[:2])

    if len(rows) < 2:
        logger.warning("Not enough metrics rows for comparison")
        return None

    prev_row = rows[1]
    curr_row = rows[0]

    try:
        prev = serialize_row(prev_row)
        curr = serialize_row(curr_row)

        result = analyze_model_health(prev, curr)
        channel_layer = get_channel_layer()
        logger.info(f"Model Health LLM Result: {result}")
        async_to_sync(channel_layer.group_send)("health_group",
                                                {
                                                    "type": "send_update",
                                                    "data": {"result": result},
                                                })
        return result
    except Exception as e:
        logger.error(f"LLM model health analysis failed: {e}")
        return {"error": str(e)}
