import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from inspect import isawaitable
from typing import Any

from nanoscrypt.config.settings import settings
from nanoscrypt.core.events import AgentEvent, QueueUpdateEvent
from nanoscrypt.core.loop import run_agent_loop
from nanoscrypt.models.agent import Agent
from nanoscrypt.models.session import Session

EventListener = Callable[[AgentEvent], Awaitable[None] | None]


class SimpleCancellationToken:
    """Cancellation token for execution loop aborts."""

    def __init__(self) -> None:
        self.thread_event = threading.Event()

    def cancel(self) -> None:
        self.thread_event.set()

    def is_cancelled(self) -> bool:
        return self.thread_event.is_set()

    async def wait_cancelled(self) -> None:
        while not self.is_cancelled():
            await asyncio.sleep(0.05)


class AgentHarness:
    """Stateful agent harness matching the prompt queuing and event delegation pattern."""

    def __init__(
        self,
        orchestrator: Any,
        session: Session,
        agent: Agent | None = None,
        max_turns: int | None = None,
        session_store: Any = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.session = session
        self.agent = agent
        configured_turns = (
            settings.runtime.max_agent_turns if max_turns is None else max_turns
        )
        self.max_turns = max(1, configured_turns)
        self.session_store = session_store
        self.last_result = None
        self._listeners: list[EventListener] = []
        self._current_signal: SimpleCancellationToken | None = None
        self._running = False
        self._steering_queue: deque[dict[str, Any]] = deque()
        self._follow_up_queue: deque[dict[str, Any]] = deque()

    @property
    def is_running(self) -> bool:
        return self._running

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    async def _notify(self, event: AgentEvent) -> None:
        for listener in list(self._listeners):
            try:
                res = listener(event)
                if isawaitable(res):
                    await res
            except Exception:
                pass

    async def emit_event(self, event: AgentEvent) -> None:
        """Notify subscribers immediately for provider-streamed response events."""
        await self._notify(event)

    def cancel(self) -> None:
        if self._current_signal is not None:
            self._current_signal.cancel()

    def steer(self, content: str) -> QueueUpdateEvent:
        self._steering_queue.append({"role": "user", "content": content})
        return self.queue_update_event()

    def follow_up(self, content: str) -> QueueUpdateEvent:
        self._follow_up_queue.append({"role": "user", "content": content})
        return self.queue_update_event()

    def queue_update_event(self) -> QueueUpdateEvent:
        return QueueUpdateEvent(
            steering=tuple(m["content"] for m in self._steering_queue),
            follow_up=tuple(m["content"] for m in self._follow_up_queue),
        )

    def clear_queues(self) -> QueueUpdateEvent:
        self._steering_queue.clear()
        self._follow_up_queue.clear()
        return self.queue_update_event()

    def take_queued_input(self) -> str | None:
        """Consume pending steering/follow-up input as the next bounded turn."""
        parts = [item["content"] for item in self._steering_queue]
        self._steering_queue.clear()
        if self._follow_up_queue:
            parts.append(self._follow_up_queue.popleft()["content"])
        return "\n\n".join(parts) if parts else None

    def persist_session(self) -> None:
        if self.session_store is not None:
            self.session_store.save(self.session)

    async def prompt(self, content: str) -> AsyncIterator[AgentEvent]:
        """Appends user message and runs the generator loop."""
        if self._running:
            raise RuntimeError("Harness is already running.")
            
        self._running = True
        self._current_signal = SimpleCancellationToken()

        initial_steering = [item["content"] for item in self._steering_queue]
        self._steering_queue.clear()
        if initial_steering:
            content = (
                f"{content}\n\nAdditional instructions:\n"
                + "\n".join(initial_steering)
            )

        try:
            async for event in run_agent_loop(
                orchestrator=self.orchestrator,
                user_prompt=content,
                session=self.session,
                agent=self.agent,
                signal=self._current_signal,
                harness=self
            ):
                await self._notify(event)
                yield event
        finally:
            self._running = False
            self._current_signal = None
