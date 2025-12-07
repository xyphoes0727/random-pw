"""
Main Service - Orchestrates Sync and Analysis

This module runs the **Neo4j Graph Service**, which is responsible for the
periodic synchronization of user-to-user graph data from a remote Delta Lake
storage (on AWS S3) into a Neo4j database, followed by graph analysis
(e.g., centrality algorithms) to generate features.

The process runs in cycles:
1. Sync: Imports new graph edges from all partitioned Delta Lake paths.
2. Analyze: If new data was synced, it runs graph algorithms on Neo4j.

It uses `BlockingScheduler` to execute this cycle at regular intervals
(1 minute).
"""

import os
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from neo4j_service.sync import SyncService
from neo4j_service.analyse import AnalysisService
from neo4j_service.log_config.log_config import get_logger
logger = get_logger(__name__)


current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '.env')
load_dotenv(dotenv_path=dotenv_path)


class Neo4jGraphService:
    """
    Orchestrates the continuous sync of graph edges from Delta Lake to Neo4j
    and the subsequent graph analysis to generate features.
    """

    def __init__(self):
        self.neo4j_uri = os.getenv("NEO4J_URI")
        self.neo4j_user = os.getenv("NEO4J_USER")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD")
        self.delta_path = os.getenv("USER_USER_GRAPH_PATH")

        self.instances = [0, 1, 2]

        self.storage_options = {
            "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "AWS_REGION": os.getenv("AWS_REGION"),
        }

        self.sync_service = SyncService(
            self.neo4j_uri,
            self.neo4j_user,
            self.neo4j_password,
            self.delta_path,
            self.storage_options,
            self.instances
        )

        self.analysis_service = AnalysisService(
            self.neo4j_uri,
            self.neo4j_user,
            self.neo4j_password
        )

        logger.info(f"Neo4j Graph Service "
                    f"initialized for instances: {self.instances}")

    def run_cycle(self):
        try:
            logger.info("Starting sync and analysis cycle")

            has_new_data = self.sync_service.sync()

            if has_new_data:
                self.analysis_service.analyze()
            else:
                logger.info("Skipping analysis - no new data in any instance")
            logger.info("Cycle completed successfully")

        except Exception as e:
            logger.error(f"Error in cycle: {e}", exc_info=True)

    def close(self):
        self.sync_service.close()
        self.analysis_service.close()
        logger.info("Neo4j Graph Service closed")


def validate_environment():
    required_vars = [
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "USER_USER_GRAPH_PATH",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY"
    ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        return False

    return True


def main():
    logger.info("Starting Neo4j Graph Service")

    if not validate_environment():
        logger.error("Environment validation failed")
        return

    service = Neo4jGraphService()

    logger.info("Running initial cycle...")
    service.run_cycle()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        service.run_cycle,
        'interval',
        minutes=1,
        id='sync_and_analyze_job',
        name='Sync Delta Lake to Neo4j and analyze'
    )

    logger.info("Scheduler started - running every 1 minute")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        service.close()


if __name__ == "__main__":
    main()
