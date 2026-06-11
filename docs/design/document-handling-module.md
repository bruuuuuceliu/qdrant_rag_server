# Document Handling Module Design

## Purpose

The current ingest path depends mostly on adapter-provided `metadata["raw_text"]`
and simple paragraph splitting. That is enough for small examples, but not for a
real documentation pipeline.

This module should turn heterogeneous sources into normalized, chunked,
retrievable text:

```text
URL / uploaded file / raw bytes
  -> fetch or read source
  -> detect content type
  -> parse into structured document text
  -> normalize sections and metadata
  -> chunk into retrieval units
  -> hand chunks to project ingestion
```

Initial target formats:

- URL / HTML
- plain text
- Markdown
- PDF
- DOCX
- optionally PPTX, XLSX, CSV, JSON, and email later

The module should not own retrieval, embeddings, Qdrant, user visibility, or
project authorization. It produces clean document/chunk objects for the existing
project ingest pipeline.

## Ownership Boundary

### `retrieval_service`

Own low-level reusable document handling:

- source fetching
- content-type detection
- parser interfaces
- parser implementations for common file types
- text normalization
- structure-preserving document model
- generic chunking algorithms
- parser diagnostics and errors

This layer should not know project IDs, user IDs, KB IDs, commercial plan rules,
or website-specific allowlists.

### `project_service`

Own project-aware ingestion:

- project/user/KB scope
- allowed domains
- max file size and accepted MIME policy
- adapter-specific metadata mapping
- visibility and data type defaults
- conversion from parsed chunks to `ProjectChunk`
- conversion from project chunks to Qdrant payloads

The existing `ProjectAdapter` remains the boundary that turns project input into
project documents and payloads.

## Proposed File Structure

```text
retrieval_service/
  document_handling/
    __init__.py
    models.py              # SourceBlob, ParsedDocument, DocumentSection, ParseResult
    fetchers.py            # URLFetcher, FileFetcher, FetchPolicy
    detectors.py           # content-type and extension detection
    parsers/
      __init__.py
      base.py              # DocumentParser protocol
      text.py              # text/plain
      markdown.py          # text/markdown
      html.py              # text/html
      pdf.py               # application/pdf
      docx.py              # .docx
      office.py            # optional pptx/xlsx later
    registry.py            # parser registry by MIME/extension
    normalizers.py         # whitespace, headings, page markers
    chunkers.py            # section-aware chunking
    errors.py              # FetchError, ParseError, UnsupportedContentType

project_service/
  document_handling/
    __init__.py
    service.py             # ProjectDocumentHandlingService
    policies.py            # project-level file/url limits
    mapping.py             # ParsedDocument -> ProjectDocument/ProjectChunk

project_service/
  adapters/
    website.py             # uses ProjectDocumentHandlingService
    files.py               # future generic file adapter
```

If a package split feels too large for the first pass, start with
`retrieval_service/document_handling/` and use it from the existing
`WebsiteProjectAdapter`.

## Data Model

### Source Input

```python
@dataclass(frozen=True, slots=True)
class SourceBlob:
    source_uri: str
    content: bytes
    content_type: str
    filename: str = ""
    content_length: int | None = None
    checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

`SourceBlob` is low-level and project-neutral. It can come from:

- HTTP URL
- uploaded file
- object storage
- raw inline content
- local path in development

### Parsed Document

```python
@dataclass(frozen=True, slots=True)
class DocumentSection:
    section_id: str
    text: str
    heading: str = ""
    level: int = 0
    page_number: int | None = None
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_uri: str
    content_type: str
    title: str = ""
    author: str = ""
    language: str = ""
    sections: list[DocumentSection] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

This preserves useful structure for chunking and payload metadata without
forcing every parser to emit the same rich schema.

### Chunk Output

```python
@dataclass(frozen=True, slots=True)
class ParsedChunk:
    chunk_id: str
    text: str
    chunk_index: int
    section_id: str = ""
    heading: str = ""
    page_number: int | None = None
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
```

`project_service` maps this to `ProjectChunk` by adding project/user/KB/doc
scope and visibility.

## Parser Protocol

```python
class DocumentParser(Protocol):
    supported_content_types: tuple[str, ...]
    supported_extensions: tuple[str, ...]

    async def parse(self, source: SourceBlob) -> ParsedDocument:
        ...
```

Parser registry:

```python
class DocumentParserRegistry:
    def register(self, parser: DocumentParser) -> None:
        ...

    def resolve(self, *, content_type: str, filename: str = "") -> DocumentParser:
        ...
```

Resolution order:

1. Explicit trusted `content_type`.
2. MIME sniff from bytes.
3. File extension fallback.
4. Reject with `UnsupportedContentType`.

## Source Fetching

### URL Fetcher

