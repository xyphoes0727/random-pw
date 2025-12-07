import shap
import os
import pickle
import json
import numpy as np
import pandas as pd
from river.compose import pipeline
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib
import tempfile
import boto3
import seaborn as sns
import jinja2
import pdfkit
import wandb
import markdown
from log_config.log_config import get_logger
import sys
# from ml_engine.models_final import AnomalyToClassifier, StackingModel


logger = get_logger(__name__)


class AnomalyToClassifier:
    def __init__(self, model, threshold=0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        self.model.learn_one(x)
        return self

    def predict_proba_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)

        # prob = 1 / (1 + np.exp(-score))
        return {0: 1 - score, 1: score}

    def predict_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)


current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '.env')

load_dotenv(dotenv_path=dotenv_path)

WANDB_NAME = os.getenv("WANDB_NAME", "Model")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pw-model")
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "pw-versioning")
WANDB_KEY = os.getenv("WANDB_KEY")

RCA_S3_FOLDER = "rca_reports"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_KEY_2 = os.environ.get("OPENAI_API_KEY_2")


maskingData = {
    "amount": [1.084087e01],
    "oldbalanceOrg": [8.338831e05],
    "newbalanceOrig": [8.551137e05],
    "oldbalanceDest": [1.100702e06],
    "newbalanceDest": [1.224996e06],
}

RCA_REPORT_DIR = os.path.join("api", "rca_reports")
os.makedirs(RCA_REPORT_DIR, exist_ok=True)


def loadModel() -> pipeline.Pipeline:
    model_artifact_name = f"{WANDB_NAME}/{WANDB_PROJECT}/{COLLECTION_NAME}:latest"

    wandb.login(key=WANDB_KEY)
    with wandb.init(project=WANDB_PROJECT) as run:
        registry_model = run.use_artifact(artifact_or_name=model_artifact_name)
        local_artifact_path = registry_model.download()
        local_model_path = f"{local_artifact_path}/ARF.pkl"

    with open(local_model_path, "rb") as f:
        model = None

        try:
            model = CustomUnpickler(f).load()
        except Exception as e:
            print(f"Model: error on pickle: {e}")
    return model


# def loadModel(alias: str = ""):
#     local_path = os.path.join("/app/ml_engine/savedModels/", "ARF.pkl")

#     if not os.path.exists(local_path):
#         raise FileNotFoundError(f"Model file not found at {local_path}")

#     with open(local_path, "rb") as f:
#         try:
#             model = CustomUnpickler(f).load()
#         except Exception as e:
#             print(f"Error unpickling: {e}")
#             raise

#     print("Local model loaded successfully!")
#     return model


class CustomUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        logger.debug(f"Unpickling in load model: {module}.{name}")

        if module == "ml_engine.models_final":
            import ml_engine.models_final as real_mod
            return getattr(real_mod, name)

        if module == "ml_engine.retraining":
            import ml_engine.retraining as real_mod
            return getattr(real_mod, name)

        if module == "ml_engine.train_model":
            import ml_engine.train_model as real_mod
            return getattr(real_mod, name)

        if module == "__main__":
            return AnomalyToClassifier

        return super().find_class(module, name)


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


def get_shap_values(data: dict) -> dict:
    logger.info("Computing SHAP values for full feature set")

    model = loadModel()

    X_row = []
    for col in FEATURE_COLS:
        X_row.append(data.get(col, 0))

    X_sample = pd.DataFrame([X_row], columns=FEATURE_COLS)

    logger.info(f"Dataset shape: {X_sample.shape}")

    def predict_fn(X_df):
        outputs = []
        for _, row in X_df.iterrows():
            feats = row.to_dict()

            if hasattr(model, "predict_proba_one"):
                p = model.predict_proba_one(feats)
                if isinstance(p, dict):
                    outputs.append([p.get(0, 0.0), p.get(1, 0.0)])
                else:  # float score → convert to prob
                    outputs.append([1 - p, p])

            elif hasattr(model, "predict_one"):
                pred = model.predict_one(feats)
                outputs.append([1 - pred, pred])

            elif hasattr(model, "score_one"):
                s = model.score_one(feats)
                outputs.append([1 - s, s])

            else:
                raise RuntimeError("Model missing inference method")

        return np.array(outputs)

    # maskingData only covers some features → fill missing with zero
    masked = pd.DataFrame([{
        col: maskingData.get(col, [0])[0] if col in maskingData else 0
        for col in FEATURE_COLS
    }])

    masker = shap.maskers.Independent(masked)

    explainer = shap.Explainer(predict_fn, masker)
    shap_res = explainer(X_sample)

    shap_vals = shap_res.values[..., 1]  # probability class 1

    # Map values back to feature names
    feature_importances = {
        col: float(shap_vals[0][i])
        for i, col in enumerate(FEATURE_COLS)
    }

    return {
        "feature_importances": feature_importances
    }


def render_jinja_html(transactionData: dict, mlData: dict,
                      feature_importances: dict, llm_report: str,
                      plot_path: str) -> str:
    try:
        cwd = os.getcwd()
        template_loader = jinja2.FileSystemLoader(
            searchpath=f"{cwd}/api/templates/")
        template_env = jinja2.Environment(loader=template_loader)
        template_file = "rca.html"
        template = template_env.get_template(template_file)
        rca_report_html = markdown.markdown(llm_report)
        output_text = template.render(
            mlData=mlData,
            transactionData=transactionData,
            returnedDict=feature_importances,
            rca_summary=rca_report_html,
            plot_path=plot_path
        )
    except Exception as e:
        logger.debug(f"Error during jinja rendering: {e}")
    return output_text


