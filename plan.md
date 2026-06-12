# Ingestion Review And Improvement Plan

**Reviewed**: 2026-06-12

## Current Status

The ingestion path is a useful prototype scaffold, but it is not production-ready yet.
It can accept an ingest request, load simple source text, chunk it, embed it, optionally
create sparse BM25 vectors, write Qdrant points, track an async job in memory, and
invalidate caches after success.

Main implemented flow:

```text
Project caller / gRPC
  -> RagGateway.prepare_ingest()
  -> adapter resolution and project config
  -> adapter.select_ingester()
  -> RagEngine.schedule_ingest()
  -> in-memory job status + async worker queue
  -> IngestPipeline.run()
  -> source loading / adapter parsing
  -> project payload mapping
  -> optional raw document backup
  -> dense embedding and optional sparse encoding
  -> Qdrant upsert
  -> cache invalidation
```

Key files:

- `project_service/gateway/gateway.py` builds `IngestPlan` objects.
- `project_service/rag/engine.py` schedules jobs, runs workers, updates status, deletes documents, and reads raw backups.
- `retrieval_service/ingest/source.py` loads source text from `metadata["raw_text"]`, HTTP(S), `file://`, local paths, or falls back to `source_uri` as text.
- `retrieval_service/ingest/ingester.py` defines `UniversalSourceIngester`, `AdapterBackedIngester`, and the current paragraph chunker.
- `retrieval_service/ingest/pipeline.py` stores raw content, enriches entities, creates dense and sparse vectors, and writes to Qdrant.
- `retrieval_service/ingest/workers.py` provides the async worker queue.
- `retrieval_service/ingest/jobs.py` provides the in-memory job-status repository.
- `project_service/adapters/website.py` maps neutral ingest output into website-scoped project documents, chunks, and payloads.

## Target Shape: Standalone Ingestion Package And Service

Ingestion should move out of `retrieval_service` and become a standalone package
and service. Treat it as a reusable file/document processing product, not a
retrieval submodule.

Retrieval should consume normalized document/chunk outputs from ingestion. It
should not own file fetching, MIME routing, parsing, OCR decisions, chunking, or
raw-source lifecycle.

Target ownership:

```text
ingestion_service
  owns: source loading, file routing, document handlers, parsing, chunking,
        raw source backup metadata, ingest job status, route decisions

project_service
  owns: project policy, user/KB scope, adapter-specific mapping, authorization

retrieval_service
  owns: embeddings, sparse encoding, Qdrant upsert/search/delete, retrieval config
```

The ingestion package should introduce a file router in front of document
handling. The router decides which handler owns a source based on trusted content
type, detected MIME type, file extension, source scheme, available resources, and
project policy.

```text
IngestRequest
  -> project policy resolution
  -> ingestion_service.SourceResolver
  -> ingestion_service.FileRouter
       -> TextDocumentHandler
       -> MarkdownDocumentHandler
       -> HtmlDocumentHandler
       -> PdfDocumentHandler
       -> DocxDocumentHandler
       -> future handlers: csv, json, pptx, xlsx, email
  -> IngestedDocument + IngestedChunk list
  -> retrieval indexing request
  -> dense/sparse indexing in retrieval_service
```

The router should be project-neutral and live under `ingestion_service`. It should
not hard-code project IDs, user IDs, KB IDs, visibility, or authorization.
Project policy should be passed into it as explicit constraints such as allowed
MIME types, allowed extensions, allowed source schemes, max bytes, allowed
domains, and resource tier.

Each document handler should own one file family end to end:

- detection confidence and supported MIME types/extensions
- parsing into a structured `IngestedDocument`
- format-specific metadata extraction
- chunk-friendly section output
- clear typed errors when a file is unsupported, empty, corrupt, or too large

The project adapter should remain responsible for project-specific policy and
mapping, but file parsing and chunk construction should come from
`ingestion_service`.

### Resource-Aware Routing

The router should not choose only by file type. It should choose by file type plus
available resources and project policy.

