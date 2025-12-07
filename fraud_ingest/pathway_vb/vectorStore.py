import threading
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, TypeAlias, cast
from config import MODEL
import jmespath
import pathway as pw
import pathway.xpacks.llm.parsers
import pathway.xpacks.llm.splitters
from pathway.stdlib.indexing import default_usearch_knn_document_index
from pathway.stdlib.indexing.data_index import _SCORE, DataIndex
from pathway.xpacks.llm._utils import _coerce_sync
from pathway.xpacks.llm._utils import _unwrap_udf

import os
from openai import OpenAI
from loguru import logger
import re
from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    import langchain_core.documents
    import langchain_core.embeddings
    import llama_index.core.schema

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

DOCUMENT_SUMMARY_PROMPT = """
... (KEEP YOUR SUMMARY PROMPT AS IS)
"""


class VectorStoreServerModified:
    """
    DENSE-ONLY vector store server.
    All sparse indexing removed.
    All APIs preserved to avoid breaking existing client code.
    """

    def __init__(
        self,
        *docs: pw.Table,
        embedder: Callable[[str], list[float] | Coroutine] | pw.UDF,
        parser: Callable[
            [bytes],
            list[tuple[str, dict]]
            ] | pw.UDF | None = None,
        splitter: Callable[
            [str],
            list[tuple[str, dict]]
            ] | pw.UDF | None = None,
        doc_post_processors=None,
        save_doc_summary=True,
        save_doc_path="./document.txt",
        store_meta_data_in_chunk=True,
    ):
        self.docs = docs
        self.doc_data = ""

        self.parser = _unwrap_udf(
            parser if parser is not None else pathway.xpacks.llm.parsers.ParseUtf8()
        )

        self.doc_post_processors = []
        self.save_doc_summary = save_doc_summary
        self.save_doc_path = save_doc_path
        self.store_meta_data_in_chunk = store_meta_data_in_chunk

        # SAFEST — autorepair missing summary file
        if self.save_doc_summary:
            os.makedirs(os.path.dirname(save_doc_path), exist_ok=True)
            if not os.path.exists(save_doc_path):
                open(save_doc_path, "w").close()

        if doc_post_processors:
            self.doc_post_processors = [
                _unwrap_udf(p) for p in doc_post_processors if p is not None
            ]

        self.splitter = _unwrap_udf(
            splitter if splitter is not None else pathway.xpacks.llm.splitters.null_splitter
        )

        if isinstance(embedder, pw.UDF):
            self.embedder = embedder
        else:
            self.embedder = pw.udf(embedder)

        # detect embedding dimension
        self.embedding_dimension = len(
            _coerce_sync(self.embedder.__wrapped__)("."))

        # Build internal graph
        self._graph = self._build_graph()
        self.input_files = 0

        if self.save_doc_summary:
            self.remove_doc_summary_in_file()

    @classmethod
    def from_langchain_components(
        cls,
        *docs,
        embedder: "langchain_core.embeddings.Embeddings",
        parser: Callable[[bytes], list[tuple[str, dict]]] | None = None,
        splitter: "langchain_core.documents.BaseDocumentTransformer | None" = None,
        **kwargs,
    ):
        try:
            from langchain_core.documents import Document
        except ImportError:
            raise ImportError(
                "Please install langchain_core: `pip install langchain_core`"
            )

        generic_splitter = None
        if splitter:
            def _generic_splitter(x):
                return [
                    (doc.page_content, doc.metadata)
                    for doc in splitter.transform_documents([Document(page_content=x)])
                ]
            generic_splitter = _generic_splitter

        async def generic_embedded(x: str) -> list[float]:
            res = await embedder.aembed_documents([x])
            return res[0]

        return cls(
            *docs,
            embedder=generic_embedded,
            parser=parser,
            splitter=generic_splitter,
            **kwargs,
        )

    @classmethod
    def from_llamaindex_components(
        cls,
        *docs,
        transformations: list["llama_index.core.schema.TransformComponent"],
        parser: Callable[[bytes], list[tuple[str, dict]]] | None = None,
        **kwargs,
    ):
        try:
            from llama_index.core.base.embeddings.base import BaseEmbedding
            from llama_index.core.ingestion.pipeline import run_transformations
            from llama_index.core.schema import BaseNode, MetadataMode, TextNode
        except ImportError:
            raise ImportError(
                "Please install llama-index-core: `pip install llama-index-core`"
            )

        try:
            from llama_index.legacy.embeddings.base import (
                BaseEmbedding as LegacyBaseEmbedding,
            )

            legacy_llama_index_not_imported = True
        except ImportError:
            legacy_llama_index_not_imported = False

        def node_transformer(x: str) -> list[BaseNode]:
            return [TextNode(text=x)]

        def node_to_pathway(x: list[BaseNode]) -> list[tuple[str, dict]]:
            return [
                (node.get_content(metadata_mode=MetadataMode.NONE), node.extra_info)
                for node in x
            ]

        if transformations is None or not transformations:
            raise ValueError("Transformations list cannot be None or empty.")

        if not isinstance(transformations[-1], BaseEmbedding) and (
            legacy_llama_index_not_imported
            or not isinstance(transformations[-1], LegacyBaseEmbedding)
        ):
            raise ValueError(
                f"Last step of transformations should be an instance of {BaseEmbedding.__name__}, "
                f"found {type(transformations[-1])}."
            )

        embedder = cast(BaseEmbedding, transformations.pop())

        async def embedding_callable(x: str) -> list[float]:
            embedding = await embedder.aget_text_embedding(x)
            return embedding

        def generic_transformer(x: str) -> list[tuple[str, dict]]:
            starting_node = node_transformer(x)
            final_node = run_transformations(starting_node, transformations)
            return node_to_pathway(final_node)

        return VectorStoreServerModified(
            *docs,
            embedder=embedding_callable,
            parser=parser,
            splitter=generic_transformer,
            **kwargs,
        )

    @staticmethod
    def _clean_text(text: str) -> str:
        text_cleaned = re.sub(r"<[^>]*>", "", text)
        text_cleaned = text_cleaned.replace("\xa0", " ").replace("\n", " ")
        text_cleaned = re.sub(r"\s+", " ", text_cleaned).strip()
        return text_cleaned

    def remove_doc_summary_in_file(self):
        if not self.save_doc_path:
            return
        with open(self.save_doc_path, "w") as f:
            f.write("")

    def get_doc_summary(self, text: str) -> str:
        text = self._clean_text(text)
        prompt = DOCUMENT_SUMMARY_PROMPT.format(doc_content=text)

        response = openai_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content
        return response

    def save_doc_summary_in_file(self, text: str) -> None:
        text = self.get_doc_summary(text)
        logger.debug(f"summary - {text}")
        self.input_files += 1

        # Append the new document summary to the file safely
        try:
            with open(self.save_doc_path, "a") as f:
                f.write("<document>\n")
                f.write(text + "\n")
                f.write("</document>\n\n")
        except Exception as e:
            logger.error(f"Failed to write summary file: {e}")

    def _build_graph(self) -> dict:
        docs_s = self.docs
        if not docs_s:
            raise ValueError(
                "Please provide at least one data source, e.g. pw.io.fs.read('./sample_docs', format='binary', mode='static', with_metadata=True)"
            )
        if len(docs_s) == 1:
            (docs,) = docs_s
        else:
            docs: pw.Table = docs_s[0].concat_reindex(
                *docs_s[1:])  # type: ignore

        @pw.udf
        async def parse_doc(data: bytes, metadata) -> list[pw.Json]:
            # Convert Pathway Json metadata → dict
            if hasattr(metadata, "value"):
                metadata = metadata.value

            if isinstance(metadata, pw.Json):
                metadata = metadata.to_dict()

            # THIS is where the await goes — RIGHT HERE
            rets = await self.parser(data)

            out = []
            for text, meta2 in rets:
                if isinstance(meta2, pw.Json):
                    meta2 = meta2.to_dict()

                out.append({
                    "text": text,
                    "metadata": {**metadata, **meta2}
                })

            return out

