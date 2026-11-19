class DomainError(Exception):
    """도메인 계층 예외의 기반."""


class STTError(DomainError):
    """STT 엔진 연결·인식 실패. 외부 SDK 예외는 어댑터에서 이것으로 바꿔 올린다."""


class LLMError(DomainError):
    """LLM 호출 실패. 외부 SDK 예외는 어댑터에서 이것으로 바꿔 올린다."""


class TurnNotFoundError(DomainError):
    """없는(또는 만료된) 녹음 구간."""


class EmptyTranscriptError(DomainError):
    """확정된 전사문이 없어 답변을 만들 수 없다."""


class AdviceInProgressError(DomainError):
    """같은 녹음 구간에 대해 답변 생성이 이미 진행 중이다."""
