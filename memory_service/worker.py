"""Memory domain service process entrypoint.

Mirrors ``workflow_log_service/worker.py``: builds the composition root from
env settings and serves the broker consumers until stopped.
"""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass

from broker_service import BrokerSettings
from memory_service.config import MemoryServiceSettings
from memory_service.domain_app import (
    MemoryDomainServerContext,
    create_default_domain_app,
)
from memory_service.reconciliation import reconcile_pending_index
from shared.logging import configure_logging
from shared.runtime_health import RuntimeHealth


@dataclass(slots=True)
class MemoryWorkerContext:
    settings: MemoryServiceSettings
    domain_app: MemoryDomainServerContext

    async def shutdown(self) -> None:
        await self.domain_app.stop()

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=True,
            dependencies={
                "repository": True,
                "broker_consumer": getattr(self.domain_app, "consumer", None) is not None,
                "broker_identity_consumer": getattr(self.domain_app, "identity_consumer", None) is not None,
                "broker_retrieval_consumer": getattr(self.domain_app, "retrieval_consumer", None) is not None,
            },
            details={
                "db_path": str(self.settings.db_path),
                "command_topic": self.settings.command_topic,
                "identity_mode": self.settings.identity_mode,
                "index_mode": self.settings.index_mode,
                "search_mode": self.settings.search_mode,
            },
        )


async def create_worker_context(
    *,
    settings: MemoryServiceSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> MemoryWorkerContext:
    settings = settings or MemoryServiceSettings.from_values(dict(os.environ))
    domain_app = await create_default_domain_app(
        settings=settings,
        broker_settings=broker_settings,
    )
    return MemoryWorkerContext(settings=settings, domain_app=domain_app)


async def serve_forever() -> None:
    context = await create_worker_context()
    await context.domain_app.start_runtime()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Non-Unix platforms without signal-handler support: fall back to the
            # default (process termination). The finally below still runs when an
            # exception interrupts the loop.
            break
    try:
        # §9 re-drive seam: re-queue memory_records whose index hand-off was
        # never confirmed (indexed=0). Best-effort, log-only on failure.
        await reconcile_pending_index(
            repository=context.domain_app.handler._repository,
            indexer=context.domain_app.handler._indexer,
        )
        await stop.wait()
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, ValueError):
                pass
        await context.shutdown()


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