Suggested resource tiers:

| Tier | Use when | Handler profile |
| --- | --- | --- |
| `minimal` | 1 CPU / 1 GB workers, local dev, constrained containers, high throughput | Pure Python or small CPU libraries; no OCR, no PyTorch, no local ML model downloads. |
| `docling_sidecar` | Larger document-conversion worker or external service | Docling conversion with strict job limits; OCR/VLM optional and disabled by default. |

Router inputs:

- declared content type from the request
- detected MIME type from bytes
- file extension and filename
- source scheme such as `https`, `file`, `upload`, `s3`, or `memory`
- file size and page/slide/sheet count when cheap to detect
- project policy: allowed types, max bytes, allowed domains, OCR permission
- runtime capabilities: installed extras, OCR binaries, GPU availability, max RAM, timeout budget

Selection rule:

```text
eligible handlers = handlers supporting type and allowed by project policy
rank by:
  1. confidence in type match
  2. handler resource cost within current budget
  3. expected output quality for the document shape
  4. operational safety and license fit
  5. deterministic fallback order
```

The router should support escalation. For example, a digitally born PDF can start
with a native text handler; if output is empty, garbled, or table-heavy, return a
`needs_docling_conversion` decision when the project policy allows it.

### 1 CPU / 1 GB Worker Profile

For the planned worker size, default to `minimal`. Treat Docling as disabled
inside the 1 CPU / 1 GB ingest worker unless a small-document benchmark proves it
is safe. Route Docling jobs to a larger sidecar worker or an external conversion
service by default.

Recommended defaults:

- `RAG_DOCUMENT_RESOURCE_TIER=minimal`
- one document parse per worker process
- no OCR in the ingest worker
- no PyTorch-backed document parsers in the ingest worker
- no local VLM/LLM cleanup in the ingest worker
- remote embedding provider preferred, or small embedding batches if local
- parse timeout: 10-30 seconds per document, depending on source type
- max source bytes: start around 5-10 MB for HTML/text/Markdown and 10-25 MB for PDF/DOCX/PPTX/XLSX
- max pages/slides/sheets: enforce hard caps before parsing
- embedding batch size: small, for example 8-16 chunks
- Qdrant upsert batch size: moderate, for example 32-64 chunks
- stream or page-iterate where possible; do not keep extracted images or full intermediate render trees

Handlers that fit this worker:

| Handler | Fit | Constraints |
| --- | --- | --- |
| `TextDocumentHandler` | Yes | Stream/decode with size caps. |
| `MarkdownDocumentHandler` | Yes | Use a lightweight parser or line-based section parser first. |
| `HtmlDocumentHandler` | Yes | Prefer lightweight extraction; `trafilatura` can be enabled with response-size and timeout caps. |
| `CsvHandler` | Yes | Stream rows and chunk by row windows. |
| `XlsxHandler` | Conditional | Use `openpyxl` read-only mode, cap sheets/rows/cells, skip styles/images. |
| `DocxNativeHandler` | Conditional | Use `python-docx`, cap file size, paragraphs, tables, and images; extract text/tables only. |
| `PptxNativeHandler` | Conditional | Use `python-pptx`, cap slide count, skip image extraction and OCR. |
| `PdfNativeTextHandler` | Yes for digital PDFs | Prefer fast text-layer extraction. Cap pages and bytes; escalate scanned/empty PDFs. |
| `ArchiveHandler` | Conditional | Enable only with strict file count, depth, expansion ratio, and child-size limits. |
| `MarkItDownHandler` | Conditional fallback | Do not install `[all]`; install only narrow extras and call narrow conversion paths. |

Handlers that should not run inside a 1 CPU / 1 GB worker:

| Handler | Reason |
| --- | --- |
| `DoclingDocumentHandler` | Useful, but PyTorch/model-backed; run in a larger sidecar with OCR/VLM disabled by default. |
| audio/video handlers | ASR and media extraction do not fit the worker budget. |

