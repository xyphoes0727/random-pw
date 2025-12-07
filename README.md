<!-- Top Banner Section -->
<div style="
  padding: 32px 40px;
  background: #0D0A17;
  border-radius: 16px;
  border: 1px solid #2A2344;
">

  <!-- Top row: Pathway logo on the left -->
  <div style="display:flex; align-items:center; margin-bottom:24px;">
    <img
      src="./assets/pathway-card-removebg-preview.png"
      alt="Pathway"
      style="height:60px; margin-right:auto;"
    />
  </div>

  <!-- Title -->
  <h1 style="
    font-size: 42px;
    color: #ffffff;
    margin: 0 0 20px 0;
    text-align: center;
  ">
    <b>Real-Time Fraud Detection System</b>
  </h1>

  <!-- Subtitle -->
  <p style="
    font-size: 16px;
    color: #C084FC;
    max-width: 760px;
    margin: 0 auto 28px auto;
    line-height: 1.6;
    text-align: center;
  ">
    Modular, streaming-native architecture integrating
    <b>Kafka</b>, <b>Pathway</b>, <b>River Online ML</b>,
    <b>Neo4j Graph Intelligence</b>, <b>SHAP Explainability</b>,
    and an <b>LLM-powered Ambient Agent</b> — engineered for
    <b>sub-second predictions</b> and
    <b>production-grade fraud detection</b>.
  </p>

  <!-- Buttons -->
  <div style="margin-top: 10px; text-align: center;">
    <a href="#system-overview" style="text-decoration:none; margin-right:8px;">
      <img src="https://img.shields.io/badge/OVERVIEW-7c3aed?style=for-the-badge&logo=readme&logoColor=white" />
    </a>
    <a href="#system-architecture" style="text-decoration:none; margin-right:8px;">
      <img src="https://img.shields.io/badge/ARCHITECTURE-4c1d95?style=for-the-badge" />
    </a>
    <a href="#production-ready-features" style="text-decoration:none;">
      <img src="https://img.shields.io/badge/FEATURES-a855f7?style=for-the-badge" />
    </a>
  </div>

</div>

<!-- --- -->


<!-- <p align="left">
  <img src="./assets/pathway-card-removebg-preview.png" width="150" />
</p>

</div>
<div align="center"> -->

<!-- ![Pathway Banner](./assets/pathway_banner.png) --> 
<!-- 
# **Real-Time Fraud Detection System**

*Modular, streaming-first architecture combining Kafka, Pathway, River online ML, Neo4j graph intelligence, SHAP explainability and an LLM-driven Ambient Agent -- built for sub-second, production-grade fraud detection.* -->

<!-- <div>
  <a href="#quick-start"><kbd>🚀 Quick Start</kbd></a>
  <a href="#architecture" style="margin-left:10px;"><kbd>🗺 Architecture</kbd></a>
  <a href="#features" style="margin-left:10px;"><kbd>✨ Features</kbd></a>
</div> -->

</div>

---



## <span style="color:#C084FC;">System Overview</span>
The system is a fully modular, real-time fraud detection platform designed to operate at high throughput with sub-second latency. It integrates Kafka, Pathway, River online ML, Neo4j graph intelligence, LLM-powered reasoning, and a complete HITL (Human-in-the-Loop) feedback loop. All services are fully dockerized and continuously observable via OpenTelemetry + Grafana, enabling production-grade reliability and transparency.

## <span style="color:#C084FC;">Data Flow</span>


The data flow begins with real-time transactions entering Kafka, which serves as the high-throughput ingestion backbone. These events are consumed by a distributed Pathway ETL pipeline, where schema validation, enrichment, rule-based classification, feature computation, and user/device profile updates occur in streaming mode. Pathway then publishes enriched transactions back to Kafka, while simultaneously persisting them to Delta Lake for auditability and offline analytics, and exporting feature snapshots to BigQuery for monthly retraining workflows. The enriched stream is consumed by downstream services that update MySQL, keeping the dashboard and APIs in sync with the latest fraud scores. In parallel, Pathway updates a dynamic fraud graph in Neo4j, where metrics such as PageRank, centrality, community structure, and cycle detection are computed and fed back into the ML pipeline. Predictions generated inside the Pathway model wrapper are streamed through Kafka and ultimately written to MySQL along with SHAP explanations and metadata. Analyst feedback travels through the same channels, enabling the ML engine to learn online. This unified streaming loop: Kafka → Pathway → Kafka → Consumers → MySQL, ensures that every component of the system receives consistent, real-time updates while maintaining exactly-once semantics, low latency, and high reliability.

