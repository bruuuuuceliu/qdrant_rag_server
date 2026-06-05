"""Website RAG project adapter.

Implements website-specific models (config, document, payload) and a
full ``ProjectAdapter`` that validates allowed domains, maps website
URLs into document metadata, adds website-specific Qdrant payload
fields, and builds website-specific prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rag_server.adapters.base import ProjectAdapter
from rag_server.core.models import (
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
)

WEBSITE_PROJECT_TYPE = "website"


@dataclass(frozen=True)
class WebsiteProjectConfig(BaseProjectConfig):
    domains: tuple[str, ...] = ()
    crawl_rules: tuple[str, ...] = ()
    sitemap_urls: tuple[str, ...] = ()
    default_locale: str = "en"

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "domains", tuple(self.domains))
        object.__setattr__(self, "crawl_rules", tuple(self.crawl_rules))
        object.__setattr__(self, "sitemap_urls", tuple(self.sitemap_urls))

    def allows_domain(self, domain: str) -> bool:
        if not self.domains:
            return True
        return domain in self.domains


@dataclass(frozen=True)
class WebsiteDocument(BaseDocument):
    url: str = ""
    canonical_url: str = ""
    page_title: str = ""
    page_description: str = ""


@dataclass(frozen=True)
class WebsiteChunkPayload(BaseChunkPayload):
    url: str = ""
    canonical_url: str = ""
    page_title: str = ""
    section_heading: str = ""

    def to_qdrant_payload(self) -> dict[str, Any]:
        payload = super().to_qdrant_payload()
        payload["url"] = self.url
        payload["canonical_url"] = self.canonical_url
        payload["page_title"] = self.page_title
        payload["section_heading"] = self.section_heading
        return payload


class WebsiteProjectAdapter(ProjectAdapter):
    project_type = WEBSITE_PROJECT_TYPE

    def get_domain_from_url(self, url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        hostname = hostname.removeprefix("www.")
        return hostname

    async def get_config(self, project_id: str) -> WebsiteProjectConfig:
        return WebsiteProjectConfig(
            project_id=project_id,
            project_type=self.project_type,
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
            domains=("example.com",),
            default_locale="en",
        )

    async def build_query_scope(self, request: Any) -> BaseQueryScope:
        return BaseQueryScope(
            project_id=request.project_id,
            user_id=request.user_id,
            kb_ids=getattr(request, "kb_ids", ()),
            include_shared=getattr(request, "include_shared", True),
        )

    async def build_retrieval_filter(
        self, scope: BaseQueryScope
    ) -> BaseRetrievalFilter:
        return BaseRetrievalFilter.from_scope(scope)

    async def parse_document(self, input_data: Any) -> WebsiteDocument:
        url = getattr(input_data, "source_uri", "")
        metadata = dict(getattr(input_data, "metadata", {}))
        return WebsiteDocument(
            project_id=input_data.project_id,
            user_id=input_data.user_id,
            kb_id=input_data.kb_id,
            doc_id=input_data.doc_id,
            source_uri=input_data.source_uri,
            content_type=getattr(input_data, "content_type", "text/html"),
            data_type=str(metadata.get("data_type", "document")),
            visibility=str(metadata.get("visibility", "private")),
            content_hash=str(metadata.get("content_hash", "")),
            embedding_version=str(metadata.get("embedding_version", "")),
            chunker_version=str(metadata.get("chunker_version", "v1")),
            metadata=metadata,
            url=url,
            canonical_url=url,
            page_title=url,
            page_description="",
        )

    async def build_chunks(
        self, document: BaseDocument
    ) -> list[BaseChunk]:
        text = document.metadata.get("raw_text", document.source_uri)
        chunks: list[BaseChunk] = []
        paragraphs = text.split("\n\n")
        for idx, paragraph in enumerate(paragraphs):
            cleaned = paragraph.strip()
            if not cleaned:
                continue
            chunks.append(
                BaseChunk(
                    project_id=document.project_id,
                    user_id=document.user_id,
                    kb_id=document.kb_id,
                    doc_id=document.doc_id,
                    chunk_id=f"{document.doc_id}:{idx}",
                    chunk_index=idx,
                    text=cleaned,
                    data_type=document.data_type,
                    visibility=document.visibility,
                    content_hash=document.content_hash,
                    embedding_version=document.embedding_version,
                    chunker_version=document.chunker_version,
                    metadata={"section": str(idx)},
                )
            )
        if not chunks:
            chunks.append(
                BaseChunk(
                    project_id=document.project_id,
                    user_id=document.user_id,
                    kb_id=document.kb_id,
                    doc_id=document.doc_id,
                    chunk_id=f"{document.doc_id}:0",
                    chunk_index=0,
                    text=text,
                    data_type=document.data_type,
                    visibility=document.visibility,
                    content_hash=document.content_hash,
                    embedding_version=document.embedding_version,
                    chunker_version=document.chunker_version,
                )
            )
        return chunks

    async def build_payload(self, chunk: BaseChunk) -> WebsiteChunkPayload:
        url = chunk.metadata.get("url", "")
        section = chunk.metadata.get("section", "")
        title = chunk.metadata.get("page_title", "")
        return WebsiteChunkPayload(
            project_id=chunk.project_id,
            user_id=chunk.user_id,
            kb_id=chunk.kb_id,
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            data_type=chunk.data_type,
            visibility=chunk.visibility,
            content_hash=chunk.content_hash,
            embedding_version=chunk.embedding_version,
            chunker_version=chunk.chunker_version,
            metadata=dict(chunk.metadata),
            url=url,
            canonical_url=url,
            page_title=title,
            section_heading=section,
        )

    async def build_prompt(
        self,
        query: str,
        chunks: list[BaseChunkPayload],
        scope: BaseQueryScope,
    ) -> str:
        context_parts: list[str] = []
        for chunk in chunks:
            payload = chunk.to_qdrant_payload()
            url = payload.get("url", "")
            title = payload.get("page_title", "")
            text = payload.get("text", "")
            source_line = f"[{title}]" if title else ""
            source_line += f"({url})" if url else ""
            context_parts.append(f"{source_line}\n{text}")

        context = "\n\n---\n\n".join(context_parts)
        return (
            "You are a helpful assistant answering questions based on website content.\n"
            "Use only the provided context to answer the question.\n"
            "If the answer is not in the context, say you don't know.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            "Answer:"
        )