Scanned PDFs, image-only documents, complex tables, formulas, and layout-heavy
PDFs should return a clear `needs_docling_conversion` route decision. The caller
can then queue the document for a Docling sidecar and later ingest the resulting
Markdown/JSON through the fast path.

### Proposed File Path Design

```text
ingestion_service/
  __init__.py
  schemas/
    __init__.py
    source.py              # SourceBlob, SourceDescriptor
    documents.py           # IngestedDocument, IngestedSection, IngestedChunk
    jobs.py                # IngestionJob, status/progress DTOs
    policy.py              # DocumentHandlingPolicy, ResourceBudget
    routing.py             # RouteDecision, HandlerCandidate
  source/
    __init__.py
    fetchers.py            # URLFetcher, LocalFileReader, ObjectStorageReader
    detectors.py           # MIME, extension, byte-signature, text-layer probes
  routing/
    __init__.py
    router.py              # FileRouter
    capabilities.py        # detects installed extras, OCR tools, GPU availability
  handlers/
    __init__.py
    base.py                # DocumentHandler protocol
    text.py                # TextDocumentHandler
    markdown.py            # MarkdownDocumentHandler
    html.py                # HtmlDocumentHandler
    pdf_native.py          # PdfNativeTextHandler, low-resource PyMuPDF/pypdf path
    docling.py             # DoclingDocumentHandler, sidecar/external profile
    docx.py                # DocxNativeHandler
    pptx.py                # PptxNativeHandler
    spreadsheet.py         # CsvHandler, XlsxHandler
    archive.py             # ZipArchiveHandler, recursively routes children
    generic_markdown.py    # MarkItDownHandler for broad fallback conversion
  chunking/
    __init__.py
    section.py             # SectionAwareChunker
    tables.py              # table-aware row/window chunking
  normalization/
    __init__.py
    text.py
    metadata.py
  storage/
    __init__.py
    raw.py                 # raw source storage metadata helpers
  jobs/
    __init__.py
    repository.py          # durable ingestion job repository protocol
    memory.py
    sqlite.py
  service.py               # IngestionService orchestration
  errors.py                # typed fetch/route/parse/chunk/job errors

project_service/
  document_handling/
    __init__.py
    service.py             # ProjectDocumentHandlingService
    policies.py            # project-specific allowed types/domains/resource tiers
    mapping.py             # IngestedDocument/IngestedChunk -> project DTOs

retrieval_service/
  indexing/
    ingestion.py           # IngestedChunk -> VectorPayload mapping and upsert orchestration

tests/
  fixtures/
    documents/
      sample.txt
      sample.md
      sample.html
      sample.pdf
      scanned.pdf
      table.pdf
      sample.docx
      sample.pptx
      sample.xlsx
      sample.csv
      archive.zip
  test_document_router.py
  test_document_handlers_*.py
```

### Initial Handler Catalog

| Handler | File types | Default tier | Method | Notes |
| --- | --- | --- | --- | --- |
| `TextDocumentHandler` | `.txt`, `text/plain` | `minimal` | Decode bytes with charset fallback and paragraph/line sectioning. | Always available. |
| `MarkdownDocumentHandler` | `.md`, `.markdown` | `minimal` | Preserve headings, lists, code blocks, and front matter. | Can start with local parsing; add `markdown-it-py` later if needed. |
| `HtmlDocumentHandler` | `.html`, `.htm`, `text/html`, URL HTML | `minimal` | Use safe fetch policy, then extract main content and metadata. | `trafilatura` can be enabled with response-size and timeout caps; otherwise use a simple HTML text extractor. |
| `PdfNativeTextHandler` | `.pdf` | `minimal` | Use PyMuPDF or `pypdf` page text extraction; no OCR. | Good for simple digital PDFs; reject/escalate on scanned or garbled pages. |
| `DocxNativeHandler` | `.docx` | `minimal` | Use `python-docx` to read paragraphs, headings, tables, core properties. | Cheap and predictable; not a full visual conversion. |
| `PptxNativeHandler` | `.pptx` | `minimal` | Use `python-pptx` to extract slide text, tables, notes, and metadata. | Route one slide or logical section per parsed chunk. |
| `SpreadsheetHandler` | `.csv`, `.tsv`, `.xlsx`, `.xlsm` | `minimal` | Use stdlib CSV and `openpyxl`; produce schema, sheet, row-window, and table chunks. | Tables should not be flattened into arbitrary paragraphs by default. |
| `MarkItDownHandler` | broad fallback | `minimal` | Convert selected formats to Markdown with per-format optional extras. | Do not install `[all]`; route through narrow conversion functions and sanitize inputs. |
| `ArchiveHandler` | `.zip` | `minimal` | Expand with file count, depth, and byte limits; route children recursively. | Must protect against zip bombs and path traversal. |
| `DoclingDocumentHandler` | PDF, DOCX, PPTX, XLSX, HTML, images, and more | `docling_sidecar` | Use Docling to produce Markdown/JSON when low-cost handlers are insufficient. | Sidecar only by default; disable OCR/VLM unless explicitly enabled. |