def html2pdf(html_output: str, pdf_path: str):
    """
    Convert html to pdf using pdfkit
    """

    options = {
        'page-size': 'Letter',
        'margin-top': '0.35in',
        'margin-right': '0.75in',
        'margin-bottom': '0.75in',
        'margin-left': '0.75in',
        'encoding': "UTF-8",
        'no-outline': None,
        'enable-local-file-access': None
    }

    pdfkit.from_string(html_output, output_path=pdf_path, options=options)


def generate_llm_rca(transactionData: dict, mlData: dict, feature_importances: dict) -> str | None:
    prompt = (
        "You are a fraud analytics system assistant.\n"
        "Your task is to analyze model outputs for a bank risk analyst.\n"
        "Write in a concise, professional, and non-technical style suitable for a compliance or risk team.\n"
        "Do not repeat the raw input values. Only interpret them.\n"
        "Do not hallucinate features that are not provided.\n\n"

        "Generate a Root Cause Analysis (RCA) covering the following:\n"
        "1. Which features contributed most based on the SHAP values.\n"
        "2. Why those features may drive the model toward the predicted label.\n"
        "3. How the model arrived at the result (high-level reasoning).\n"
        "4. Any risk flags or behavioral anomalies worth noting.\n"
        "5. A brief recommended next step for the bank analyst.\n\n"

        "--- SHAP VALUES ---\n"
        f"{json.dumps(feature_importances, indent=1)}\n\n"
        "--- TRANSACTION DATA ---\n"
        f"{json.dumps(transactionData, indent=1)}\n\n"
        "--- MODEL PREDICTION DATA ---\n"
        f"{json.dumps(mlData, indent=1)}\n\n"
    )

    logger.info("Came to generate llm report")
    rca_summary = "RCA unavailable."

    try:
        client_chat = OpenAI(api_key=OPENAI_API_KEY)

        completion = client_chat.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        rca_summary_raw = completion.choices[0].message.content
        rca_summary_raw = rca_summary_raw if rca_summary_raw else ""
        rca_summary = rca_summary_raw.strip()

        logger.info("[INFO] RCA generated successfully.")

    except Exception:
        logger.warning(f"Trying to use second OpenAI API Key...")

        try:
            client_chat = OpenAI(api_key=OPENAI_API_KEY_2)

            completion = client_chat.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
            )

            rca_summary_raw = completion.choices[0].message.content
            rca_summary_raw = rca_summary_raw if rca_summary_raw else ""
            rca_summary = rca_summary_raw.strip()

        except Exception as e:
            logger.warning(
                f"No working API Key found. Skipping RCA Generation")

    plot_path = ""
    # generate plot here
    out_html = ""
    try:
        cwd = os.getcwd()
        plot_path = f"{cwd}/feature_importances.png"
        logger.info(f"feature:{feature_importances}")

        sns.set_style("whitegrid")
        df_plot = (
            pd.DataFrame(feature_importances["feature_importances"].items(),
                         columns=["feature", "importance"])
            .sort_values("importance", ascending=False)
        )

        plt.figure(figsize=(10, 8))
        plot = sns.barplot(x="importance", y="feature", data=df_plot)
        fig, _ = plt.subplots()
        font = {
            "size": 20
        }

        # plt.title("SHAP Feature Importances", fontdict=font)
        # plt.figure(figsize=(10, 8))
        plt.setp(plot.get_xticklabels(), rotation=15,
                 horizontalalignment='right', rotation_mode="anchor")
        dx = 18/72.
        dy = 0/72.
        offset = matplotlib.transforms.ScaledTranslation(
            dx, dy, scale_trans=fig.dpi_scale_trans)

        for label in plot.xaxis.get_majorticklabels():
            label.set_transform(label.get_transform() + offset)

        plt.xlabel("Features", fontdict=font)
        plt.ylabel("Feature Importances", fontdict=font)
        plot_fig = plot.get_figure()
        plot_fig.savefig(plot_path)  # type: ignore
        out_html = render_jinja_html(transactionData, mlData,
                                     feature_importances, rca_summary, plot_path)
    except Exception as e:
        logger.info(f"Error during jinja and plot gen: {e}")

    tmp_file_path = ""
    report_url = None

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"rca_report_{timestamp}.pdf"

        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:

            # tmp_file.write(out_html)
            tmp_file_path = tmp_file.name
            html2pdf(out_html, tmp_file_path)

        s3_bucket = os.environ.get("RCA_BUCKET_NAME")
        region = os.environ.get("REGION")
        aws_access_key_id = os.environ.get("AWS_S3_ACCESS_KEY")
        aws_secret_key = os.getenv("AWS_S3_SECRET_ACCESS_KEY")

        if not all([s3_bucket, region, aws_access_key_id, aws_secret_key]):
            logger.info(
                "[ERROR] S3 credentials not fully configured in .env. Skipping upload.")
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
            return None

        s3_client = boto3.client(
            service_name='s3',
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_key,
        )

        s3_key = f"{RCA_S3_FOLDER}/{filename}"
        s3_client.upload_file(tmp_file_path, s3_bucket, s3_key)

        report_url = f"https://{s3_bucket}.s3.{region}.amazonaws.com/{s3_key}"
        print(f"RCA report uploaded to S3: {report_url}")
        return report_url

    except Exception as e:
        print(f"[ERROR] Failed to save or upload RCA report: {e}")
        report_url = None
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        if (os.path.exists(plot_path)):
            os.remove(plot_path)
    return report_url
