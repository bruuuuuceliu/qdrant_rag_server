"""Manager gRPC compatibility server."""

from manager_service.server.grpc.server import ManagerRagServiceServicer, serve_grpc

__all__ = ["ManagerRagServiceServicer", "serve_grpc"]
