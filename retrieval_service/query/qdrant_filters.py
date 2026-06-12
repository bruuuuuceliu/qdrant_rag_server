"""Qdrant filter rendering for retrieval queries."""

from __future__ import annotations

from typing import Any

from retrieval_service.services.vector_store import models as qdrant_models


def _build_qdrant_filter(retrieval_filter: Any) -> qdrant_models.Filter:
    must: list[qdrant_models.Condition] = []

    must.append(
        qdrant_models.FieldCondition(
            key="project_id",
            match=qdrant_models.MatchValue(value=retrieval_filter.project_id),
        )
    )

    user_ids = tuple(retrieval_filter.allowed_user_ids)
    if len(user_ids) == 1:
        must.append(
            qdrant_models.FieldCondition(
                key="user_id",
                match=qdrant_models.MatchValue(value=user_ids[0]),
            )
        )
    else:
        must.append(
            qdrant_models.FieldCondition(
                key="user_id",
                match=qdrant_models.MatchAny(any=list(user_ids)),
            )
        )

    kb_ids = tuple(getattr(retrieval_filter, "kb_ids", ()))
    if kb_ids:
        if len(kb_ids) == 1:
            must.append(
                qdrant_models.FieldCondition(
                    key="kb_id",
                    match=qdrant_models.MatchValue(value=kb_ids[0]),
                )
            )
        else:
            must.append(
                qdrant_models.FieldCondition(
                    key="kb_id",
                    match=qdrant_models.MatchAny(any=list(kb_ids)),
                )
            )

    doc_ids = tuple(getattr(retrieval_filter, "doc_ids", ()))
    if doc_ids:
        if len(doc_ids) == 1:
            must.append(
                qdrant_models.FieldCondition(
                    key="doc_id",
                    match=qdrant_models.MatchValue(value=doc_ids[0]),
                )
            )
        else:
            must.append(
                qdrant_models.FieldCondition(
                    key="doc_id",
                    match=qdrant_models.MatchAny(any=list(doc_ids)),
                )
            )

    return qdrant_models.Filter(must=must)

