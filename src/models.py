"""資料模型"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Location(str, Enum):
    TAIWAN = "臺灣"
    WORLD = "世界"


class Confidence(str, Enum):
    HIGH = "🟢 高"
    MEDIUM = "🟡 中"
    LOW = "🔴 低"


class SourceLayer(str, Enum):
    TWTC = "台北世貿"
    NANGANG = "南港"
    WHITELIST = "白名單"
    AI_DISCOVERY = "AI發現"


class Status(str, Enum):
    PENDING = "待確認"
    CONFIRMED = "已確認"
    EXPIRED = "已過期"


@dataclass
class Exhibition:
    name: str
    start_date: date | None = None
    end_date: date | None = None
    location: Location = Location.WORLD
    organizer: str = ""
    url: str = ""
    confidence: Confidence = Confidence.MEDIUM
    source: SourceLayer = SourceLayer.WHITELIST
    industries: list[str] = field(default_factory=list)
    related_stocks: str = ""
    status: Status = Status.PENDING

    @property
    def unique_key(self) -> str:
        year = self.start_date.year if self.start_date else "????"
        return f"{self.name} {year}"

    @property
    def has_precise_date(self) -> bool:
        return self.start_date is not None and self.end_date is not None