### Ingestion Pipeline
<p align="center"> <img src="assets/ingestion.jpg" width="800" height="350"> </p>




## <span style="color:#C084FC;">System Architecture</span>

The system follows a modular, event-driven architecture centered around Kafka and Pathway, where each subsystem—ingestion, enrichment, machine learning, explainability, monitoring, and storage—operates independently but remains connected through streaming interfaces. Kafka handles real-time transaction ingestion, while Pathway performs continuous enrichment and transformation without disrupting downstream components. The ML layer, built on River, generates fraud predictions and confidence scores that are synchronized with SHAP-based explanations and the Human-in-the-Loop module for transparent decision-making. Verified transactions are stored in Delta Lake and streamed to Neo4j to build entity-relationship graphs for fraud ring detection. Grafana, the Ambient Agent, and the dashboard provide monitoring, alerting, forensic insights, and analyst-facing visualizations. This modular, stream-oriented design enables scalable, explainable, and production-ready fraud detection with minimal coupling and high maintainability.

<p align="center">
  <img src="assets/Architecture.jpg" width="800" height="550">
</p>


---

### <span style="color:#7C4DFF;">Key Highlights</span>


| Category                 | Description                                                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| Real-Time Streaming      | Built on **Pathway + Kafka** with exactly-once ingestion and low latency.                                                  |
| Adaptive Learning        | Online ML ensemble (**Half-Space Trees + One-Class SVM + Logistic Regression**) using the River framework.                 |
| Explainability (XAI)     | **SHAP** plots highlight feature influences; **RCA** generates natural-language summaries for transparency.                |
| Human-in-the-Loop (HITL) | Analysts review uncertain predictions and send real-time feedback that updates the model instantly.                        |
| Ambient Agents           | Autonomous background agents monitor latency, CPU, and logs; detect errors, perform root-cause analysis, and auto-recover. |
| Fault Tolerance          | Deterministic checkpointing ensures recovery from crashes without data loss.                                               |
| Graph Analytics          | Neo4j visualizes user–merchant–device relationships for fraud-ring detection.                                              |
| Dockerized Deployment    | Single **docker-compose** stack for complete reproducibility.                                                              |
| Monitoring & Telemetry   | Integrated metrics and OpenTelemetry for observability.                                                       |

---

### ML Pipeline
<p align="center"> <img src="assets/ml_pipeline1.jpg" width="760" height="500"> </p>

#### 💻Online Machine Learning Engine (River)

The ML system uses adaptive online learners that update on every transaction:

1. Models:
<br>Base Models:
Adaptive Random Forest (AdaRF) which detects evolving and non-linear fraud patterns, drift aware and two logistic regression models.
<br>Meta-Classifier: Logistic Regression which learns the optimal combination of the three models and outputs the final calibrated fraud probability


1. Dynamic Thresholding 
Fraud threshold is recalculated in real time using the most recent N predictions, making the system drift-aware and stable under rapidly changing transaction patterns.

1. Online Learning with HITL Feedback
Analyst corrections are streamed back through Kafka → ML Engine → Database, enabling continuous incremental improvement.

---
### 👨‍💼 Human-in-the-Loop (HITL)

Analysts can override low-confidence flagged predictions.
If the analyst feedback contradicts the model:
1. The feedback is streamed back to Kafka
2. Stored as ground truth in MySQL
3. ML model is incrementally updated
4. Future predictions shift closer to human judgment

---

### 🔍 Explainability & Transaction Reports

For every suspicious transaction, the frontend displays:
1. complete user & device profile
2. transaction metadata
3. SHAP feature importance values with graphs
4. natural language explanation (LLM-generated)
5. RCA report

This gives full transparency into why a transaction was flagged.

---

### 🕸 Graph Intelligence with Neo4j

Every enriched transaction updates a dynamic user–device–merchant graph, enabling advanced fraud-ring detection.
Neo4j periodically computes:
1. PageRank (influence estimation)
2. Betweenness Centrality (bridge nodes)
3. Community Detection (Louvain)
4. Cycle Detection for suspicious loops
5. Neighborhood anomaly scores

---
### 🖥️System Monitoring and Persistence
#### Ambient Agent for RCA & Monitoring
The Ambient Agent is the autonomous supervisory layer of our fraud detection system.
It continuously monitors model health, analyses fraud patterns, recalculates risk, and orchestrates alerts by coordinating three sub-agents:

