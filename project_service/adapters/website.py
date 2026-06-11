"""Website RAG project adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_service.adapters.base import ProjectAdapter
from project_service.schemas import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectConfig,
    ProjectDocument,
    ProjectQueryScope,
    ProjectRetrievalFilter,
)
from retrieval_service.ingest.source import IngestSourceContent

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
        return _website_ingester()

    async def parse_document(self, input_data: Any) -> WebsiteDocument:
        prepared = await _website_ingester().prepare(input_data)
        return prepared.document

    async def build_chunks(
        self, document: ProjectDocument
    ) -> list[ProjectChunk]:
        return await _website_ingester().build_chunks(
            document,
            _source_from_document(document),
        )

    async def build_payload(self, chunk: ProjectChunk) -> WebsiteChunkPayload:
        return await _website_ingester().build_payload(
            chunk,
            _source_from_chunk(chunk),
        )

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


def _website_ingester() -> Any:
    from project_service.ingest.website import WebsiteIngester

    return WebsiteIngester()


def _source_from_document(document: ProjectDocument) -> IngestSourceContent:
    raw_text = str(document.metadata.get("raw_text", document.source_uri))
    return IngestSourceContent(
        source_uri=document.source_uri,
        text=raw_text,
        raw_content=raw_text.encode("utf-8"),
        content_type=document.content_type,
    )


def _source_from_chunk(chunk: ProjectChunk) -> IngestSourceContent:
    return IngestSourceContent(
        source_uri=str(chunk.metadata.get("url", "")),
        text=chunk.text,
        raw_content=chunk.text.encode("utf-8"),
        content_type="text/plain",
    )
