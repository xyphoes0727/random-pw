import pathway as pw
import os
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from typing import List
from tqdm import tqdm
import re
from config import MODEL
from .config import (
    DOCUMENT_CONTEXT_PROMPT,
    CHUNK_CONTEXT_PROMPT,
    FINAL_CHUNK_CONTEXT_PROMPT
)
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def simple_split(text: str, chunk_size: int, overlap: int = 200) -> List[str]:
    """A pure-Python replacement for LangChain's RecursiveCharacterTextSplitter."""
    chunks = []
    start = 0
    n = len(text)

    while start < n:
        end = start + chunk_size
        chunk = text[start:end]

        # try to break at punctuation for cleaner splits
        last_punct = max(chunk.rfind("."), chunk.rfind("?"), chunk.rfind("!"))
        if last_punct != -1 and last_punct > chunk_size * 0.4:
            end = start + last_punct + 1
            chunk = text[start:end]

        chunks.append(chunk)
        start = end - overlap  # create overlap

        if start < 0:
            start = 0

    return chunks


class ContextualRetrievalSplitter(pw.UDF):

    def __init__(self):
        super().__init__()

        self.pages_chunk_size = 3000
        self.chunk_size = 1000
        self.overlap = 200

    @staticmethod
    def _get_chunk_summary(doc: str, chunk: str) -> str:
        completion = openai_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a useful assistant"},
                {
                    "role": "user",
                    "content": (
                        DOCUMENT_CONTEXT_PROMPT.format(doc_content=doc)
                        + CHUNK_CONTEXT_PROMPT.format(chunk_content=chunk)
                    ),
                },
            ],
        )
        return completion.choices[0].message.content

    def process_page(self, page, metadata) -> List[str]:
        page_chunks = simple_split(page, self.chunk_size, self.overlap)

        context = [self._get_chunk_summary(page, chunk) for chunk in page_chunks]

        res = [
            FINAL_CHUNK_CONTEXT_PROMPT.format(
                chunk_content=chunk,
                doc_content=cxt,
                file_name=metadata
            )
            for chunk, cxt in zip(page_chunks, context)
        ]

        return res

    @staticmethod
    def _clean_text(text: str) -> str:
        text_cleaned = re.sub(r'<[^>]*>', '', text)
        text_cleaned = text_cleaned.replace('\xa0', ' ').replace('\n', ' ')
        text_cleaned = re.sub(r'\s+', ' ', text_cleaned).strip()
        return text_cleaned

    def __wrapped__(self, txt: str, **kwargs) -> list[tuple[str, dict]]:
        data = txt.split("<THIS_IS_A_SPLITTER>")

        if len(data) > 1:
            txt = data[0]
            metadata = data[1]
        else:
            txt = data[0]
            metadata = ""

        txt = self._clean_text(txt)

        # PAGE SPLITTING (NO LANGCHAIN)
        pages = simple_split(txt, self.pages_chunk_size, self.overlap)

        chunks = []

        with ThreadPoolExecutor() as executor:
            future_to_page = [
                executor.submit(self.process_page, page, metadata)
                for page in pages
            ]

            chunks_temp = [
                future.result()
                for future in tqdm(
                    as_completed(future_to_page),
                    total=len(pages),
                    desc="Chunking and getting context"
                )
            ]

        for page_chunks in chunks_temp:
            chunks.extend(page_chunks)

        logger.debug(f"Chunks length: {len(chunks)}")

        return [(chunk, {}) for chunk in chunks]

    def __call__(self, text: pw.ColumnExpression, **kwargs) -> pw.ColumnExpression:
        return super().__call__(text, **kwargs)