```python
@dataclass(frozen=True, slots=True)
class FetchPolicy:
    max_bytes: int = 25 * 1024 * 1024
    timeout_seconds: float = 20.0
    allowed_schemes: tuple[str, ...] = ("https", "http")
    allowed_domains: tuple[str, ...] = ()
    user_agent: str = "qdrant-rag-server/0.1"

class URLFetcher:
    async def fetch(self, url: str, *, policy: FetchPolicy) -> SourceBlob:
        ...
```

Project-level allowed domains belong in `project_service`; the low-level fetcher
only enforces the supplied policy.

Security requirements:

- reject non-HTTP schemes by default
- block private network targets unless explicitly allowed
- enforce max response size
- enforce timeout
- preserve final URL after redirects
- keep content type from response headers but do not trust it blindly

### File / Upload Fetcher

For local files or upload bytes:

```python
class FileSourceReader:
    async def from_bytes(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str = "",
    ) -> SourceBlob:
        ...
```

## Parser Implementations

### HTML / URL

Responsibilities:

- parse HTML
- remove scripts/styles/nav/footer boilerplate where possible
- preserve title, canonical URL, headings, and links
- emit sections by heading hierarchy

Possible dependencies:

- `beautifulsoup4`
- `readability-lxml` or `trafilatura` later

Output metadata:

```text
title
canonical_url
description
headings
links
source_url
```

### PDF

Responsibilities:

- extract text page by page
- preserve page numbers
- preserve metadata such as title/author if available
- degrade gracefully for scanned/image-only PDFs

Possible dependencies:

- `pypdf` for lightweight text extraction
- optional OCR later, not in first pass

Output metadata:

```text
page_number
pdf_title
pdf_author
is_scanned_candidate
```

First pass should not implement OCR. If a page has no extractable text, emit a
diagnostic and continue.

### DOCX

Responsibilities:

- extract paragraphs
- preserve heading styles
- preserve table text in a readable order
- preserve basic document properties

Possible dependencies:

- `python-docx`
- `mammoth` if HTML-like conversion becomes more useful

Output metadata:

```text
heading
style
table_index
document_title
```

### Markdown

Responsibilities:

- preserve heading hierarchy
- strip or normalize front matter
- keep code blocks as separate sections when useful
- retain links as text plus metadata

Possible dependencies:

- standard parsing first
- `markdown-it-py` later if structure matters

### Plain Text

Responsibilities:

- normalize line endings
- split paragraphs
- preserve source filename and charset

## Chunking Strategy

Use a section-aware chunker instead of direct paragraph splitting.

```python
@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    target_tokens: int = 450
    overlap_tokens: int = 80
    max_tokens: int = 700
    preserve_sections: bool = True

class SectionAwareChunker:
    def chunk(self, document: ParsedDocument, *, config: ChunkingConfig) -> list[ParsedChunk]:
        ...
```

Rules:

- prefer section boundaries
- keep headings attached to their body text
- merge very small adjacent sections
- split very large sections by sentence or paragraph boundaries
- add overlap only across split pieces of the same section
- retain `page_number` for PDF chunks
- retain `heading` for HTML, Markdown, and DOCX chunks

Token counting can start with a simple word estimate. A tokenizer-aware counter
can be added later.

## Project Service Integration

### Project Document Handling Service

```python
class ProjectDocumentHandlingService:
    def __init__(
        self,
        *,
        fetcher: URLFetcher,
        parser_registry: DocumentParserRegistry,
        chunker: SectionAwareChunker,
    ) -> None:
        ...

    async def load_and_chunk(
        self,
        *,
        source_uri: str,
        content_type: str,
        filename: str = "",
        inline_content: bytes | None = None,
        fetch_policy: FetchPolicy,
        chunking: ChunkingConfig,
    ) -> tuple[ParsedDocument, list[ParsedChunk]]:
        ...
```

### Adapter Usage

`WebsiteProjectAdapter` should eventually delegate document loading and chunking:

```text
parse_document()
  -> validate website policy and metadata
  -> call ProjectDocumentHandlingService for URL or inline raw content
  -> wrap ParsedDocument as WebsiteDocument

build_chunks()
  -> map ParsedChunk to ProjectChunk
```

For a future generic file adapter:

```text
FileProjectAdapter
  -> accepts uploaded bytes/object storage key
  -> parses by content type
  -> maps ParsedChunk to ProjectChunk
```

## End-To-End Flows

### URL To Chunks

```text
IngestRequest(source_uri="https://docs.example.com/page", content_type="text/html")
  -> Gateway validates request
  -> WebsiteProjectAdapter checks allowed domain
  -> URLFetcher downloads HTML
  -> content detector confirms HTML
  -> HTMLParser extracts title/headings/main text
  -> SectionAwareChunker creates chunks
  -> WebsiteProjectAdapter maps chunks to ProjectChunk
  -> RagEngine embeds/indexes dense and sparse vectors
```

### PDF Upload To Chunks

