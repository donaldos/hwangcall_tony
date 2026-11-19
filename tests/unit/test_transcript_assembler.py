from manura.adapters.stt.openai_realtime import TranscriptAssembler
from manura.domain.models import TranscriptEvent


def P(text: str) -> TranscriptEvent:
    return TranscriptEvent(kind="partial", text=text)


def F(text: str, start: int, end: int) -> TranscriptEvent:
    return TranscriptEvent(kind="final", text=text, start_ms=start, end_ms=end)


def test_delta_then_completed() -> None:
    asm = TranscriptAssembler()
    asm.committing(0, 1000)
    assert asm.delta("a", "안녕") == [P("안녕")]
    assert asm.delta("a", "하세요") == [P("안녕하세요")]
    asm.committed("a")
    assert not asm.idle
    assert asm.completed("a", " 안녕하세요 ") == [F("안녕하세요", 0, 1000), P("")]
    assert asm.idle


def test_out_of_order_completion_is_emitted_in_commit_order() -> None:
    asm = TranscriptAssembler()
    asm.committing(0, 1000)
    asm.committed("a")
    asm.committing(1000, 2000)
    asm.committed("b")
    asm.delta("a", "첫째")
    asm.delta("b", "둘째")
    assert asm.completed("b", "둘째") == []  # a가 아직이므로 보류
    assert asm.completed("a", "첫째") == [F("첫째", 0, 1000), F("둘째", 1000, 2000), P("")]
    assert asm.idle


def test_failed_item_is_skipped() -> None:
    asm = TranscriptAssembler()
    asm.committing(0, 500)
    asm.committed("a")
    asm.delta("a", "잡음")
    assert asm.failed("a") == [P("")]
    assert asm.idle


def test_empty_transcript_emits_no_final() -> None:
    asm = TranscriptAssembler()
    asm.committing(0, 500)
    asm.committed("a")
    assert asm.completed("a", "") == []
    assert asm.idle


def test_rejected_commit_does_not_block_idle() -> None:
    asm = TranscriptAssembler()
    asm.committing(0, 50)
    assert not asm.idle
    asm.commit_rejected()
    assert asm.idle


def test_late_events_after_finish_are_ignored() -> None:
    asm = TranscriptAssembler()
    asm.committing(0, 500)
    asm.committed("a")
    asm.completed("a", "끝")
    assert asm.delta("a", "늦은") == []
    assert asm.idle
