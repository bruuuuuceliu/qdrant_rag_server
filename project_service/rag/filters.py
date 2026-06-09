"""Vector-store filter helpers for RAG retrieval."""

from __future__ import annotations

from project_service.schemas import ProjectRetrievalFilter
from retrieval_service.services.vector_store import models as qdrant_models


def _build_qdrant_filter(
    retrieval_filter: ProjectRetrievalFilter,
) -> qdrant_models.Filter:
    must: list[qdrant_models.Condition] = []

    must.append(
        qdrant_models.FieldCondition(
            key="project_id",
            match=qdrant_models.MatchValue(value=retrieval_filter.project_id),
        )
    )

    user_ids = retrieval_filter.allowed_user_ids
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

    if retrieval_filter.kb_ids:
        if len(retrieval_filter.kb_ids) == 1:
            must.append(
                qdrant_models.FieldCondition(
                    key="kb_id",
                    match=qdrant_models.MatchValue(value=retrieval_filter.kb_ids[0]),
                )
            )
        else:
            must.append(
                qdrant_models.FieldCondition(
                    key="kb_id",
                    match=qdrant_models.MatchAny(any=list(retrieval_filter.kb_ids)),
                )
            )

    if retrieval_filter.doc_ids:
        if len(retrieval_filter.doc_ids) == 1:
            must.append(
                qdrant_models.FieldCondition(
                    key="doc_id",
                    match=qdrant_models.MatchValue(value=retrieval_filter.doc_ids[0]),
                )
            )
        else:
            must.append(
                qdrant_models.FieldCondition(
                    key="doc_id",
                    match=qdrant_models.MatchAny(any=list(retrieval_filter.doc_ids)),
                )
            )

    return qdrant_models.Filter(must=must)