- Health Agent
- Re-analyser Agent
- Alert Agent
<p align="center"> <img src="assets/ambient_agent1.jpg" width="750" height="540"> </p>
These agents operate inside the Pathway MCP Server, making the entire pipeline streaming-native, reactive, and self-correcting.

The Ambient Agent updates the dashboard in real time with:
- Recalculated fraud scores
- Alert summaries
- Model health insights
- Neo4j graph changes

This supports full system transparency and analyst trust.

A key innovation validated during experimentation was the introduction of an Ambient Health Check Agent. This agent continuously monitors model metrics, drift indicators, and confidence distributions. If degradation is detected, it triggers a retraining request via RabbitMQ. The retraining pipeline automatically generates an updated model, logs it to Weights & Biases, and pushes a signal back to Pathway to load the new model.

---
### Experimental Validation

We conducted extensive experiments to compare different fraud-detection approaches across offline, online, and adaptive learning settings. Traditional supervised models such as XGBoost, Random Forests, and standalone Adaptive Random Forest achieved strong accuracy during offline evaluation on PaySim. However, they lacked the ability to continuously adapt, recalibrate thresholds, or respond to drift in real streaming environments.

To address these limitations, we designed a stacking ensemble composed of:
- Adaptive Random Forest (captures non-linear fraud patterns and reacts to concept drift)
- Logistic Regression (Calibrated Model)
- Logistic Regression (Fraud-Sensitive Model)
- combined through a Meta Logistic Regression Classifier that learns the optimal weighted combination of all base learners.

This ensemble is wrapped inside a Pathway streaming wrapper, enabling real-time ingestion, inference, and incremental updates without batch recomputation.

During experiments, the ensemble produced a highly calibrated fraud probability which was further stabilized by dynamic thresholding. HITL (human-in-the-loop) overrides were fed back into the system to correct misclassifications and improve downstream thresholds.

This validation demonstrated that the final architecture is not only accurate but also:

- Fully streaming-native
- Self-correcting and drift-aware
- Explainable through structured LLM reasoning
- Production-ready with automated monitoring and retraining

Overall, the ensemble + ambient agent + retraining loop proved significantly more robust and scalable than any standalone offline or unsupervised solution we tested.

---
### Retraining & Model Registry

The Ambient Agent monitors model health (drift indicators, precision/recall trends, confidence distribution).

- When performance degrades, it publishes a retrain request to RabbitMQ.
- A separate training worker consumes this request, retrains the stacking ensemble on recent data, and logs the new version to Weights & Biases (W&B) as a production candidate.
- Once approved, the inference service is restarted or updated to load the latest model from W&B.

Pathway continues to stream transactions and features, calling the updated model for scoring without changing the streaming layer.

---

## <span style="color:#C084FC;">Role of Pathway in our system</span>

Pathway serves as the streaming backbone of our entire fraud detection system, enabling real-time ingestion, feature computation, model inference and learning, monitoring. It ensures that every component—from ML decisions to agent workflows—operates consistently on live, continuously updating data streams.

### 1. Exactly-Once Streaming Ingestion

Pathway consumes transactions from Kafka with checkpointed offsets, guaranteeing:

- no duplicate processing,
- no missing events, and
- strict ordering of financial transactions.

This reliability is essential for fraud scoring and downstream auditability.

### 2. Pathway Incremental Checkpointing (State Recovery)

Incremental Checkpointing

- Pathway snapshots operator state at regular intervals.
- On crash/restart, Pathway replays Kafka events up to the checkpointed offset
- This guarantees consistent reconstruction of the streaming state.

### 3. Real-Time Feature Enrichment

Pathway maintains live transaction tables and performs:

- rolling window aggregations,
- frequency/velocity feature updates,
- joins with account metadata,
- lookups against blocklists.

These enriched feature streams become the single source of truth for the ML pipeline, without batch recomputation or stale data.

### 4. Synchronized Stacking Ensemble Inference (Pathway Wrapper)

Pathway wraps our final ML architecture:
- Adaptive Random Forest
- Logistic Regression (Calibrated)
- Logistic Regression (Fraud-Sensitive)
- Meta Logistic Regression

It ensures:
- temporally aligned inputs across all learners,
- deterministic scoring,
- low-latency inference,
- consistent fraud probabilities for downstream components,
- on-the-fly threshold recalculation.

The wrapper allows the model to behave as a true streaming ensemble rather than a batch classifier bolted onto a stream.

