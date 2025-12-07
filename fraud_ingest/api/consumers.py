from channels.generic.websocket import AsyncJsonWebsocketConsumer
import logging
import hashlib
import json
import os
import asyncio
import time
from aiokafka import AIOKafkaProducer

logger = logging.getLogger(__name__)


def user_partitioner(key, partition_count):
    if key is None:
        return 0
    hash_val = int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16)
    return hash_val % partition_count


class TransactionConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.producer = None
        self.counter = 0

    async def connect(self):
        await self.accept()
        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=os.environ.get(
                    "KAFKA_BOOTSTRAP_SERVERS", "kafka:9093"),
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                key_serializer=lambda k: k.encode('utf-8') if k else None,
                acks=1
            )
            await self.producer.start()

            logger.info(
                "Transaction WebSocket connected (Raw Pass-Through Mode)")
            await self.send_json({
                'status': 'connected',
                'message': 'Ready'
            })
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            await self.close(code=4000)

    async def disconnect(self, close_code):
        if self.producer:
            await self.producer.stop()
        logger.info(f"WebSocket disconnected: {close_code}")

    async def receive_json(self, content):

        if isinstance(content, list):
            transactions_to_process = content
        else:
            transactions_to_process = [content]

        if not self.producer:
            return

        batch_start = time.time()
        send_tasks = []

        try:
            for tx in transactions_to_process:
                name_orig = tx["nameOrig"]

                partition = user_partitioner(name_orig, partition_count=9)

                task = self.producer.send(
                    topic='transactions-raw',
                    key=name_orig,
                    value=tx,
                    partition=partition
                )
                send_tasks.append(task)

            if send_tasks:
                await asyncio.gather(*send_tasks)

            successful_txns = len(send_tasks)
            self.counter += successful_txns

            if successful_txns > 0:
                last_id = transactions_to_process[-1].get(
                    'transactionId', 'N/A')
                await self.send_json({
                    'status': 'complete_batch',
                    'successful_txns': successful_txns,
                    'last_id': last_id,
                    'errors': []
                })

        except KeyError as e:
            logger.error(f"Missing Key in raw data: {e}")
            await self.send_json({'status': 'error',
                                  'message': f"Missing key: {e}"})
        except Exception as e:
            logger.error(f"Kafka Send Error: {e}")
            await self.send_json({'status': 'error', 'message': str(e)})

        batch_elapsed = time.time() - batch_start

        if batch_elapsed > 0.1:
            logger.info(f"Batch processed: {successful_txns}"
                        f"items in {batch_elapsed:.3f}s")
