"""
PARIKA API - Weather Schemas

Wire-format Pydantic schemas for the direct Weather API endpoint.
"""

from __future__ import annotations

from pydantic import Field

from .common import ApiModel


class WeatherLocation(ApiModel):
    name: str
    latitude: float
    longitude: float
    timezone: str


class WeatherCurrent(ApiModel):
    temperature_c: float | None = None
    feels_like_c: float | None = None
    condition: str | None = None
    weather_code: int | None = None
    icon: str | None = None
    is_day: bool
    humidity_percent: int | None = None
    precipitation_mm: float | None = None
    rain_mm: float | None = None
    showers_mm: float | None = None
    snowfall_mm: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_degrees: int | None = None
    wind_gusts_kmh: float | None = None
    cloud_cover_percent: int | None = None
    pressure_hpa: float | None = None
    visibility_m: float | None = None
    observed_at: str | None = None


class WeatherForecastDay(ApiModel):
    date: str
    condition: str | None = None
    weather_code: int | None = None
    icon: str | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    feels_like_max_c: float | None = None
    feels_like_min_c: float | None = None
    precipitation_probability_percent: int | None = None
    precipitation_sum_mm: float | None = None
    sunrise: str | None = None
    sunset: str | None = None


class WeatherMetadata(ApiModel):
    fetched_at: str
    cached_at: str
    cache_expires_at: str
    cache_status: str = Field(pattern="^(fresh|fetched)$")
    cache_ttl_seconds: int


class WeatherResponse(ApiModel):
    location: WeatherLocation
    current: WeatherCurrent
    forecast: list[WeatherForecastDay]
    metadata: WeatherMetadata


class WeatherErrorResponse(ApiModel):
    error: dict[str, str]