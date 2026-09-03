from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SMSResult:
    success: bool
    provider_sid: str | None = None
    error: str | None = None
    segments: int = 1
    cost_estimate: float | None = None

class BaseSMSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, to: str, body: str) -> SMSResult:
        raise NotImplementedError
