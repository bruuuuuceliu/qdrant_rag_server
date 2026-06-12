"""Reusable retrieval configuration parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RetrievalMode = Literal["dense", "bm25", "hybrid"]
FusionMethod = Literal["rrf", "weighted"]
NerProvider = Literal["disabled", "local", "llm"]


@dataclass(frozen=True, slots=True)
class ProjectBM25Settings:
    sparse_vector_name: str = "bm25"
    dense_vector_name: str = "dense"
    encoder_provider: str = "fastembed"
    encoder_model: str = "Qdrant/bm25"
    text_field: str = "text_lemmatized"
    lemmatize: bool = True
    index_version: str = "qdrant_bm25_v1"
    use_named_dense_vector: bool = False


@dataclass(frozen=True, slots=True)
class ProjectNerSettings:
    enabled: bool = False
    provider: NerProvider = "disabled"
    model: str = ""
    boost_entities: bool = False
    entity_boost: float = 0.0
    enrichment_version: str = "ner_none"


@dataclass(frozen=True, slots=True)
class ProjectRetrievalSettings:
    mode: RetrievalMode = "dense"
    top_k: int = 5
    candidate_count: int = 20
    fusion: FusionMethod = "rrf"
    dense_weight: float = 1.0
    bm25_weight: float = 1.0
    bm25: ProjectBM25Settings = field(default_factory=ProjectBM25Settings)
    ner: ProjectNerSettings = field(default_factory=ProjectNerSettings)

    @property
    def dense_enabled(self) -> bool:
        return self.mode in {"dense", "hybrid"}

    @property
    def bm25_enabled(self) -> bool:
        return self.mode in {"bm25", "hybrid"}


def parse_retrieval_settings(
    raw: dict[str, Any] | None,
    *,
    default_top_k: int = 5,
    default_candidate_count: int = 20,
) -> ProjectRetrievalSettings:
    raw = dict(raw or {})
    mode = _literal(
        raw.get("mode", "dense"),
        allowed={"dense", "bm25", "hybrid"},
        name="retrieval_config.mode",
    )
    fusion = _literal(
        raw.get("fusion", "rrf"),
        allowed={"rrf", "weighted"},
        name="retrieval_config.fusion",
    )
    top_k = _int(raw.get("top_k", default_top_k), "retrieval_config.top_k")
    candidate_count = _int(
        raw.get("candidate_count", default_candidate_count),
        "retrieval_config.candidate_count",
    )
    dense_weight = _float(
        raw.get("dense_weight", 0.7),
        "retrieval_config.dense_weight",
    )
    bm25_weight = _float(
        raw.get("bm25_weight", 0.3),
        "retrieval_config.bm25_weight",
    )

    if top_k <= 0:
        raise ValueError("retrieval_config.top_k must be positive")
    if candidate_count < top_k:
        raise ValueError("retrieval_config.candidate_count must be at least top_k")
    if dense_weight < 0:
        raise ValueError("retrieval_config.dense_weight must be non-negative")
    if bm25_weight < 0:
        raise ValueError("retrieval_config.bm25_weight must be non-negative")

    bm25 = _parse_bm25_settings(
        raw.get("bm25"),
        use_named_dense_vector=mode in {"bm25", "hybrid"} or "bm25" in raw,
    )
    ner = _parse_ner_settings(raw.get("ner"))

    return ProjectRetrievalSettings(
        mode=mode,  # type: ignore[arg-type]
        top_k=top_k,
        candidate_count=candidate_count,
        fusion=fusion,  # type: ignore[arg-type]
        dense_weight=dense_weight,
        bm25_weight=bm25_weight,
        bm25=bm25,
        ner=ner,
    )


def _parse_bm25_settings(
    raw: Any,
    *,
    use_named_dense_vector: bool,
) -> ProjectBM25Settings:
    data = dict(raw or {}) if isinstance(raw, dict) else {}
    sparse_vector_name = str(data.get("sparse_vector_name", "bm25")).strip()
    dense_vector_name = str(data.get("dense_vector_name", "dense")).strip()
    encoder_provider = str(data.get("encoder_provider", "fastembed")).strip().lower()
    encoder_model = str(data.get("encoder_model", "Qdrant/bm25")).strip()
    text_field = str(data.get("text_field", "text_lemmatized")).strip()
    if not sparse_vector_name:
        raise ValueError("retrieval_config.bm25.sparse_vector_name is required")
    if not dense_vector_name:
        raise ValueError("retrieval_config.bm25.dense_vector_name is required")
    if encoder_provider != "fastembed":
        raise ValueError("retrieval_config.bm25.encoder_provider must be 'fastembed'")
    if not encoder_model:
        raise ValueError("retrieval_config.bm25.encoder_model is required")
    if not text_field:
        raise ValueError("retrieval_config.bm25.text_field is required")
    return ProjectBM25Settings(
        sparse_vector_name=sparse_vector_name,
        dense_vector_name=dense_vector_name,
        encoder_provider=encoder_provider,
        encoder_model=encoder_model,
        text_field=text_field,
        lemmatize=_bool(data.get("lemmatize", True)),
        index_version=str(data.get("index_version", "qdrant_bm25_v1")),
        use_named_dense_vector=use_named_dense_vector,
    )


def _parse_ner_settings(raw: Any) -> ProjectNerSettings:
    data = dict(raw or {}) if isinstance(raw, dict) else {}
    enabled = _bool(data.get("enabled", False))
    provider_default = "local" if enabled else "disabled"
    provider = _literal(
        data.get("provider", provider_default),
        allowed={"disabled", "local", "llm"},
        name="retrieval_config.ner.provider",
    )
    if not enabled:
        provider = "disabled"
    model = str(data.get("model", ""))
    boost_entities = _bool(data.get("boost_entities", False))
    entity_boost = _float(
        data.get("entity_boost", 0.0),
        "retrieval_config.ner.entity_boost",
    )
    if entity_boost < 0:
        raise ValueError("retrieval_config.ner.entity_boost must be non-negative")
    if enabled and provider == "local" and not model:
        model = "en_core_web_sm"
    enrichment_version = str(
        data.get(
            "enrichment_version",
            f"ner_{provider}_{model}" if enabled else "ner_none",
        )
    )
    return ProjectNerSettings(
        enabled=enabled,
        provider=provider,  # type: ignore[arg-type]
        model=model,
        boost_entities=boost_entities,
        entity_boost=entity_boost,
        enrichment_version=enrichment_version,
    )


def _literal(value: Any, *, allowed: set[str], name: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return normalized


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return bool(value)

