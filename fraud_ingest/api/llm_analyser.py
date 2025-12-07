import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from loguru import logger
from google import genai
import pika


current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)
BROKER_URL = os.getenv("CELERY_BROKER_URL", "")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_KEY_2 = os.environ.get("OPENAI_API_KEY_2")
OPENAI_URL = os.getenv("OPENAI_URL")
OPENAI_URL = OPENAI_URL if OPENAI_URL else ""

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gclient = genai.Client(api_key=GEMINI_API_KEY)  # fallback client


def llm_safe_predict(prompt: str) -> str:
    """
    Standardized OpenAI to Gemini fallback.
    Return raw text only.
    """

    # Try OpenAI
    resp = ""
    try:
        client_chat = None
        if OPENAI_URL is not None and OPENAI_URL != "":
            client_chat = OpenAI(
                api_key=OPENAI_API_KEY, base_url=OPENAI_URL)
        else:
            client_chat = OpenAI(api_key=OPENAI_API_KEY)

        resp = client_chat.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.warning(
            f"OpenAI first key. Switching to second key | Error: {e}  Resp: {resp}")

        try:
            client_chat_2 = None
            if OPENAI_URL is not None and OPENAI_URL != "":
                client_chat_2 = OpenAI(
                    api_key=OPENAI_API_KEY, base_url=OPENAI_URL)
            else:
                client_chat_2 = OpenAI(api_key=OPENAI_API_KEY)

            resp = client_chat_2.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(
                f"OpenAI second failed too. Switching to Gemini | Error: {e}  Resp: {resp}")

    # Fallback Gemini
    try:
        resp = gclient.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return resp.text.strip()

    except Exception as e:
        logger.error(f"Gemini failed too | Error: {e}")
        return ""


def llm_safe_predict_analyser(prompt: str) -> str:
    """
    Standardized OpenAI to Gemini fallback.
    Return raw text only.
    """

    # Try OpenAI
    resp = ""
    try:
        client_reanalyser = None
        if OPENAI_URL is not None and OPENAI_URL != "":
            client_reanalyser = OpenAI(
                api_key=OPENAI_API_KEY, base_url=OPENAI_URL)
        else:
            client_reanalyser = OpenAI(api_key=OPENAI_API_KEY)

        resp = client_reanalyser.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.warning(
            f"OpenAI first key failed. Switching to second key | Error: {e}  Resp: {resp}")

        client_reanalyser_2 = None
        if OPENAI_URL is not None and OPENAI_URL != "":
            client_reanalyser_2 = OpenAI(
                api_key=OPENAI_API_KEY, base_url=OPENAI_URL)
        else:
            client_reanalyser_2 = OpenAI(api_key=OPENAI_API_KEY)

        try:
            resp = client_reanalyser_2.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(
                f"OpenAI second key failed. Switching to second key | Error: {e}  Resp: {resp}")

    # Fallback Gemini
    try:
        resp = gclient.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return resp.text.strip()

    except Exception as e:
        logger.error(f"Gemini failed too | Error: {e}")
        return ""


def llm_reanalyser(txn_data: dict) -> int:
    ground_truth = txn_data.pop("isFraud", None)

    prompt = f"""
        You are evaluating whether a financial transaction is fraudulent.

        Strictly output ONLY:
        Fraud
        OR
        Not Fraud

        Data:
        {json.dumps(txn_data, indent=2)}
    """

    raw = llm_safe_predict_analyser(prompt)

    if not raw:
        logger.warning("Empty LLM response. Returning ground_truth")
        return ground_truth

    raw = raw.strip()

    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]).strip()

    if raw == "Fraud":
        return 1
    if raw == "Not Fraud":
        return 0

    logger.warning(
        f"Unexpected LLM output: {raw}. using ground_truth instead.")
    return ground_truth


def serialize_metrics_row(row):
    clean = {}
    if isinstance(row, dict):
        items = row.items()
    else:
        items = {
            k: v for k, v in row.__dict__.items() if not k.startswith("_")
        }.items()

    for key, value in items:
        if key == "_state":
            continue

        if hasattr(value, "isoformat"):
            clean[key] = value.isoformat()
            continue

        if str(type(value)) == "<class 'decimal.Decimal'>":
            clean[key] = float(value)
            continue

        try:
            json.dumps(value)
            clean[key] = value
        except Exception:
            clean[key] = str(value)

    return clean


def analyze_model_health(prev_row, curr_row):
    prev = serialize_metrics_row(prev_row)
    curr = serialize_metrics_row(curr_row)

    prompt = f"""
        Compare ML performance snapshots.

        ### Previous Metrics:
        {json.dumps(prev, indent=2)}

        ### Current Metrics:
        {json.dumps(curr, indent=2)}

        Return ONLY valid JSON in this strictly exact shape:

        {{
        "status": "Healthy" | "Declining" | "Stable",
        "severity": <float between 0 and 1>,
        "explanation": "<one sentence>"
        }}
    """

    raw = llm_safe_predict(prompt)

    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]).strip()

    retrain_prompt = f"""
    Compare the ML performance snapshots and decide if retraining is necessary.

    ### Instructions:
    - Be strict and conservative: ONLY output 1 (retrain) if there is clear and significant performance degradation or strong evidence of data drift.
    - Minor fluctuations, noise, or small metric drops should NOT trigger retraining.
    - Output MUST be a single number: 0 (no retrain) or 1 (retrain).

    ### Previous Metrics:
    {json.dumps(prev, indent=2)}

    ### Current Metrics:
    {json.dumps(curr, indent=2)}
    """

    raw_retrain = llm_safe_predict(retrain_prompt)

    if raw.startswith("```"):
        lines = raw.splitlines()
        raw_retrain = "\n".join(lines[1:-1]).strip()

    doRetrain = 0
    if (int(raw_retrain) == 1):
        doRetrain = 1
    elif (int(raw_retrain) == 0):
        doRetrain = 0

    if (doRetrain):
        connection = pika.BlockingConnection(
            pika.URLParameters(BROKER_URL))
        channel = connection.channel()

        channel.queue_declare(queue='trigger-retrain',

                              arguments={
                                    "x-max-length": 1,
                                    "x-overflow": "reject-publish"
                              })

        print(f"Model degraded in quality. Sending retrain signal.")
        channel.basic_publish(
            exchange='', routing_key='trigger-retrain', body=raw_retrain)
        print(f"Sent retrain signal.")
        connection.close()
    elif (int(raw_retrain) == 0):
        logger.info(
            f"LLM Analysis yielded no requirement for retraining. Skipping it.")
    else:
        logger.warning(
            f"LLM didn't return 0 or 1 for retraining: {raw_retrain}")

    try:
        return json.loads(raw)
    except Exception:
        logger.warning(f"Failed parsing JSON from output: {raw}")
        return {"error": "parse_error", "raw": raw}
