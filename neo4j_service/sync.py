"""
Sync Service - Incremental Delta Lake to Neo4j Synchronization

This module implements the `SyncService`, responsible for incrementally
transferring new graph data (user-to-user edges) from partitioned Delta
Lake tables (hosted on S3) into a Neo4j graph database.

The synchronization process ensures data consistency by:
1. Tracking the last sync time using a `SyncMetadata` node in Neo4j.
2. Reading only data appended to Delta Lake since the last sync.
3. Using `MERGE` operations in Neo4j to update user nodes and edge
relationships with aggregated metrics (total amount, transaction count,
fraud count).
4. Re-computing basic graph features (in/out degree, total sent/received)
after sync.
"""

from typing import Optional, List
from datetime import datetime
from deltalake import DeltaTable
from neo4j import GraphDatabase
import pandas as pd
from neo4j_service.log_config.log_config import get_logger
logger = get_logger(__name__)


class SyncService:
    """
    Manages the incremental synchronization of graph data from multiple
    Delta Lake partitions (representing different Pathway processing instances)
    to Neo4j.
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        delta_path_base: str,
        storage_options: dict,
        instances: List[int]
    ):
        self.neo4j_uri = neo4j_uri
        self.delta_path_base = delta_path_base
        self.storage_options = storage_options
        self.instances = instances

        self.driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password),
            connection_timeout=30,
            max_connection_lifetime=200
        )

        logger.info(f"SyncService initialized - {delta_path_base}")

        self.ensure_schema()

    def ensure_schema(self):
        try:
            with self.driver.session() as session:
                session.run("""
                    CREATE CONSTRAINT user_id_unique IF NOT EXISTS
                    FOR (u:User) REQUIRE u.user_id IS UNIQUE
                """)
        except Exception as e:
            logger.error(f"Failed to ensure schema constraints: {e}")

    def get_last_sync_timestamp(self) -> Optional[str]:
        with self.driver.session() as session:
            result = session.run("""
                MATCH (m:SyncMetadata {id: 'sync_tracker'})
                RETURN m.last_sync_time as last_sync
                ORDER BY m.last_sync_time DESC
                LIMIT 1
            """).single()

            if result and result['last_sync']:
                return result['last_sync']
            return None

    def update_sync_timestamp(self, timestamp: str):
        with self.driver.session() as session:
            session.run("""
                MERGE (m:SyncMetadata {id: 'sync_tracker'})
                SET m.last_sync_time = $timestamp,
                    m.updated_at = datetime()
            """, timestamp=timestamp)

        logger.info(f"Global sync timestamp updated to {timestamp}")

    def read_incremental_edges(
        self,
        full_table_path: str,
        last_sync: Optional[str] = None
    ) -> pd.DataFrame:

        try:
            dt = DeltaTable(
                full_table_path, storage_options=self.storage_options)
            df = dt.to_pandas()

            if last_sync and 'timestamp' in df.columns:
                df = df[df['timestamp'] > last_sync]
                logger.info(f"  -> Found {len(df)} new edges since {last_sync}"
                            f"in {full_table_path}")

            return df
        except Exception as e:
            logger.warning(
                f"Could not read Delta Table at {full_table_path}. "
                f"It might not exist yet. Error: {e}"
            )
            return pd.DataFrame()

    def sync_users_incremental(self, edges_df: pd.DataFrame):
        if edges_df.empty:
            return

        sender = edges_df.groupby('from_user').agg({
            'amount': ['sum', 'count'],
            'is_fraud': 'sum'
        })
        sender.columns = ['sent_amount', 'sent_count', 'fraud_sent']

        receiver = edges_df.groupby('to_user').agg({
            'amount': ['sum', 'count'],
            'is_fraud': 'sum'
        })
        receiver.columns = ['recv_amount', 'recv_count', 'fraud_recv']

        users = sender.join(receiver, how='outer').fillna(0)
        users['user_id'] = users.index
        users = users.reset_index(drop=True)

        with self.driver.session() as session:
            batch_size = 500
            total_updated = 0

            for i in range(0, len(users), batch_size):
                batch = users.iloc[i:i+batch_size]
                session.run("""
                    UNWIND $users AS user
                    MERGE (u:User {user_id: user.user_id})
                    SET u.total_transactions = coalesce(u.total_transactions, 0) + user.sent_count + user.recv_count,
                        u.total_sent = coalesce(u.total_sent, 0) + user.sent_amount,
                        u.total_received = coalesce(u.total_received, 0) + user.recv_amount,
                        u.fraud_count = coalesce(u.fraud_count, 0) + user.fraud_sent + user.fraud_recv,
                        u.fraud_ratio = toFloat(coalesce(u.fraud_count, 0)) / u.total_transactions,
                        u.last_updated = datetime()
                """, users=batch.to_dict('records'))

                total_updated += len(batch)

        logger.info(f"  -> Updated {total_updated} user nodes")

    def sync_edges_incremental(self, edges_df: pd.DataFrame):
        if edges_df.empty:
            return

        edges = edges_df.groupby(['from_user', 'to_user']).agg({
            'amount': ['sum', 'count'],
            'is_fraud': 'sum'
        })
        edges.columns = ['amount_sum', 'txn_count', 'fraud_count']
        edges = edges.reset_index()

        with self.driver.session() as session:
            batch_size = 500
            total_updated = 0

            for i in range(0, len(edges), batch_size):
                batch = edges.iloc[i:i+batch_size]
                session.run("""
                    UNWIND $edges AS edge
                    MATCH (from:User {user_id: edge.from_user})
                    MATCH (to:User {user_id: edge.to_user})
                    MERGE (from)-[r:TRANSACTED_WITH]->(to)
                    SET r.total_amount = coalesce(r.total_amount, 0) + edge.amount_sum,
                        r.transaction_count = coalesce(r.transaction_count, 0) + edge.txn_count,
                        r.fraud_count = coalesce(r.fraud_count, 0) + edge.fraud_count,
                        r.fraud_ratio = toFloat(coalesce(r.fraud_count, 0)) / r.transaction_count,
                        r.last_updated = datetime()
                """, edges=batch.to_dict('records'))

                total_updated += len(batch)

        logger.info(f"  -> Updated {total_updated} edge relationships")

    def sync_users_incremental_with_graph_features(self):
        with self.driver.session() as session:
            session.run("""
                MATCH (u:User)
                WITH u,
                    size([(u)-[:TRANSACTED_WITH]->() | 1]) as out_deg,
                    size([(u)<-[:TRANSACTED_WITH]-() | 1]) as in_deg
                SET u.out_degree = out_deg,
                    u.in_degree = in_deg
            """)

            session.run("""
                MATCH (u:User)-[r:TRANSACTED_WITH]->()
                WITH u, sum(r.total_amount) as sent
                SET u.total_sent = sent
            """)

            session.run("""
                MATCH (u:User)<-[r:TRANSACTED_WITH]-()
                WITH u, sum(r.total_amount) as received
                SET u.total_received = received
            """)

            logger.info("Graph features re-computed in Neo4j")

    def sync(self) -> bool:
        try:
            last_sync = self.get_last_sync_timestamp()
            logger.info(f"Starting sync cycle. Last sync time: "
                        f"{last_sync if last_sync else 'Never'}")

            cycle_had_data = False

            for instance_id in self.instances:
                try:
                    full_path = f"{self.delta_path_base}_{instance_id}"

                    edges_df = self.read_incremental_edges(
                        full_path, last_sync)

                    if not edges_df.empty:
                        logger.info(f"Processing data from "
                                    f"Instance {instance_id}")
                        self.sync_users_incremental(edges_df)
                        self.sync_edges_incremental(edges_df)
                        cycle_had_data = True
                    else:
                        logger.debug(f"No new data for Instance {instance_id}")

                except Exception as e:
                    logger.error(f"Failed to sync Instance {instance_id}: {e}")
                    continue

            if cycle_had_data:
                self.sync_users_incremental_with_graph_features()
                current_time = datetime.now().isoformat()
                self.update_sync_timestamp(current_time)
                logger.info(f"Sync cycle completed. Timestamp "
                            f"updated to {current_time}")
                return True
            else:
                logger.info("Sync cycle completed. No new data found.")
                return False

        except Exception as e:
            logger.error(f"Error during sync: {e}", exc_info=True)
            raise

    def close(self):
        self.driver.close()
        logger.info("SyncService closed")
