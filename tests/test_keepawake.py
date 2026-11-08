"""Unit tests for reference-counted KeepAwake."""
from agents_dialpad.keepawake import KeepAwake


class FakeBackend:
    def __init__(self):
        self.calls: list[str] = []

    def on(self) -> None:
        self.calls.append("on")

    def off(self) -> None:
        self.calls.append("off")


def test_turns_on_once_and_off_after_last_release():
    backend = FakeBackend()
    ka = KeepAwake(enabled=True, backend=backend)
    ka.acquire()
    ka.acquire()
    ka.release()
    assert backend.calls == ["on"]
    ka.release()
    assert backend.calls == ["on", "off"]


def test_extra_release_is_harmless():
    backend = FakeBackend()
    ka = KeepAwake(enabled=True, backend=backend)
    ka.release()
    assert ka.count == 0
    assert backend.calls == []


def test_disabled_never_calls_the_backend():
    backend = FakeBackend()
    ka = KeepAwake(enabled=False, backend=backend)
    ka.acquire()
    ka.release()
    assert backend.calls == []


def test_backend_errors_do_not_raise():
    class FailingBackend:
        def on(self) -> None:
            raise RuntimeError("boom")

        def off(self) -> None:
            raise RuntimeError("boom")

    ka = KeepAwake(enabled=True, backend=FailingBackend())
    ka.acquire()
    assert ka.count == 1
    ka.release()
    assert ka.count == 0