```text
IngestRequest(source_uri="upload://file.pdf", content_type="application/pdf")
  -> FileProjectAdapter reads bytes
  -> content detector confirms PDF
  -> PDFParser extracts page text
  -> SectionAwareChunker chunks by page/section
  -> FileProjectAdapter maps chunks with page_number metadata
  -> RagEngine indexes chunks
```

### DOCX Upload To Chunks

```text
IngestRequest(source_uri="upload://handbook.docx", content_type=docx MIME)
  -> FileProjectAdapter reads bytes
  -> DOCXParser extracts headings, paragraphs, tables
  -> SectionAwareChunker chunks by heading
  -> FileProjectAdapter maps chunks with heading/style metadata
  -> RagEngine indexes chunks
```

## Payload Metadata

Recommended chunk payload additions:

```text
source_uri
source_type: url | upload | object_storage | inline
content_type
filename
title
heading
page_number
section_id
section_path
parser_name
parser_version
chunker_version
content_hash
```

These fields improve filtering, debugging, reranking context, citations, and
future rebuilds.

## Configuration

Project-level document handling config:

```python
document_handling_config = {
    "allowed_content_types": [
        "text/html",
        "text/plain",
        "text/markdown",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
    "max_source_bytes": 25 * 1024 * 1024,
    "chunking": {
        "target_tokens": 450,
        "overlap_tokens": 80,
        "max_tokens": 700,
    },
    "url": {
        "allowed_domains": ["docs.example.com"],
        "follow_redirects": True,
    },
}
```

Runtime optional dependency groups:

```toml
[project.optional-dependencies]
documents = [
    "beautifulsoup4>=4.12",
    "pypdf>=4",
    "python-docx>=1.1",
]
```

Later extras:

```toml
documents-heavy = [
    "trafilatura>=1.8",
    "python-pptx>=0.6",
    "openpyxl>=3.1",
]
```

## Error Handling

Use typed errors:

```python
class DocumentHandlingError(Exception): ...
class FetchError(DocumentHandlingError): ...
class SourceTooLargeError(FetchError): ...
class UnsupportedContentTypeError(DocumentHandlingError): ...
class ParseError(DocumentHandlingError): ...
class EmptyDocumentError(DocumentHandlingError): ...
```

Ingest job errors should include:

- source URI
- detected content type
- parser name
- short error message
- whether retry is likely useful

Do not include raw document content in logs.

## Testing Plan

Unit tests:

- content-type detection by header, bytes, and extension
- URL fetch policy enforcement
- parser registry resolution
- HTML parser removes scripts/styles and preserves headings
- PDF parser preserves page numbers
- DOCX parser preserves headings and tables
- chunker respects target size and overlap
- adapter maps parsed chunks into scoped `ProjectChunk`

Integration tests:

- URL HTML ingest to Qdrant
- PDF ingest to Qdrant
- DOCX ingest to Qdrant
- hybrid retrieval over parsed file chunks

Fixtures:

```text
tests/fixtures/documents/sample.html
tests/fixtures/documents/sample.md
tests/fixtures/documents/sample.pdf
tests/fixtures/documents/sample.docx
```

## Implementation Phases

### Phase 1: Neutral Models And Chunker

- Add `retrieval_service/document_handling/models.py`.
- Add `SectionAwareChunker`.
- Add tests for section-aware chunking.
- Keep existing adapters working.

### Phase 2: Parser Registry And Basic Parsers

- Add parser protocol and registry.
- Implement plain text, Markdown, and HTML parsers.
- Update website adapter to use the HTML/text parser path for inline raw text.

### Phase 3: URL Fetching

- Add `URLFetcher` with size, timeout, redirect, and domain policy.
- Integrate URL fetch into `WebsiteProjectAdapter`.
- Keep raw inline text path for tests and simple examples.

### Phase 4: PDF And DOCX

- Add optional `documents` dependency group.
- Implement PDF parser with page metadata.
- Implement DOCX parser with heading/table metadata.
- Add fixtures and parser tests.

### Phase 5: Generic File Adapter

- Add `FileProjectAdapter`.
- Support uploaded bytes or object-storage source keys.
- Map parser metadata into payload metadata.

### Phase 6: Durable Raw Source And Rebuilds

- Make raw content a first-class ingest input.
- Store raw source bytes before parsing.
- Save `raw_storage_key`, parser version, and chunker version for rebuilds.

## Acceptance Criteria

- Existing simple examples still work with inline `raw_text`.
- URL, PDF, DOCX, Markdown, and text sources can produce `ProjectChunk` objects.
- Parser failures fail the ingest job clearly.
- File type support is controlled by parser registry and project policy.
- The engine remains parser-agnostic.
- Parsed chunks carry enough metadata for citations and debugging.
- Unit tests cover each parser and the chunker.
- Optional parser dependencies are not required for dense-only or simple text use.
