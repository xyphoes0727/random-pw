import json
from typing import TYPE_CHECKING
import requests

if TYPE_CHECKING:
    import llama_index.core.schema


class VectorStoreClientModified:

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        url: str | None = None,
        timeout: int = 15,
        additional_headers: dict | None = None,
    ):
        err = "Either (`host` and `port`) or `url` must be provided, but not both."

        if url is not None:
            if host or port:
                raise ValueError(err)
            self.url = url
        else:
            if host is None:
                raise ValueError(err)
            port = port or 80
            self.url = f"http://{host}:{port}"

        self.timeout = timeout
        self.additional_headers = additional_headers or {}

    def query(
        self,
        query: str,
        k: int = 3,
        metadata_filter: str | None = None,
        filepath_globpattern: str | None = None,
    ) -> list[dict]:

        data = {"query": query, "k": k}

        if metadata_filter:
            data["metadata_filter"] = metadata_filter

        if filepath_globpattern:
            data["filepath_globpattern"] = filepath_globpattern

        url = self.url + "/v1/retrieve"
        response = requests.post(
            url,
            data=json.dumps(data),
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )
        responses = response.json()
        return sorted(responses, key=lambda x: x["dist"])

    def query_all_chunks(
        self,
        query: str,
        metadata_filter: str | None = None,
        filepath_globpattern: str | None = None,
    ) -> list[dict]:

        data = {"query": query}

        if metadata_filter:
            data["metadata_filter"] = metadata_filter
        if filepath_globpattern:
            data["filepath_globpattern"] = filepath_globpattern

        url = self.url + "/v1/retrieve_all_chunks"
        response = requests.post(
            url,
            data=json.dumps(data),
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )
        responses = response.json()
        return sorted(responses, key=lambda x: x["dist"])

    __call__ = query  # shorthand

    def get_input_files(self, metadata_filter=None, filepath_globpattern=None):
        url = self.url + "/v1/inputs"
        response = requests.post(
            url,
            json={
                "metadata_filter": metadata_filter,
                "filepath_globpattern": filepath_globpattern,
            },
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )
        return response.json()

    def get_doc_text(self):
        url = self.url + "/v1/get_doc_text"
        response = requests.post(
            url,
            json={},
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )
        res = response.json()
        return res["text"][0]

    def _get_request_headers(self):
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self.additional_headers)
        return request_headers
