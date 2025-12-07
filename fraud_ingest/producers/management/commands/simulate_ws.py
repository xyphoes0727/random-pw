"""Django management command to simulate WebSocket transaction traffic.

Streams batched JSON payloads from a CSV over a WebSocket connection at a
target rate, with auto-reconnect, background listener, and progress reporting.
"""

from django.core.management.base import BaseCommand
import asyncio
import websockets
import json
import pandas as pd
import time
import sys


class Command(BaseCommand):
    """Simulate transaction traffic via WebSocket with rate control.

    Arguments:
        --file: Path to the CSV file containing transactions.
        --rate: Target transactions per second.
        --url: WebSocket endpoint URL.

    Workflow:
        - Load CSV rows.
        - Connect to WebSocket and create a background listener.
        - Send batches at the target rate, computing sleep time per batch.
        - Handle connection drops with auto-reconnect.
        - Report progress and final throughput.
    """

    def add_arguments(self, parser):
        """Register CLI arguments for the management command."""
        parser.add_argument('--file', type=str, required=True)
        parser.add_argument('--rate', type=float, default=10.0)
        parser.add_argument('--url', type=str,
                            default='ws://localhost:8000/ws/transactions/')

    def handle(self, *args, **options):
        """Entrypoint that runs the async simulation and handles interrupts."""
        try:
            asyncio.run(self.run_simulation(options))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nStopped by user."))

    async def listen_loop(self, websocket):
        """Consume messages from the server in the background.

        Keeps the connection alive by reading incoming frames.
        """
        try:
            async for _ in websocket:
                pass
        except Exception:
            pass

    async def run_simulation(self, options):
        """Run the client-side streaming loop with rate limiting and reconnects.

        Args:
            options: Dict-like object containing 'file', 'rate', and 'url'.

        Behavior:
            - Reads CSV rows into memory.
            - Sends batches of transactions as JSON over WebSocket.
            - Adjusts sleep time to match desired transactions per second.
            - Logs progress periodically and reconnects on errors.
        """
        file_path = options['file']
        rate = options['rate']
        url = options['url']
        BATCH_SIZE = 500

        self.stdout.write(f"Loading {file_path}...")
        try:
            df = pd.read_csv(file_path)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Read failed: {e}"))
            return

        total_rows = len(df)
        delay = 1.0 / rate
        current_index = 0

        self.stdout.write(f"Target: {rate} tx/s | Total: {total_rows}")
        self.stdout.write(f"Batch Size: {BATCH_SIZE}")

        while current_index < total_rows:
            try:
                async with websockets.connect(
                        url,
                        ping_interval=None,
                        ping_timeout=None,
                        close_timeout=5) as websocket:

                    listener_task = asyncio.create_task(
                        self.listen_loop(websocket))

                    if current_index == 0:
                        start_time = time.time()

                    self.stdout.write(self.style.SUCCESS(
                        f"\nConnected! Resuming at {current_index}..."))

                    try:
                        while current_index < total_rows:
                            loop_start = time.time()

                            batch_df = df.iloc[
                                current_index:current_index + BATCH_SIZE
                            ]

                            if batch_df.empty:
                                break

                            batch_payload = []
                            for row in batch_df.itertuples(index=False):
                                tx_payload = {
                                    "transactionId": str(row.transactionId),
                                    "step": int(row.step),
                                    "type": int(row.type),
                                    "amount": float(row.amount),
                                    "nameOrig": str(row.nameOrig),
                                    "oldbalanceOrg": float(row.oldbalanceOrg),
                                    "newbalanceOrig": float(
                                        row.newbalanceOrig),
                                    "nameDest": str(row.nameDest),
                                    "oldbalanceDest": float(
                                        row.oldbalanceDest),
                                    "newbalanceDest": float(
                                        row.newbalanceDest),
                                    "isFraud": int(row.isFraud),
                                    "kyc_tier": int(row.kyc_tier)
                                }
                                batch_payload.append(tx_payload)

                            await websocket.send(json.dumps(batch_payload))

                            txns_sent_in_batch = len(batch_payload)
                            current_index += txns_sent_in_batch

                            elapsed = time.time() - loop_start

                            target_delay = delay * txns_sent_in_batch
                            sleep_time = target_delay - elapsed

                            if sleep_time > 0:
                                await asyncio.sleep(sleep_time)
                            else:
                                await asyncio.sleep(0)

                            if (current_index % (10 * BATCH_SIZE) == 0
                                    or current_index >= total_rows):
                                curr_t = time.time() - start_time
                                real_rate = (
                                    current_index / curr_t if curr_t > 0 else 0
                                )
                                sys.stdout.write(
                                    f"\rProgress: {current_index}/{total_rows}"
                                    f" ({real_rate:.0f} tx/s)")
                                sys.stdout.flush()

                    finally:
                        listener_task.cancel()

            except (websockets.exceptions.ConnectionClosed,
                    ConnectionRefusedError) as e:
                self.stdout.write(self.style.WARNING(
                    f"\nConnection lost ({e}). Reconnecting in 1s..."))
                await asyncio.sleep(1.0)
                continue

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\nCritical Error: {e}"))
                break

        total_time = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(
            f"\n\nCOMPLETE! Sent {current_index} records in {total_time:.2f}s."
        ))
