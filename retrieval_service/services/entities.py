"""Entity extraction primitives for retrieval enrichment."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EntityMention:
    text: str
    label: str
    canonical: str
    start: int
    end: int
    confidence: float | None = None
    source: str = "local"

    @property
    def key(self) -> str:
        return f"{self.label}:{self.canonical}"


class NerExtractor(Protocol):
    async def extract(self, text: str) -> list[EntityMention]:
        ...

    async def extract_batch(self, texts: list[str]) -> list[list[EntityMention]]:
        ...


class NoopNerExtractor:
    async def extract(self, text: str) -> list[EntityMention]:
        return []

    async def extract_batch(self, texts: list[str]) -> list[list[EntityMention]]:
        return [[] for _ in texts]


class LocalNerExtractor:
    """Local spaCy-backed NER extractor.

    spaCy remains optional; this class imports it only during initialization.
    """

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        self._model_name = model_name
        self._nlp: Any = None

    async def initialize(self) -> None:
        self._nlp = await asyncio.to_thread(self._load_model)

    async def extract(self, text: str) -> list[EntityMention]:
        if self._nlp is None:
            await self.initialize()
        return await asyncio.to_thread(self._extract_sync, text)

    async def extract_batch(self, texts: list[str]) -> list[list[EntityMention]]:
        if self._nlp is None:
            await self.initialize()
        return await asyncio.to_thread(self._extract_batch_sync, texts)

    def _load_model(self) -> Any:
        try:
            import spacy
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "spacy is required for local NER. Install the ner optional "
                "dependencies and the configured spaCy model."
            ) from exc
        try:
            return spacy.load(self._model_name)
        except OSError as exc:
            raise RuntimeError(
                f"spaCy model {self._model_name!r} is not installed"
            ) from exc

    def _extract_sync(self, text: str) -> list[EntityMention]:
        doc = self._nlp(text)
        return [
            EntityMention(
                text=ent.text,
                label=ent.label_,
                canonical=normalize_entity_text(ent.text),
                start=int(ent.start_char),
                end=int(ent.end_char),
                confidence=None,
                source="local",
            )
            for ent in doc.ents
        ]

    def _extract_batch_sync(self, texts: list[str]) -> list[list[EntityMention]]:
        docs = self._nlp.pipe(texts)
        result: list[list[EntityMention]] = []
        for doc in docs:
            result.append(
                [
                    EntityMention(
                        text=ent.text,
                        label=ent.label_,
                        canonical=normalize_entity_text(ent.text),
                        start=int(ent.start_char),
                        end=int(ent.end_char),
                        confidence=None,
                        source="local",
                    )
                    for ent in doc.ents
                ]
            )
        return result


def normalize_entity_text(text: str) -> str:
    return " ".join(text.casefold().split())


def entities_to_metadata(entities: list[EntityMention]) -> dict[str, Any]:
    return {
        "entities": [asdict(entity) for entity in entities],
        "entity_keys": sorted({entity.key for entity in entities}),
    }


def metadata_to_entities(metadata: dict[str, Any]) -> list[EntityMention]:
    raw_entities = metadata.get("entities", [])
    if not isinstance(raw_entities, list):
        return []
    entities: list[EntityMention] = []
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        try:
            entities.append(
                EntityMention(
                    text=str(raw["text"]),
                    label=str(raw["label"]),
                    canonical=str(raw["canonical"]),
                    start=int(raw["start"]),
                    end=int(raw["end"]),
                    confidence=(
                        None
                        if raw.get("confidence") is None
                        else float(raw["confidence"])
                    ),
                    source=str(raw.get("source", "local")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return entities
