## Quick setup instructions

```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
set up environment variables
```
### docker

```
cd deploy/
docker compose up -d
if needed, docker compose down -v
```
### make db migrations

``` 
cd fraud_ingest/
python manage.py makemigrations
python manage.py migrate
```

### mysql configuration (if needed)

```
docker exec -it mysql_db mysql -u app_user -p app_db
```

### run kafka database sync service

```
cd fraud_ingest/
python manage.py run_kafka_consumer
```
### run backend
```
cd fraud_ingest/
uvicorn fraud_ingest.asgi:application --reload
```

### run pathway engine with telemetry

```
python -m fraud_ingest.pathway.preprocessor
```

### run ml engine

```
python -m ml_engine.main
```

### run neo4j service

```
python -m neo4j_service.main
```
### run kafka producer

```
cd fraud_ingest/
python manage.py produce_from_csv --file "data/file.csv"
```


### api endpoints
```
/api/transactions/ -> get all transaction details (enriched)
/api/stats -> get all time stats (total transactions, total fraud count, protected amount)
/api/transactions/?start_time=1762701290000&end_time=1762701299000 -> timestamped transactions
/api/predictions -> get all ml predictions
/api/predictions/?start_time=1762701290000&end_time=1762701299000 -> timestamped predictions
```


### docker setup
```
put your csv file in root folder data
cd deploy/
./start.sh up
./start.sh produce data/file.csv
```

### command for using chatbot individually on CLI
cd deploy/
docker exec -it fraud_ingest_api python -u -m api.orc1

### RABBITMQ COMMANDS AND INFORMATION
# sudo rabbitmq-server -detached
# sudo rabbitmqctl stop

# USE BELOW IF STUCK
# sudo pkill -f rabbitmq
# sudo pkill -f beam.smp

# vhost: myvhost