# type: ignore

        parsed_docs = docs.select(data=parse_doc(
            docs.data, docs._metadata)).flatten(pw.this.data)

        @pw.udf
        def post_proc_docs(data_json: pw.Json) -> pw.Json:
            data: dict = data_json.value  # type:ignore
            text = data["text"]
            metadata = data["metadata"]

            for processor in self.doc_post_processors:
                text, metadata = processor(text, metadata)

            return dict(text=text, metadata=metadata)  # type: ignore

        parsed_docs = parsed_docs.select(data=post_proc_docs(pw.this.data))

        @pw.udf
        def split_doc(data_json: pw.Json) -> list[pw.Json]:
            logger.debug("splitting doc")
            data: dict = data_json.value  # type:ignore
            text = data["text"]
            metadata = data["metadata"]

            if self.save_doc_summary:
                # do not block, but attempt to save summary (best-effort)
                try:
                    self.save_doc_summary_in_file(text)
                except Exception:
                    logger.exception("Failed to save doc summary")

        # If we store metadata in chunk, add a simple delimiter and call splitter
            if self.store_meta_data_in_chunk:
                riched_text = text + "<THIS_IS_A_SPLITTER>" + \
                    (metadata.get("name") if isinstance(metadata, dict) else "")
                rets = self.splitter(riched_text)
            else:
                rets = self.splitter(text)

            # type:ignore
            return [dict(text=ret[0], metadata={**metadata, **ret[1]}) for ret in rets]

        chunked_docs = parsed_docs.select(
            data=split_doc(pw.this.data)).flatten(pw.this.data)

        # ensure a string column for text
        chunked_docs += chunked_docs.select(text=pw.this.data["text"].as_str())
        logger.debug(f"chunks formed and contexted {chunked_docs}")

        # DENSE only: build a usearch dense KNN index
        knn_index = default_usearch_knn_document_index(
            chunked_docs.text,
            chunked_docs,
            dimensions=self.embedding_dimension,
            metadata_column=chunked_docs.data["metadata"],
            embedder=self.embedder,
        )

        parsed_docs += parsed_docs.select(
            modified=pw.this.data["metadata"].get(
                "modified_at", None).as_int(),
            indexed=pw.this.data["metadata"].get("seen_at", None).as_int(),
            path=pw.this.data["metadata"].get("path", None).as_str(),
        )

        stats = parsed_docs.reduce(
            count=pw.reducers.count(),
            last_modified=pw.reducers.max(pw.this.modified),
            last_indexed=pw.reducers.max(pw.this.indexed),
            paths=pw.reducers.tuple(pw.this.path),
        )
        return locals()

    class StatisticsQuerySchema(pw.Schema):
        pass

    class QueryResultSchema(pw.Schema):
        result: pw.Json

    class InputResultSchema(pw.Schema):
        result: list[pw.Json]

    class FilterSchema(pw.Schema):
        metadata_filter: str | None = pw.column_definition(
            default_value=None, description="JMESPath filter expression"
        )
        filepath_globpattern: str | None = pw.column_definition(
            default_value=None, description="Optional file path glob"
        )

    InputsQuerySchema: TypeAlias = FilterSchema

    @staticmethod
    def merge_filters(queries: pw.Table):
        @pw.udf
        def _get_jmespath_filter(metadata_filter: str, filepath_globpattern: str) -> str | None:
            clauses = []
            if metadata_filter:
                mf = (
                    metadata_filter.replace("'", r"\'")
                    .replace("`", "'")
                    .replace('"', "")
                )
                clauses.append(f"({mf})")

            # Keep globmatch because your retriever depends on it
            if filepath_globpattern:
                clauses.append(f"globmatch('{filepath_globpattern}', path)")

            return " && ".join(clauses) if clauses else None

        queries = queries.without(
            *VectorStoreServerModified.FilterSchema.__columns__.keys()
        ) + queries.select(
            metadata_filter=_get_jmespath_filter(
                pw.this.metadata_filter, pw.this.filepath_globpattern
            )
        )
        return queries

    @pw.table_transformer
    def inputs_query(
        self, input_queries: pw.Table[InputsQuerySchema]
    ) -> pw.Table[InputResultSchema]:

        docs = self._graph["docs"]

        # Build tuple of all metadata
        all_metas = docs.reduce(metadatas=pw.reducers.tuple(pw.this._metadata))

        input_queries = self.merge_filters(input_queries)

        @pw.udf
        def filter_metas(metadatas: list[pw.Json] | None, metadata_filter: str | None) -> list[pw.Json]:
            if not metadatas:
                return []
            if not metadata_filter:
                return metadatas

            return [
                m for m in metadatas
                if jmespath.search(metadata_filter, m.value)
            ]

        results = input_queries.join_left(all_metas, id=input_queries.id).select(
            result=filter_metas(pw.this.metadatas, pw.this.metadata_filter)
        )
        return results

    class RetrieveQuerySchema(pw.Schema):
        query: str
        k: int = pw.column_definition(default_value=2)
        metadata_filter: str | None = pw.column_definition(default_value=None)
        filepath_globpattern: str | None = pw.column_definition(
            default_value=None)

    class RetrieveQueryAllChunksSchema(pw.Schema):
        query: str
        metadata_filter: str | None = pw.column_definition(default_value=None)
        filepath_globpattern: str | None = pw.column_definition(
            default_value=None)

    @pw.table_transformer
    def retrieve_query(
        self, retrieval_queries: pw.Table[RetrieveQuerySchema]
    ) -> pw.Table[QueryResultSchema]:

        knn_index: DataIndex = self._graph["knn_index"]
        retrieval_queries = self.merge_filters(retrieval_queries)

        retrieval_results = retrieval_queries + knn_index.query_as_of_now(
            retrieval_queries.query,
            number_of_matches=retrieval_queries.k,
            collapse_rows=True,
            metadata_filter=retrieval_queries.metadata_filter,
        ).select(
            result=pw.coalesce(pw.right.data, ()),
            score=pw.coalesce(pw.right[_SCORE], ()),
        )

        @pw.udf
        def format_results(data_items, scores) -> pw.Json:
            combined = [
                {**item.value, "dist": -score}
                for item, score in zip(data_items, scores)
            ]
            return pw.Json(
                sorted(combined, key=lambda x: x["dist"])
            )

        return retrieval_results.select(
            result=format_results(pw.this.result, pw.this.score)
        )

    @pw.table_transformer
    def retrieve_query_all_chunks(
        self, retrieval_queries: pw.Table[RetrieveQueryAllChunksSchema]
    ) -> pw.Table[QueryResultSchema]:

        knn_index: DataIndex = self._graph["knn_index"]
        retrieval_queries = self.merge_filters(retrieval_queries)

        retrieval_results = retrieval_queries + knn_index.query_as_of_now(
            retrieval_queries.query,
            number_of_matches=3000,   # your original behavior
            collapse_rows=True,
            metadata_filter=retrieval_queries.metadata_filter,
        ).select(
            result=pw.coalesce(pw.right.data, ()),
            score=pw.coalesce(pw.right[_SCORE], ()),
        )

        @pw.udf
        def format_all(data_items, scores) -> pw.Json:
            combined = [
                {**item.value, "dist": -score}
                for item, score in zip(data_items, scores)
            ]
            return pw.Json(
                sorted(combined, key=lambda x: x["dist"])
            )

        return retrieval_results.select(
            result=format_all(pw.this.result, pw.this.score)
        )

    class EmptySchema(pw.Schema):
        pass

    class GetDocumentTextSchema(pw.Schema):
        result: pw.Json

    @pw.table_transformer
    def get_document_text(
        self,
        inp: pw.Table[EmptySchema]
    ) -> pw.Table[GetDocumentTextSchema]:

        content = ""
        if self.save_doc_summary:
            try:
                with open(self.save_doc_path, "r") as f:
                    content = f.read().strip()
            except Exception:
                logger.exception("Failed reading summary file")

        return inp.select(result={"text": [content]})

    @property
    def index(self) -> DataIndex:
        return self._graph["knn_index"]

    def run_server(
        self,
        host,
        port,
        threaded=False,
        with_cache=True,
        cache_backend=pw.persistence.Backend.filesystem("./cache"),
        **kwargs,
    ):
        webserver = pw.io.http.PathwayWebserver(
            host=host, port=port, with_cors=True)

        def serve(route, schema, handler, documentation):
            queries, writer = pw.io.http.rest_connector(
                webserver=webserver,
                route=route,
                methods=("GET", "POST"),
                schema=schema,
                autocommit_duration_ms=50,
                delete_completed_queries=False,
                documentation=documentation,
            )
            writer(handler(queries))

        serve(
            "/v1/retrieve",
            self.RetrieveQuerySchema,
            self.retrieve_query,
            pw.io.http.EndpointDocumentation(
                summary="Dense retrieve",
                description="Returns k nearest dense-matching chunks",
                method_types=("GET",),
            ),
        )

        serve(
            "/v1/retrieve_all_chunks",
            self.RetrieveQueryAllChunksSchema,
            self.retrieve_query_all_chunks,
            pw.io.http.EndpointDocumentation(
                summary="Retrieve all chunks (dense)",
                description="Returns all dense matches up to 3000",
                method_types=("GET",),
            ),
        )

        serve(
            "/v1/inputs",
            self.InputsQuerySchema,
            self.inputs_query,
            pw.io.http.EndpointDocumentation(
                summary="List indexed docs",
                description="Lists metadata for all files",
                method_types=("GET",),
            ),
        )

        serve(
            "/v1/get_doc_text",
            self.EmptySchema,
            self.get_document_text,
            pw.io.http.EndpointDocumentation(
                summary="Retrieve summary text",
                description="Gets combined summary text",
                method_types=("GET",),
            ),
        )

        def run():
            if with_cache:
                persistence = pw.persistence.Config(
                    cache_backend, persistence_mode=pw.PersistenceMode.UDF_CACHING
                )
            else:
                persistence = None

            pw.run(
                monitoring_level=pw.MonitoringLevel.NONE,
                persistence_config=persistence,
                **kwargs,
            )

        if threaded:
            t = threading.Thread(target=run, name="VectorStoreServer")
            t.start()
            return t
        else:
            run()

    def __repr__(self):
        return f"VectorStoreServer(dense-only, dims={self.embedding_dimension})"