### Handler Research Notes

- `Docling` supports many formats, advanced PDF understanding, local execution,
  OCR, tables, and a unified document representation. It requires PyTorch-backed
  models, so keep it in the `docling_sidecar` profile unless benchmarks prove
  small-document safety inside 1 CPU / 1 GB workers:
  https://docling-project.github.io/docling/getting_started/installation/
- `MarkItDown` is a lightweight Markdown converter for many document types and
  supports optional dependency groups per format; its security note means the
  router should call the narrowest conversion path and sanitize inputs:
  https://github.com/microsoft/markitdown
- `trafilatura` is a strong HTML/web text extraction option with metadata,
  boilerplate reduction, and multiple output formats:
  https://trafilatura.readthedocs.io/en/latest/
- `pypdf`, `python-docx`, `python-pptx`, and `openpyxl` are useful low-resource
  native handlers for PDFs, DOCX, PPTX, and XLSX respectively:
  https://pypdf.readthedocs.io/en/stable/user/extract-text.html,
  https://python-docx.readthedocs.io/en/latest/,
  https://python-pptx.readthedocs.io/en/latest/,
  https://openpyxl.readthedocs.io/en/stable/
- `MinerU` was reviewed but is not included in the target handler set. It is
  powerful and supports pure CPU mode, but its published local deployment table
  lists minimum RAM of 16 GB and minimum disk of 20 GB, far above the 1 CPU /
  1 GB worker budget:
  https://github.com/opendatalab/MinerU

## What Works

- The architecture already has the beginnings of a useful separation between project policy and low-level ingestion primitives.
- The gateway resolves project adapters and normalizes ingest requests before engine execution.
- The engine uses background workers and exposes job status.
- The ingest pipeline is retrieval-mode aware: dense mode writes dense vectors; hybrid/BM25-capable ingest writes dense and sparse vectors to the same Qdrant point.
- Raw content backup exists at the engine level when `object_storage` is provided.
- Project-scoped payloads include `project_id`, `user_id`, `kb_id`, `doc_id`, visibility, chunk metadata, content hash, embedding version, and chunker version.
- Tests cover basic job status transitions, failure status, raw storage behavior, website adapter mapping, cache invalidation, and mocked hybrid ingest.

## Main Gaps

1. Document parsing is still minimal.

   `UniversalSourceIngester` treats sources as text and splits on blank lines. HTML is not cleaned, titles/headings are not parsed, PDFs and DOCX files are not parsed, tables are not handled, and chunk metadata is shallow.

2. Source loading needs safety policy.

   HTTP loading follows redirects without project-level domain enforcement, private-network blocking, or response size limits. Local path loading is convenient for development, but risky in a server context unless it is explicitly disabled or restricted.

3. Website adapter policy is not enforced.

   `WebsiteProjectConfig.allows_domain()` exists, but the current ingest path does not reject disallowed domains before fetching.

