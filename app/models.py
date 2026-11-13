from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Place(Model):
    """차곡 장소. 좌표 없는 장소는 저장 가능하지만 NaviHelper 경로 요청에 사용할 수 없습니다."""
    id: Identifier
    name: Text
    time: str = Field(default="", max_length=100)
    duration: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=500)
    group: Literal["좋아요", "재생목록", "구독", "공유", ""] = ""
    reason: str = Field(default="", max_length=500)
    distance: str = Field(default="", max_length=100)
    lat: float | None = Field(default=None, ge=-90, le=90, description="위도. lng와 함께 제공; NaviHelper latitude에 대응합니다.")
    lng: float | None = Field(default=None, ge=-180, le=180, description="경도. lat와 함께 제공; NaviHelper longitude에 대응합니다.")
    open: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def coordinates(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be supplied together")
        return self


class TripDraft(Model):
    destination: Text
    departure: date
    endDate: date | Literal["미정"] = "미정"
    recordRoute: bool = Field(default=False, description="계획상의 선호값. 현재 서버는 true여도 위치 이력을 수집하지 않습니다.")
    companions: list[Text] = Field(max_length=10)
    interests: list[Text] = Field(max_length=3)
    mood: Text
    density: Text
    places: list[Place] = Field(default_factory=list, max_length=100, description="전체 여행 장소 목록. NaviHelper의 동시 활성 경유지(최대 2개)와 다릅니다.")

    @model_validator(mode="after")
    def dates_and_places(self):
        if isinstance(self.endDate, date) and self.endDate < self.departure:
            raise ValueError("endDate precedes departure")
        if len({p.id for p in self.places}) != len(self.places):
            raise ValueError("Place IDs must be unique")
        return self


class TripPlan(TripDraft):
    """차곡 CONTRACT.md v1 여행 메시지. 차량 앱이 Pleos SDK 입력으로 변환합니다."""
    v: Literal[1] = 1
    tripId: Identifier


class TripWrite(TripDraft):
    visibility: Literal["private", "link"] = "private"


class DriveEvent(Model):
    """차곡 사용자 행동 기록. WAYPOINT_APPROVED는 내비 실행 성공이나 방문 증명이 아닙니다."""
    v: Literal[1] = 1
    tripId: Identifier
    type: Literal["TRIP_STARTED", "PLACE_SAVED", "WAYPOINT_APPROVED", "WAYPOINT_DECLINED", "TRIP_FINISHED"]
    placeId: Identifier | None = None
    at: datetime

    @model_validator(mode="after")
    def event_fields(self):
        if self.at.tzinfo is None or self.at.utcoffset().total_seconds() != 0:
            raise ValueError("at must be a UTC timestamp")
        needs_place = self.type in {"PLACE_SAVED", "WAYPOINT_APPROVED", "WAYPOINT_DECLINED"}
        if needs_place != (self.placeId is not None):
            raise ValueError("placeId does not match event type")
        return self


class SpeakCommand(Model):
    """차곡 대사 메시지. 실제 재생 여부와 오디오 포커스는 차량 앱에서 결정합니다."""
    v: Literal[1] = 1
    tripId: Identifier
    text: str = Field(min_length=1, max_length=500)
    place: Place | None = None


class RadioResponse(Model):
    command: SpeakCommand
    messageId: Identifier = Field(description="큐에 저장된 envelope id. 직접 응답과 폴링 결과의 중복 재생 방지에 사용합니다.")


class Credentials(Model):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)
    password: str = Field(min_length=12, max_length=128)


class Device(Model):
    name: Text
    kind: Literal["phone", "pleos"]


class PairClaim(Device):
    code: str = Field(min_length=32, max_length=100)


class RecommendationRequest(Model):
    tripId: Identifier
    candidates: list[Place] = Field(min_length=1, max_length=30)


class RadioRequest(Model):
    place: Place
    facts: list[Text] = Field(min_length=1, max_length=10)


class ExtractionRequest(Model):
    text: str = Field(min_length=1, max_length=20000)
    source: str = Field(min_length=1, max_length=500)
    group: Literal["좋아요", "재생목록", "구독", "공유"] = "공유"