### 5. Integrated HITL + Ambient Agent Flows

Pathway emits events to the Ambient Health Check Agent, enabling:
- live monitoring of drift, accuracy, and score distributions,
- immediate health feedback loops,
- coordination with the Re-analyser and Alert Agents,
- dynamic recalculation of fraud labels when HITL overrides occur.

Every update flows through Pathway tables, ensuring a consistent state across the system.


### 6. Vector Store for Document Verification & RAG

We use the Pathway Vector Store to support real-time document intelligence:
- PDF embeddings are generated and inserted as vectors
- Top-k similarity retrieval runs each time a new document arrives
- Retrieved chunks power LLM-based classification & RCA

This provides fast, low-latency document relevance verification at ingestion speed.


### 7. MCP server
Pathway serves as the MCP server for our system, hosting tool logic through @pw.udf functions:
- McpServable runs the MCP server
- safe inputs/outputs to LLMs
- function implements the tool
- register_mcp exposes it to the LLM
- controlled memory access
- this emphasizes LLM guardrails,

Grafana alerts trigger these tools to fetch logs, send them to the LLM for analysis, and stream summarized outputs to the frontend. 

### 8. Production-Grade Reliability

Pathway abstracts away the complexities of:
- state management,
- fault tolerance,
- recovery,
- rollback and replay,
- ordering guarantees,
- concurrency control.

This allows the entire fraud platform to behave like a single, consistent, fully streaming system, drastically reducing engineering overhead.


---

## Tech Stack

| Layer                  | Technologies                                       |
| ---------------------- | -------------------------------------------------- |
| Streaming & Compute    | Apache Kafka, Pathway (Vectorstore + Real-time pipelines), Redis Streams                              |
| Offline ML Engine	 |Stacking Ensemble (Adaptive Random Forest + Logistic Regression + Logistic Regression → Meta Logistic Regression), Scikit-Learn|
| Online ML & Explainability |River (Adaptive Models, Thresholding), SHAP, Model Drift Monitors|
|Document AI / PDF Verification  | Pathway PDF Parser, OpenAI Embeddings, Similarity Search (Vectorstore), Django Document Verification Agent  |
| Databases & Storage    | MySQL (metadata), Neo4j (Graph Fraud Network), Delta Lake / Parquet (batch data), Redis (caching), RabbitMQ (queueing)   , Wandb (model registry)       |
| Backend & APIs         | Django REST Framework, FastAPI microservices, Guvicorn (ASGI server), WebSockets (real-time chat & streaming)             |
| Monitoring & RCA & Observability      | Grafana, Prometheus, Ambient Agent, Kafka UI, Neo4j Browser    |
| Frontend	      | React (TypeScript), Tailwind / CSS / JS, WebSocket Client, Axios     |
| Containerization & Deployment	        | Docker, Docker Compose, Ngrok Tunneling                       |            

---

## Setup and Run Instructions

---
### 1. Clone the Repository
git clone <repo-url>
cd <repo-name>

---
### 2. Set environment variables

Create a `.env` file, copy the environment file:

```bash
  cp .env.example .env
```

---
### 3.  Environment Variable Setup Guide

Follow the instructions below to generate all required API keys and credentials for the platform.

#### 1. HuggingFace Token (`HUGGINGFACE_HUB_TOKEN`)

**How to get it:**

Go to: https://huggingface.co/settings/tokens<br>
Click **New token**.<br>
Choose permissions: **Read** (pull models) or **Write** (push checkpoints).<br>
Click **Generate Token** and copy it.<br>

**Add to `.env`:**

```bash
HUGGINGFACE_HUB_TOKEN="hf_xxxxx"
HF_REPO_NAME="username/repo-name"
```
---

#### 2. OpenAI API Key (`OPENAI_API_KEY`)

**How to get it:**

Go to: https://platform.openai.com/settings/organization/api-keys<br>
Click **Create new secret key**.<br>
Copy the key.<br>

**Add to `.env`:**

```bash
OPENAI_API_KEY="sk-xxxxxx"
```

---
#### 3. WANDB API Key (`WANDB_KEY`)

**How to get it:**

Go to: https://wandb.ai/authorize<br>
Copy the API key displayed after login.<br>

**Add to `.env`:**

```bash
WANDB_KEY="xxxxxxxx"
WANDB_PROJECT="fraud-detection"
REGISTRY_NAME="Model"
COLLECTION_NAME="Production"
```
---


