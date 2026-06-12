"""Compatibility shim for the project-service gRPC server."""

from project_service.server.grpc.server import (
    RagServiceServicer,
    serve_grpc,
    _search_result_to_proto,
)

__all__ = ["RagServiceServicer", "serve_grpc", "_search_result_to_proto"]