4. Ingest jobs are not durable.

   Job state is stored in memory. A restart loses pending, running, completed, and failed job history. There is no durable error record, retry count, progress detail, or worker ownership metadata.

5. The queue defaults are unsafe for production.

   `AsyncIngestWorkerQueue` supports `maxsize`, but `RagEngine` defaults it to `0`, which means unbounded. App settings expose worker count but not queue depth.

6. App bootstrap does not wire object storage.

   Storage adapters and config helpers exist, and `RagEngine` accepts `object_storage`, but `project_service/server/app.py` does not currently build and pass object storage into the engine.

7. Raw content is not a first-class API input.

   Simple ingest depends mostly on `metadata["raw_text"]`. gRPC/proto does not expose explicit raw bytes, object-storage keys, file names, or source type.

8. Reingest idempotency is incomplete.

   Upsert overwrites stable chunk identities, but if a reingested document produces fewer chunks than a previous version, old higher-index chunks can remain unless the document is deleted first.

9. Large documents are processed as one batch.

   The pipeline embeds all chunk text, sparse-encodes all sparse text, and upserts all payloads in one call. This can exceed provider limits or memory limits for large documents.

10. Test coverage is mostly mocked.

   Current tests are useful for wiring, but there are no live Qdrant ingest tests, no queue saturation tests, no parser fixtures, no SSRF/domain-policy tests, and no durable job repository tests.

## Recommended Improvements

### Phase 1: Harden The Existing Ingest Path

- Add an explicit `RAG_INGEST_QUEUE_MAXSIZE` setting and pass it into `RagEngine`.
- Replace or supplement `MemoryIngestJobStatusRepository` with a SQLite-backed repository.
- Track job fields such as `created_at`, `updated_at`, `started_at`, `finished_at`, `chunk_count`, `error_code`, `error_message`, `retry_count`, and `raw_storage_key`.
- Wire object storage in `project_service/server/app.py` using `configs/storage/config.py`.
- Add a first-class raw content path to request handling: raw bytes or an object-storage source key, not only `metadata["raw_text"]`.
- Enforce website domain policy before HTTP fetching.
- Add HTTP fetch safety controls: max bytes, timeout, redirect policy, user agent, allowed schemes, and private-network blocking.
- Disable local path ingestion by default in server mode, or restrict it to an allowed root.
- Delete existing Qdrant points for `(project_id, user_id, kb_id, doc_id)` before replacing a document, or implement a document-version marker that filters out stale chunks.
- Batch embedding, sparse encoding, and Qdrant upserts with configurable batch sizes.

### Phase 2: Extract A Standalone Ingestion Package

Use the existing `docs/design/document-handling-module.md` as the blueprint, but
move the implementation target to `ingestion_service/` instead of
`retrieval_service/document_handling/`.

- Add `ingestion_service/schemas/` with `SourceBlob`, `IngestedDocument`, `IngestedSection`, and `IngestedChunk`.
- Add typed errors for fetch, content detection, unsupported content, parse failure, source-too-large, and empty document.
- Add `DocumentHandlingPolicy`, `ResourceBudget`, and runtime capability detection.
- Add a `FileRouter` plus `DocumentHandler` protocol. Route by trusted content type, detected MIME type, file extension, source scheme, project policy, and available resources.
- Implement `TextDocumentHandler`, `MarkdownDocumentHandler`, and `HtmlDocumentHandler` first.
- Add a section-aware chunker with target size, max size, and overlap settings.
- Preserve useful metadata: title, canonical URL, heading, section path, page number, parser version, chunker version, content hash, source type, and filename.
- Keep `UniversalSourceIngester` as a compatibility path while adapters move to the standalone ingestion service.

### Phase 3: Add Low-Cost Native File Handlers

