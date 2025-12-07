"""
Analysis Service - Graph Algorithms and Risk Scoring

This module defines the `AnalysisService`, which uses the Neo4j Graph Data
Science (GDS) library to perform deep analysis on the synchronized graph.

Key functions:
1. Centrality Algorithms: Computes PageRank and Betweenness Centrality.
2. Community Detection: Runs the Louvain algorithm to identify user clusters.
3. Feature Generation: Calculates derived metrics, such as fraud ratio of
neighbors.
4. Risk Scoring: Assigns a composite `risk_score` to each user based on a
weighted combination of graph centrality metrics and fraud metrics.
"""

from neo4j_service.log_config.log_config import get_logger
from neo4j import GraphDatabase
from graphdatascience import GraphDataScience

logger = get_logger(__name__)


class AnalysisService:
    """
    Manages the execution of graph algorithms and the calculation of composite
    risk scores on the Neo4j graph database using GDS.
    """

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        self.neo4j_uri = neo4j_uri

        self.driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password)
        )
        self.gds = GraphDataScience(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password)
        )

        logger.info("AnalysisService initialized")

    def run_centrality_algorithms(self):
        """
        Projects the graph into GDS memory and executes two key centrality
        algorithms:
        1. PageRank: Measures the influence of a user node.
        2.Betweenness Centrality: Measures the control a user has over the
        flow of transactions between other users.

        Results are written back to the User nodes as properties.

        Returns:
            GDSGraph: The in-memory projected graph object.
        """

        graph_name = "fraud-graph"

        if self.gds.graph.exists(graph_name).exists:
            self.gds.graph.drop(self.gds.graph.get(graph_name))

        G, result = self.gds.graph.project(
            graph_name,
            "User",
            "TRANSACTED_WITH"
        )
        logger.info(f"Graph projected: {result['nodeCount']} nodes, {result['relationshipCount']} edges")

        self.gds.pageRank.mutate(G, mutateProperty="pagerank")
        self.gds.graph.nodeProperties.write(G, ["pagerank"])
        logger.info("PageRank completed")

        self.gds.betweenness.mutate(G, mutateProperty="betweenness", samplingSize=1000)
        self.gds.graph.nodeProperties.write(G, ["betweenness"])
        logger.info("Betweenness centrality completed")

        return G

    def run_community_detection(self, G):
        """
        Executes the Louvain algorithm to detect communities or clusters of
        users with dense internal transactions. The resulting `community_id`
        is written back to the User nodes.
        """

        self.gds.louvain.mutate(G, mutateProperty="community_id")
        self.gds.graph.nodeProperties.write(G, ["community_id"])
        logger.info("Louvain community detection completed")

    def calculate_fraud_metrics(self):
        """
        Calculates derived fraud metrics based on neighbors, specifically:
        - `fraud_neighbor_count`: Number of neighbors who are known fraud
        accounts.
        - `fraud_neighbor_ratio`: Ratio of fraud neighbors to total distinct
        neighbors.
        """

        with self.driver.session() as session:
            session.run("""
                MATCH (u:User)
                OPTIONAL MATCH (u)-[:TRANSACTED_WITH]-(n:User WHERE n.fraud_count > 0)
                WITH u, count(DISTINCT n) as fraud_neighbors,
                        count(DISTINCT CASE WHEN n IS NOT NULL THEN n END) as total_neighbors
                SET u.fraud_neighbor_count = fraud_neighbors,
                    u.fraud_neighbor_ratio = CASE
                        WHEN total_neighbors > 0
                        THEN toFloat(fraud_neighbors) / total_neighbors
                        ELSE 0.0
                    END
            """)

        logger.info("Fraud neighbor metrics calculated")

    def calculate_risk_scores(self):
        """
        Calculates a final composite `risk_score` for each user using a
        weighted sum of normalized graph and fraud metrics:
        - Fraud Ratio (0.35)
        - Fraud Neighbor Ratio (0.25)
        - PageRank (0.25)
        - Betweenness Centrality (0.15)

        Also assigns a categorical `risk_level` (CRITICAL, HIGH, MEDIUM, LOW).
        """

        with self.driver.session() as session:
            session.run("""
                MATCH (u:User)
                WHERE u.pagerank IS NOT NULL
                WITH max(u.pagerank) as max_pr,
                max(u.betweenness) as max_bt,
                collect(u) as users
                UNWIND users as u
                WITH u,
                    u.pagerank / max_pr as norm_pr,
                    coalesce(u.betweenness / max_bt, 0) as norm_bt,
                    coalesce(u.fraud_ratio, 0) as norm_fr,
                    coalesce(u.fraud_neighbor_ratio, 0) as norm_fn
                SET u.risk_score = (norm_fr * 0.35 + norm_fn * 0.25 + norm_pr * 0.25 + norm_bt * 0.15),
                    u.risk_level = CASE
                        WHEN u.risk_score > 0.8 THEN 'CRITICAL'
                        WHEN u.risk_score > 0.6 THEN 'HIGH'
                        WHEN u.risk_score > 0.4 THEN 'MEDIUM'
                        ELSE 'LOW'
                    END,
                    u.analysis_timestamp = datetime()
            """)

        logger.info("Risk scores calculated")

    def get_analysis_summary(self) -> dict:
        """
        Retrieves summary statistics on the analyzed graph, including total
        users and the distribution of users across the calculated risk levels.
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (u:User)
                RETURN count(u) as total,
                    avg(u.risk_score) as avg_risk,
                    sum(CASE WHEN u.risk_level = 'CRITICAL' THEN 1 ELSE 0 END) as critical,
                    sum(CASE WHEN u.risk_level = 'HIGH' THEN 1 ELSE 0 END) as high,
                    sum(CASE WHEN u.risk_level = 'MEDIUM' THEN 1 ELSE 0 END) as medium,
                    sum(CASE WHEN u.risk_level = 'LOW' THEN 1 ELSE 0 END) as low
            """).single()

            return {
                'total_users': result['total'],
                'avg_risk': result['avg_risk'] if result['avg_risk'] else 0.0,
                'critical': result['critical'],
                'high': result['high'],
                'medium': result['medium'],
                'low': result['low']
            }

    def analyze(self):
        try:

            G = self.run_centrality_algorithms()

            self.run_community_detection(G)

            self.gds.graph.drop(G)
            logger.info("Graph projection dropped")

            self.calculate_fraud_metrics()

            self.calculate_risk_scores()

            summary = self.get_analysis_summary()

            return summary

        except Exception as e:
            logger.error(f"Error during analysis: {e}", exc_info=True)
            raise

    def close(self):
        self.driver.close()
        logger.info("AnalysisService closed")