#### 4. AWS Credentials (S3, Delta Lake, SHAP Reports)

**How to get them:**

Go to https://console.aws.amazon.com/iam/home<br>
IAM → **Users** → choose/create user.<br>
Open **Security Credentials** tab.<br>
Click **Create Access Key** → choose **CLI**.<br>
Copy Access Key ID + Secret Key.<br>

**Add to `.env`:**

```bash
AWS_ACCESS_KEY_ID="AKIAxxxxx"
AWS_SECRET_ACCESS_KEY="xxxxxxxx"

AWS_S3_ACCESS_KEY="AKIAxxxxx"
AWS_S3_SECRET_ACCESS_KEY="xxxxxxxx"
AWS_REGION="ap-south-1"

BUCKET_NAME="your-s3-bucket"
RCA_BUCKET_NAME="shapreport"
AWS_S3_SIGNATURE_VERSION="s3v4"
```
---

#### 5. Google Cloud Credentials (`GOOGLE_APPLICATION_CREDENTIALS`)

**How to get it:**

Go to https://console.cloud.google.com<br>
IAM & Admin → **Service Accounts**.<br>
Create/select an account → **Keys → Add Key → JSON**.<br>
Download the key file.<br>

**Add to `.env`:**

```bash
GOOGLE_APPLICATION_CREDENTIALS="/app/key.json"
```
---

#### 6. Neo4j Credentials

**How to set:**

Open Neo4j Browser → http://localhost:7474<br>
Login with default credentials → set new password.<br>

**Add to `.env`:**

```bash
NEO4J_URI="bolt://neo4j-fraud:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="frauddetection"
```
---


#### 7. Pinecone Vector DB (Chatbot + Document Verification)

**How to get it:**

Go to https://app.pinecone.io<br>
Create an index.<br>
Go to **API Keys** → copy Key & Environment.<br>

**Add to `.env`:**

```bash
PINECONE_API_KEY="xxxxx"
PINECONE_INDEX="fraud-assistant"
PINECONE_ENVIRONMENT="gcp-starter"
```
---

#### 8. Grafana Cloud (Metrics, Logs, Traces)

**How to get credentials:**

Go to https://grafana.com/auth/sign-in<br>
Create Cloud Stack → Connections → **Send Data** → OpenTelemetry.<br>
Copy:
- OTLP Metrics endpoint  
- OTLP Logs endpoint  
- OTLP Traces endpoint  
- Access Token  

**Add to `.env`:**

```bash
GRAFANA_CLOUD_ACCESS_TOKEN="xxxx"

PROMETHEUS_ENDPOINT="https://prometheus-prod-xxx.grafana.net/api/prom/push"
PROMETHEUS_INSTANCE_ID="12345"

LOKI_ENDPOINT="https://logs-prod-xxx.grafana.net/loki/api/v1/push"
LOKI_INSTANCE_ID="12345"

TEMPO_ENDPOINT="https://tempo-prod-xxx.grafana.net/tempo/api/push"
TEMPO_INSTANCE_ID="tempo-12345"
```
---

#### 9. RabbitMQ (Celery + Async Tasks)

**How to configure:**

Go to http://localhost:15672<br>
Create a new user if needed.<br>

**Add to `.env`:**

```bash
RABBITMQ_URL="amqp://my_user:my_password@rabbitmq:5672/"
```
---


#### 10. MCP / Ambient Agent Settings

**Add to `.env`:**

```bash
MCP_BROKER_URL="http://localhost:8123"
MCP_HOST="localhost"
MCP_PORT=8123
MCP_SERVER_NAME="Ambient MCP Server"
MCP_GATEWAY_URL="http://127.0.0.1:8123/mcp"
MCP_REQUEST_TIMEOUT=20
```
---

#### 11. Pathway Vector Store

```bash
PATHWAY_VECTORSTORE_URL="http://127.0.0.1:8765"
PATHWAY_VECTORSTORE_API_KEY=""
```
---

####  12. Validate Your Environment

Run:

```bash
docker compose config
```

If anything is missing, Docker will show warnings or errors.

---

### 4. Running the Backend System

#### 1. Create virtual environment and install dependencies
```bash
python -m venv venv
source venv/bin/activate
```

---



#### 2. Start services with Docker
The full stack is dockerized. To start all services, simply run:
```bash
cd deploy/
./start.sh 
```
This launches:
Kafka + Zookeeper
Schema Registry
Multi-instance Pathway Cluster
MySQL
Neo4j + Graph Service
Redis
ML Engine
Ambient Agent
Kafka Producer/Consumers
Fraud Ingest API
Frontend Dashboard
OTEL Collector
Grafana Cloud integration

