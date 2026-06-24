"""Message bus composition helpers."""

from __future__ import annotations
from dataclasses import dataclass

from shared.contracts import MessageEnvelope


@dataclass(slots=True)
class BrokerMessageBus:
    """Small adapter over independently configured producer/consumer objects."""

    producer: object
    consumer: object | None = None
    consumer_topic: str = ""

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        publish = getattr(self.producer, "publish")
        await publish(topic, envelope, key=key)

    async def consume(self, topic: str) -> MessageEnvelope:
        if self.consumer is None:
            raise RuntimeError("broker message bus has no consumer")
        if self.consumer_topic and topic != self.consumer_topic:
            raise ValueError(f"broker message bus consumes only {self.consumer_topic}")
        consume = getattr(self.consumer, "consume")
        return await consume(topic)

    async def start(self) -> None:
        for component in (self.producer, self.consumer):
            start = getattr(component, "start", None)
            if start is not None:
                await start()

    async def stop(self) -> None:
        errors: list[Exception] = []
        for component in (self.consumer, self.producer):
            stop = getattr(component, "stop", None)
            if stop is not None:
                try:
                    await stop()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise ExceptionGroup("broker message bus stop failed", errors)
