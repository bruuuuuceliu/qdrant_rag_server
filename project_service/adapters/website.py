"""Website RAG project adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_service.adapters.base import ProjectAdapter
from project_service.config.repository import ProjectConfigNotFoundError
from project_service.schemas import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectConfig,
    ProjectDocument,
    ProjectQueryScope,
    ProjectRetrievalFilter,
)
from retrieval_service.core.schemas import BaseChunk, BaseDocument
from retrieval_service.ingest.ingester import PreparedIngestData, UniversalSourceIngester

WEBSITE_PROJECT_TYPE = "website"


@dataclass(frozen=True)
class WebsiteProjectConfig(ProjectConfig):
    domains: tuple[str, ...] = ()
    crawl_rules: tuple[str, ...] = ()
    sitemap_urls: tuple[str, ...] = ()
    default_locale: str = "en"

    def __post_init__(self) -> None:
        ProjectConfig.__post_init__(self)
        object.__setattr__(self, "domains", tuple(self.domains))
        object.__setattr__(self, "crawl_rules", tuple(self.crawl_rules))
        object.__setattr__(self, "sitemap_urls", tuple(self.sitemap_urls))

    def allows_domain(self, domain: str) -> bool:
        if not self.domains:
            return True
        return domain in self.domains


@dataclass(frozen=True)
class WebsiteDocument(ProjectDocument):
    url: str = ""
    canonical_url: str = ""
    page_title: str = ""
    page_description: str = ""


@dataclass(frozen=True)
class WebsiteChunkPayload(ProjectChunkPayload):
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

    def __init__(self, *, config_repo: Any = None) -> None:
        self._config_repo = config_repo

    def get_domain_from_url(self, url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        hostname = hostname.removeprefix("www.")
        return hostname

    async def get_config(self, project_id: str) -> WebsiteProjectConfig:
        stored = None
        if self._config_repo is not None:
            try:
                stored = await self._config_repo.get_project_config(project_id)
            except ProjectConfigNotFoundError:
                pass

        if stored is not None:
            return WebsiteProjectConfig(
                project_id=project_id,
                project_type=self.project_type,
                active_embedding_version=stored.active_embedding_version,
                embedding_model=stored.embedding_model,
                reranker_model=stored.reranker_model,
                domains=_string_tuple(
                    stored.chunker_config.get("domains")
                    or stored.chunker_config.get("allowed_domains")
                    or stored.retrieval_config.get("domains")
                    or stored.retrieval_config.get("allowed_domains")
                    or ()
                ),
                crawl_rules=_string_tuple(stored.chunker_config.get("crawl_rules", ())),
                sitemap_urls=_string_tuple(stored.chunker_config.get("sitemap_urls", ())),
                default_locale=str(stored.chunker_config.get("default_locale", "en")),
            )

        return WebsiteProjectConfig(
            project_id=project_id,
            project_type=self.project_type,
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
            default_locale="en",
        )

    async def build_query_scope(self, request: Any) -> ProjectQueryScope:
        return ProjectQueryScope(
            project_id=request.project_id,
            user_id=request.user_id,
            kb_ids=getattr(request, "kb_ids", ()),
            include_shared=getattr(request, "include_shared", True),
        )

    async def build_retrieval_filter(
        self, scope: ProjectQueryScope
    ) -> ProjectRetrievalFilter:
        return ProjectRetrievalFilter.from_scope(scope)

    async def select_ingester(
        self,
        request: Any,
        *,
        config: ProjectConfig | None = None,
    ) -> Any:
        del request, config
        return UniversalSourceIngester()

    async def adapt_ingest_output(
        self,
        prepared: PreparedIngestData,
        request: Any,
        *,
        config: ProjectConfig | None = None,
    ) -> PreparedIngestData:
        del config
        document = _render_document(prepared.document, request=request)
        chunks = tuple(
            _render_chunk(chunk, document=document) for chunk in prepared.chunks
        )
        payloads = tuple(_render_payload(chunk) for chunk in chunks)
        return PreparedIngestData(
            document=document,
            chunks=chunks,
            payloads=payloads,
            raw_content=prepared.raw_content,
        )

    async def parse_document(self, input_data: Any) -> WebsiteDocument:
        prepared = await UniversalSourceIngester().prepare(input_data)
        return _render_document(prepared.document, request=input_data)

    async def build_chunks(
        self, document: ProjectDocument
    ) -> list[ProjectChunk]:
        raw_text = str(document.metadata.get("raw_text", document.source_uri))
        chunks: list[ProjectChunk] = []
        for idx, paragraph in enumerate(raw_text.split("\n\n")):
            cleaned = paragraph.strip()
            if not cleaned:
                continue
            chunks.append(
                ProjectChunk(
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
                ProjectChunk(
                    project_id=document.project_id,
                    user_id=document.user_id,
                    kb_id=document.kb_id,
                    doc_id=document.doc_id,
                    chunk_id=f"{document.doc_id}:0",
                    chunk_index=0,
                    text=raw_text,
                    data_type=document.data_type,
                    visibility=document.visibility,
                    content_hash=document.content_hash,
                    embedding_version=document.embedding_version,
                    chunker_version=document.chunker_version,
                )
            )
        return chunks

    async def build_payload(self, chunk: ProjectChunk) -> WebsiteChunkPayload:
        return _render_payload(chunk)

    async def build_prompt(
        self,
        query: str,
        chunks: list[ProjectChunkPayload],
        scope: ProjectQueryScope,
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


def _render_document(document: BaseDocument, *, request: Any) -> WebsiteDocument:
    metadata = dict(getattr(document, "metadata", {}) or {})
    metadata.update(dict(getattr(request, "metadata", {}) or {}))
    source_uri = getattr(request, "source_uri", document.source_uri)
    return WebsiteDocument(
        project_id=request.project_id,
        user_id=request.user_id,
        kb_id=getattr(request, "kb_id", ""),
        doc_id=getattr(request, "doc_id", document.document_id),
        source_uri=source_uri,
        content_type=getattr(request, "content_type", document.content_type),
        data_type=document.data_type,
        visibility=str(metadata.get("visibility", "private")),
        content_hash=document.content_hash,
        embedding_version=str(metadata.get("embedding_version", "")),
        chunker_version=str(metadata.get("chunker_version", "v1")),
        metadata=metadata,
        url=source_uri,
        canonical_url=source_uri,
        page_title=source_uri,
        page_description="",
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value if str(item))


def _render_chunk(chunk: BaseChunk, *, document: WebsiteDocument) -> ProjectChunk:
    metadata = dict(getattr(chunk, "metadata", {}) or {})
    metadata.setdefault("url", document.url)
    metadata.setdefault("page_title", document.page_title)
    return ProjectChunk(
        project_id=document.project_id,
        user_id=document.user_id,
        kb_id=document.kb_id,
        doc_id=document.doc_id,
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        data_type=chunk.data_type,
        visibility=document.visibility,
        content_hash=chunk.content_hash,
        embedding_version=document.embedding_version,
        chunker_version=chunk.chunker_version,
        metadata=metadata,
    )


def _render_payload(chunk: ProjectChunk) -> WebsiteChunkPayload:
    url = chunk.metadata.get("url", "")
    section = chunk.metadata.get("section", "")
    title = chunk.metadata.get("page_title", "")
    return WebsiteChunkPayload(
        payload_id=chunk.chunk_id,
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