- Add optional `documents-lite` dependencies for PyMuPDF or `pypdf`, `python-docx`, `python-pptx`, and `openpyxl`.
- Benchmark PyMuPDF text extraction against `pypdf` under a 1 CPU / 1 GB limit and choose the faster/lower-memory default.
- Implement `PdfNativeTextHandler` for digital PDFs, with clear scanned/empty/garbled escalation signals.
- Implement `DocxNativeHandler`, `PptxNativeHandler`, and `SpreadsheetHandler`.
- Add table-aware chunking for CSV/XLSX instead of flattening tables into arbitrary paragraphs.
- Add parser fixtures under `tests/fixtures/documents/`.
- Add a generic file adapter for upload/object-storage backed documents.

### Phase 4: Split Ingestion Runtime From Retrieval Runtime

- Move ingest job status from `retrieval_service/ingest/jobs.py` into `ingestion_service/jobs/`.
- Move source loading from `retrieval_service/ingest/source.py` into `ingestion_service/source/`.
- Move chunking and handler selection out of project adapters.
- Define a stable `IngestionService.process()` API that returns `IngestedDocument` and `IngestedChunk` objects.
- Define a retrieval-facing indexing API that accepts ingestion outputs and performs embedding, sparse encoding, and Qdrant upsert.
- Keep a compatibility shim for the current `RagEngine.schedule_ingest()` path while migration happens.
- Add package-level tests for `ingestion_service` that run without Qdrant or embedding dependencies.

### Phase 5: Add Docling Sidecar Integration

- Add `DoclingDocumentHandler` behind the `docling_sidecar` resource tier.
- Prefer a sidecar process or external service with higher memory limits instead of importing Docling into the 1 CPU / 1 GB ingest worker.
- Disable OCR, VLM, ASR, and enrichment features by default.
- Add policy flags for `allow_docling`, `allow_docling_ocr`, `allow_docling_vlm`, max pages, max bytes, and timeout.
- Route scanned PDFs, image-only docs, complex layouts, formulas, and table-heavy documents to `needs_docling_conversion`.
- Store the route decision and Docling conversion metadata in job metadata so operators can explain why the sidecar was used.

### Phase 6: Operational Reliability

- Add retry policy for transient fetch, embedding, sparse encoding, and Qdrant failures.
- Add cancellation or superseding behavior for replaced documents.
- Add metrics for queued jobs, running jobs, completed jobs, failed jobs, source bytes, chunk count, embedding latency, sparse latency, and Qdrant upsert latency.
- Add engine-level semaphores for embedding, sparse encoding, and Qdrant write pressure.
- Add live integration tests against Qdrant for dense and hybrid ingest.
- Add migration/reingest guidance for dense-only collections moving to hybrid collections.

## Suggested Near-Term Milestone

Target a minimal safe ingestion core:

```text
project/user-scoped ingest
  + bounded queue
  + durable job status
  + explicit raw source handling
  + safe URL policy
  + idempotent document replacement
  + batched dense/sparse indexing
  + raw backup wired in app bootstrap
```

Do this before adding broad file-format support. The current document-handling design
is valuable, but the production risk is first in durability, source safety, and
replacement semantics.

## Validation Plan

- Run the focused ingestion and adapter tests:

```bash
python -m pytest tests/test_phase3_engine.py tests/test_phase5_ingestion.py tests/test_phase6_website_adapter.py -q
```

- Run sparse/hybrid ingest tests:

```bash
python -m pytest tests/test_sparse_retrieval.py -q
```

- Add new tests for:
  - durable job persistence across repository instances
  - bounded queue saturation
  - website domain rejection
  - local path rejection in server mode
  - raw bytes/object-storage ingest input
  - delete-before-replace or version-filter replacement behavior
  - batched embedding/upsert behavior
  - file router behavior, document handler selection, and section-aware chunking

## Open Questions

- Should local file ingestion be supported in production, or only in local/dev profiles?
- Should document replacement delete old chunks immediately, or keep multiple document versions and filter by active version?
- Should raw backups be mandatory for all production ingest, or optional per project?
- Should parser/chunker configuration live in project config, request metadata, or both with project-level limits?
- Should handler routing prefer declared content type, byte sniffing, or extension when they disagree?
