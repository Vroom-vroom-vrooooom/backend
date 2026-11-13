from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Place(Model):
    id: Identifier
    name: Text
    time: str = Field(default="", max_length=100)
    duration: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=500)
    group: Literal["좋아요", "재생목록", "구독", "공유", ""] = ""
    reason: str = Field(default="", max_length=500)
    distance: str = Field(default="", max_length=100)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
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
    recordRoute: bool = False
    companions: list[Text] = Field(max_length=10)
    interests: list[Text] = Field(max_length=3)
    mood: Text
    density: Text
    places: list[Place] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def dates_and_places(self):
        if isinstance(self.endDate, date) and self.endDate < self.departure:
            raise ValueError("endDate precedes departure")
        if len({p.id for p in self.places}) != len(self.places):
            raise ValueError("Place IDs must be unique")
        return self


class TripPlan(TripDraft):
    v: Literal[1] = 1
    tripId: Identifier


class TripWrite(TripDraft):
    visibility: Literal["private", "link"] = "private"


class DriveEvent(Model):
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
    v: Literal[1] = 1
    tripId: Identifier
    text: str = Field(min_length=1, max_length=500)
    place: Place | None = None


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
