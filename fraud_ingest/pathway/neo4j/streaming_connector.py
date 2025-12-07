"""
Neo4j Streaming Connector Module.

This module provides a class (`Neo4jStreamingConnector`) to establish
and manage a connection to a Neo4j graph database. It is designed to
fetch real-time graph-based features for a given user ID efficiently,
primarily for integration into a streaming data pipeline (like the Pathway
fraud detection system).

The module initializes environment variables for Neo4j connection details
and provides a global singleton pattern via `init_neo4j_connector` and
`fetch_graph_features` for easy access within the main pipeline.
"""
import os
import time
import logging
from typing import Dict
from neo4j import GraphDatabase
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)


class Neo4jStreamingConnector:
    """
    Manages the connection to a Neo4j database and handles fetching
    user-specific graph features for real-time stream enrichment.
    """
    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        logger.info("Initializing Neo4j connector...")
        in_time = time.time()
        self.driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password),
        )
        logger.info(f"Neo4j connector ready: {neo4j_uri}, initialised in {time.time() - in_time:.2f} seconds")

    def get_user_features(self, user_id: str) -> Dict:
        logger.info(f"Fetching neo4j graph features for user {user_id}.")
        default_features = {
            'out_degree': 0,
            'in_degree': 0,
            'total_sent': 0,
            'total_received': 0,
            'fraud_ratio': 0,
            'pagerank': 0.0,
            'betweenness': 0.0
        }

        try:
            with self.driver.session() as session:
                query_start = time.time()
                result = session.run("""
                    MATCH (u:User {user_id: $user_id})
                    RETURN {
                        out_degree: coalesce(u.out_degree, 0),
                        in_degree: coalesce(u.in_degree, 0),
                        total_sent: coalesce(u.total_sent, 0),
                        total_received: coalesce(u.total_received, 0),
                        fraud_ratio: coalesce(u.fraud_ratio, 0),
                        pagerank: coalesce(u.pagerank, 0.0),
                        betweenness: coalesce(u.betweenness, 0.0)
                    } as features
                """, user_id=user_id).single()
                logger.debug(
                    f"Neo4j query for user {user_id} executed in "
                    f"{time.time() - query_start:.4f}s"
                )

                if result and result['features']:
                    logger.debug(f"Found features for user {user_id}")
                    return result['features']
                else:
                    logger.debug(f"User {user_id} not found in"
                                f" Neo4j, using defaults")
                    return default_features

        except Exception as e:
            logger.error(f"Neo4j lookup failed for {user_id}: {e}")
            return default_features

    def close(self):
        self.driver.close()


neo4j_connector = None


def init_neo4j_connector():
    global neo4j_connector
    logger.info("Initializing global Neo4j connector.")
    neo4j_connector = Neo4jStreamingConnector(
        os.getenv("NEO4J_URI"),
        os.getenv("NEO4J_USER"),
        os.getenv("NEO4J_PASSWORD")
    )


def fetch_graph_features(user_id: str) -> Dict:
    if neo4j_connector is None:
        logger.error("Neo4j connector not initialized")
        raise RuntimeError("Neo4j connector not initialized")
    return neo4j_connector.get_user_features(user_id)
