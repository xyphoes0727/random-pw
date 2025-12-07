import logging
import pathway as pw
from loguru import logger
from .vectorStoreDense import make_dense_vector_store_server

logging.basicConfig(level=logging.DEBUG)

CRED = "./fraud_ingest/uploaded_files/credentials.json"
FILE_ID = "1HHr3SMCLvvEtXpfaksLRWidkUxcoRJhy"   # must be FILE, not folder


def main():
    logger.info("Reading file from Google Drive...")

    table = pw.io.gdrive.read(
        object_id=FILE_ID,
        service_user_credentials_file=CRED,
        mode="streaming",
        with_metadata=True,
    )

    logger.info("Starting vector store server on port 8765...")
    make_dense_vector_store_server(
        table,
        port=8765,
        save_doc_summary=False,
        save_doc_path="./document_data/document_summary.txt"
    )


if __name__ == "__main__":
    main()