---
#### 3. Start Streaming Transactions 
To produce transactions from a CSV file into the streaming pipeline:
Upload your CSV file to this path: fraud_ingest/data

```bash
  cd ..
  cd fraud_ingest/
  ./start.sh produce data/file.csv
```

---
#### Backend runs on **[http://localhost:8000](http://localhost:8000)**
---
### 5. Open frontend

```bash
  http://localhost:3000
```

---

## Frontend Tabs

[![Summary](https://img.shields.io/badge/Tab-Summary-6c5ce7?style=for-the-badge&logo=appveyor)]( # )
[![Analytics](https://img.shields.io/badge/Tab-Analytics-4f46e5?style=for-the-badge )]( # )
[![Audits](https://img.shields.io/badge/Tab-Audits-7c3aed?style=for-the-badge)]( # )
[![Metrics](https://img.shields.io/badge/Tab-Metrics-2563eb?style=for-the-badge)]( # )
[![Observability](https://img.shields.io/badge/Tab-Observability-00bcd4?style=for-the-badge)]( # )
[![AI Assistant](https://img.shields.io/badge/Tab-AI_Assistant-8b5cf6?style=for-the-badge)]( # )

| **Tab** | **Description (short)** |
|---|---|
| **Summary** | KPI cards (Fraud Alerts, Protected Amount, Transactions, Suspected Txns), total transactions chart and a live transaction stream table with quick actions. |
| **Analytics** | Model evaluation: confusion matrix, ROC / PR curves, partial dependence (Amount vs Fraud probability), feature importance trends and per-slice metrics for root-cause. |
| **Audits** | Live audit log stream from Pathway, Kafka, ML engine and Ambient Agent. Search, filter by service/level, and link log lines to transactions. |
| **Metrics** | System metrics and historical charts: Pathway CPU/Memory, Kafka lag, model latency, consumer throughput. Time-range selector + service filter. |
| **Observability** | Web Vitals, traces, request latency percentiles (p50/p90/p99). Correlates traces with transaction IDs for RCA. |
| **AI Assistant** | Natural language queries to fetch transactions, create custom plots, compare user/device behavior, and verify uploaded documents (PDF). |
| **Transaction Details** | Inspect a transaction: user/device profiles, SHAP waterfall & bar charts, NLP explanation, graph context, verdict & history. Includes SHAP PDF/report link. |
| **Graph Explorer** | Interactive Neo4j visualizer – search nodes, view communities (Louvain), PageRank, centrality and detect suspicious cycles. |
| **Feedback** | Analyst feedback UI (Verify modal). Low-confidence predictions automatically go to analyst queue. Feedback is streamed to ground truth and triggers online learning. |
| **Ambient Agent** | LLM-powered background agent producing RCA summaries, retrain suggestions, and automated remediation playbooks. |
| **Security & Audit** | All actions are authenticated and role-based. All analyst overrides and model changes are timestamped and auditable. |

---


## Frontend Interface Overview

The frontend is a real-time, analyst-centric investigation console designed for transparency, rapid triage, and deep forensic analysis. It brings together live transaction streams, ML explanations, graph intelligence, system metrics, and LLM reasoning into one unified interface.

The dashboard transforms raw streaming data into actionable insights, enabling analysts to understand what happened, why it happened, and how to respond - all within a few seconds.

---

###  Frontend Dashboard Snapshot 

<p align="center">

  <img src="./assets/frontend_dash.jpeg" width="400" height="250" />
  <img src="./assets/analysis_tab.jpeg" width="400" height="250" />

  <br/><br/>
  <img src="./assets/transaction_analysis.jpeg" width="400" height="250" />
  <img src="./assets/transaction_details.jpeg" width="400" height="250" />
  <br/><br/>

  <img src="./assets/audits_tab.jpeg" width="398" height="248" />
  <img src="./assets/metrics_tab.jpeg" width="398" height="248" />

   <br/><br/>

  <img src="./assets/observability_tab.jpeg" width="398" height="248" />
  <img src="./assets/chatbot_tab.jpeg" width="398" height="248" />

   <br/><br/>
     <img src="./assets/chatbot.jpeg" width="398" height="248" />
  <img src="./assets/shap_result.jpeg" width="398" height="248" />



</p>
---



## Performance Metrics

| Metric     | Result                              |
| ---------- | ----------------------------------- |
| Latency    | ~0.9 seconds         |
| Throughput | ~50,000 transactions/min (simulated) |
| Precision   | 0.923 (Stacking Ensemble)  
| Recall  | 0.923 (Stacking Ensemble)  
| F1 Score   | 0.923 (Stacking Ensemble)          |
| Accuracy   | 99.9% (PaySim dataset)              |

---
<div style="background:#0D0A17; padding:20px; border-radius:12px; border:1px solid #3a3a5c;">

## <span style="color:#9d7fff;">Production-Ready Features</span>

Our platform is engineered for enterprise-grade reliability, fault tolerance, and real-time performance.

<!-- ### <span style="color:#b8a3ff;">1. Fault-Tolerant Streaming Architecture</span> -->
### 1. Fault-Tolerant Streaming Architecture
- Distributed Kafka ingestion with high throughput  
- Exactly-once semantics via Pathway offset checkpointing  
- Multi-instance Pathway cluster for horizontal scaling and auto-recovery  


<!-- ### <span style="color:#b8a3ff;">2. Real-Time ETL, Rule Engine & Enrichment</span> -->
### 2. Real-Time ETL, Rule Engine & Enrichment<
- Millisecond-level transformations and validation  
- Real-time rule-based classification inside Pathway  
- Continuous profile updates (user, device, merchant)  
- Live streaming joins and feature computation  


<!-- ### <span style="color:#b8a3ff;">3. Persistent & Replayable Storage</span> -->
### 3. Persistent & Replayable Storage
- Delta Lake for durable, versioned storage  
- BigQuery for historical analysis, drift detection, and retraining  
- Scheduled monthly Vertex AI training pipeline  


<!-- ### <span style="color:#b8a3ff;">4. Graph Intelligence at Scale</span> -->
### 4. Graph Intelligence at Scale
- Neo4j fraud graph updated in real time  
- PageRank, Centrality, Community Detection, Cycle Detection  
- Optimized reads for analyst-facing tools  


<!-- ### <span style="color:#b8a3ff;">5. Adaptive Online Machine Learning</span> -->
### 5. Adaptive Online Machine Learning
- River-based online learning updated continuously  
- Dynamic Thresholding adapting to streaming distributions  
- Human-in-the-loop feedback correcting drift instantly  


<!-- ### <span style="color:#b8a3ff;">6. Human-in-the-Loop Decisioning</span> -->
### 6. Human-in-the-Loop Decisioning
- Suspicious predictions routed to analysts  
- Delayed finalization: model decisions finalized only without feedback  
- Ground-truth ingestion improves online model performance  


<!-- ### <span style="color:#b8a3ff;">7. LLM Guardrails & Ambient Agent</span> -->
### 7. LLM Guardrails & Ambient Agent
- Strict schemas and sanitization for safe LLM execution  
- Autonomous root-cause reasoning from system logs  
- ML health assessment and drift monitoring  


<!-- ### <span style="color:#b8a3ff;">8. End-to-End Observability</span> -->
### 8. End-to-End Observability
- OpenTelemetry instrumentation across all services  
- Unified logs, metrics, and traces via Grafana  
- Dashboard visibility into latency, Kafka lag, system health, error rates  
- Frontend displays live audit logs for transparency  


<!-- ### <span style="color:#b8a3ff;">9. Secure & Compliant API Layer</span> -->
### 9. Secure & Compliant API Layer
- Authentication required for all backend endpoints  
- Role-based access for analysts  
- Complete audit trails of decisions and overrides  


<!-- ### <span style="color:#b8a3ff;">10. Fully Containerized Deployment</span> -->
### 10. Fully Containerized Deployment
- Single docker-compose stack with ~20 interconnected services  
- Reproducible environments with isolated networks & persistent volumes  
- One-command startup: `./start.sh` and data injection  


<!-- ### <span style="color:#b8a3ff;">11. Real-Time Explainability & Analytics</span> -->
### 11. Real-Time Explainability & Analytics
- SHAP explanation graphs for every transaction  
- NLP-powered reasoning summaries  
- Real-time fraud trend analytics, confusion matrix, PR curves  


<!-- ### <span style="color:#b8a3ff;">12. Analyst-Centric Tools</span> -->
### 12. Analyst-Centric Tools
- AI assistant for querying transactions, generating insights & document verification  
- Transaction explorer with SHAP, graph context, user/device profiles  
- Feedback portal updating the model instantly  

</div>

---

---

<div style="background:#0D0A17; padding:22px; border-radius:14px; border:1px solid #7A3FFF;">

## Future Improvements

### 1. Integrating BDH (Baby Dragon Hatchling)
A brain-inspired LLM model using scale-free neuron graphs and Hebbian plasticity to enable transaction-level adaptation without retraining.  
Future pipeline: Kafka → Pathway → Neo4j → **BDH (Hebbian)** → Score + Synaptic Explanation.

---

### 2. TGN (Templar Graph Network) for Deep Graph Intelligence
Introduce a **Templar Graph Network (TGN)** layer on top of the Neo4j transaction graph to model:
- Long-term temporal patterns  
- Entity evolution (user, device, merchant)  
- Cross-community fraud signals  
- High-order structural anomalies  

TGN will run in parallel with online ML to generate deeper risk embeddings and detect coordinated fraud rings.

---

### 3. Advanced Neo4j Background Analysis
Enhance background graph processing with:
- Multi-hop cycle detection (fraud loops)  
- Temporal community drift analysis  
- Subgraph anomaly detection for collusion patterns  
- Fraud ring “core node” identification using centrality deltas  

These computations will run asynchronously and feed back enriched graph features into Pathway.

---

### 4. Data Encryption & Privacy Enhancements
As the system handles sensitive financial information, the next improvements include:
- Full **encryption-at-rest** (Delta Lake, MySQL, Neo4j)  
- **Field-level encryption** for personally identifiable information  
- Encrypted feature generation pipelines for KYC & device metadata  
- Secure audit logging with tamper-evident storage  

---

### 5. TLS & Secure Transport Across All Services
Upgrade the entire microservice ecosystem to strict TLS:
- mTLS between backend → Kafka → Pathway → Neo4j  
- TLS termination at ingress for API and frontend  
- Certificate rotation automation  
- Zero-trust service communication policies  

This reduces the attack surface and protects privacy-critical financial flows.

---

### 6. Security Hardening & Compliance
As the pipeline contains highly sensitive user and transaction information:
- Migration toward **RBAC + OAuth2**  
- Request lineage tracking  
- SIEM integration for anomaly detection  
- Compliance alignment for financial standards (PCI-DSS, ISO 27001)

---

</div>

---

## References

* [Pathway Documentation](https://pathway.com/developers)
* [Pathway-microservices](https://pathway.com/blog/pathway-laposte-microservices/)
* [Pathway-kafka](https://pathway.com/developers/templates/etl/linear_regression_with_kafka/)
* [Pathway MCP Server](https://pathway.com/developers/user-guide/llm-xpack/pathway_mcp_server/)
* [Pathway Vector Store](https://pathway.com/glossary/vector-database/)
* [River ML Documentation](https://riverml.xyz)
* [Apache Kafka](https://kafka.apache.org/)
* [SHAP Library](https://github.com/slundberg/shap)
* [PaySim Dataset (Kaggle)](https://www.kaggle.com/datasets/ealaxi/paysim1)
* [Neo4j Graph](https://neo4j.com/blog/developerexploring-fraud-detection-neo4j-graph-data-science-part-1/)
* [Neo4j-AWS](https://neo4j.com/blog/fraud-detection/neo4j-aws-fraud-detection/)
* [SHAP research paper to interpret model predictions](https://arxiv.org/abs/1705.07874)
* [Applying Simulation to the Problem of Detecting Financial Fraud](https://www.researchgate.net/publication/315837540_Applying_Simulation_to_the_Problem_of_Detecting_Financial_Fraud)
* [AWS SageMaker Stack for Fraud Detection](https://aws.amazon.com/sagemaker/)
* [AWS FinTech Blog: Real-time Fraud Detection at Scale Using Stream-ing Analytics](https://aws.amazon.com/blogs/industries/real-time-fraud-detection-at-scale-using-streaming-analytics/)
* [Real-time fraud detection using AWS](https://aws.amazon.com/blogs/machine-learning/real-time-fraud-detection-using-aws-serverless-and-machine-learning-services/)
* [Paypal throughput and latency](https://www.oberlo.com/statistics/how-many-people-use-paypal)
* [Adaptive Random Forest](https://riverml.xyz/0.11.1/api/ensemble/AdaptiveRandomForestClassifier/)
* [RabbitMQ](https://www.rabbitmq.com/)
* [Grafana Opentelemetry](https://grafana.com/docs/opentelemetry/)
* [Delta lake](https://delta.io/)
---
