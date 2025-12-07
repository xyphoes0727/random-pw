from google.cloud import aiplatform
from vertexai.resources.preview.feature_store import (
    FeatureOnlineStore,
    FeatureView,
    FeatureGroup
)
from typing import List
import os
from dotenv import load_dotenv
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '.env')
load_dotenv(dotenv_path)


current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '.env')
load_dotenv(dotenv_path)

FEATURE_GROUP_NAME = os.getenv("FEATURE_GROUP_NAME", "")
GCP_PROJ_NAME = os.getenv("GCP_PROJ_NAME", "")
FG_LOCATION = os.getenv("FG_LOCATION", "")
FEATURE_VIEW_NAME = os.getenv("FEATURE_VIEW_NAME", "")
FEATURE_ONLINE_STORE = os.getenv("FEATURE_ONLINE_STORE", "")
ENTITY_ID = os.getenv("ENTITY_ID", "")


# def get_access_token():
#     """Load service account and create OAuth access token"""
#     credentials = service_account.Credentials.from_service_account_file(
#         os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
#         scopes=SCOPES)
#     credentials.refresh(Request())
#     return credentials.token


aiplatform.init(project=GCP_PROJ_NAME, location=FG_LOCATION)
fos = FeatureOnlineStore(FEATURE_ONLINE_STORE)
fv = FeatureView(FEATURE_VIEW_NAME, feature_online_store_id=fos.name)


def GetFeatureMonitor():
    fg = FeatureGroup(
        FEATURE_GROUP_NAME,
        project=GCP_PROJ_NAME,
        location=FG_LOCATION
    )

    feature_monitor = fg.get_feature_monitor("FEATURE_MONITOR_NAME")

    feature_monitor_job = feature_monitor.get_feature_monitor_job(
        "FEATURE_MONITOR_JOB_ID"
    )

# Retrieve feature stats and anomalies
    feature_stats_and_anomalies = feature_monitor_job.feature_stats_and_anomalies
    print(feature_stats_and_anomalies)


def read_entity_ids(entity_ids_path: str) -> List[dict]:
    entity_ids = pd.read_csv(f"{entity_ids_path}")

    resps: List[dict] = []
    for eid in entity_ids:
        resp = fv.read([ENTITY_ID,]).to_dict()
        resps.append(resp)

    return resps
