import pathway as pw
import threading
from loguru import logger
import time
from .vectorRetriever import VectorStoreRetriever
from .vectorStoreDense import make_dense_vector_store_server


def wait_for_server_ready(
    port: int,
    max_retries: int = 20,
    delay: float = 1.0
) -> bool:
    """Wait until dense vector store server starts responding."""
    client = VectorStoreRetriever("0.0.0.0", port)

    for attempt in range(1, max_retries + 1):
        try:
            num_files = client.get_num_input_files()
            logger.info(
                f"Server on port {port} responded with {num_files} files")
            return True
        except Exception as e:
            logger.debug(f"Attempt {attempt}: server not ready yet → {e}")
            time.sleep(delay)

    logger.error(
        f"Server on port {port} did not start after {max_retries} attempts")
    return False


def run_vector_store(
    credential_path: str,
    object_id: str,
    dense_port: int = 8765,
    summary_path: str = "./document_data/document_summary.txt"
) -> None:
    """Starts the dense vectorstore server and waits until it becomes ready."""

    # IMPORTANT: GDrive READ must be correct
    table = pw.io.gdrive.read(
        object_id=object_id,  # MUST BE A FILE ID
        service_user_credentials_file=credential_path,
        mode="streaming",
        with_metadata=True
    )

    # Start dense server
    dense_thread = threading.Thread(
        target=make_dense_vector_store_server,
        args=(table, dense_port, True, summary_path),
        daemon=True
    )
    dense_thread.start()
    logger.info("Dense server initiated")

    # Health check
    if not wait_for_server_ready(dense_port):
        raise RuntimeError("Dense vectorstore failed to start")

    logger.info("Dense vectorstore is ready and running")

    # KEEP MAIN THREAD ALIVE
    while True:
        time.sleep(10)


if __name__ == "__main__":
    run_vector_store(
        credential_path="fraud_ingest/uploaded_files/credentials.json",
        object_id="1HHr3SMCLvvEtXpfaksLRWidkUxcoRJhy"
    )
