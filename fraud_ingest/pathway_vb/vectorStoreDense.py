import pathway as pw
from loguru import logger
from pathway.xpacks.llm import parsers
from pathway.xpacks.llm.embedders import OpenAIEmbedder
from .vectorStore import VectorStoreServerModified
from .contextSplitter import ContextualRetrievalSplitter


def make_dense_vector_store_server(
    source,
    port: int,
    save_doc_summary: bool,
    save_doc_path: str,
):
    """Start the dense vector store server."""

    logger.info("Initializing dense vector store...")

    # Use Unstructured parser for PDFs
    parser = parsers.ParseUnstructured()

    # Embeddings
    embedder = OpenAIEmbedder()

    # Split large docs
    splitter = ContextualRetrievalSplitter()

    # Build server
    vector_server = VectorStoreServerModified(
        source,
        embedder=embedder,
        parser=parser,
        splitter=splitter,
        save_doc_summary=save_doc_summary,
        save_doc_path=save_doc_path,
        store_meta_data_in_chunk=True,
    )

    # Run HTTP server (blocking)
    vector_server.run_server(
        host="0.0.0.0",
        port=port,
    )
