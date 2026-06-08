"""Weather lookup service used by the Home dashboard.

The UI calls this only after an explicit user action. Tests inject ``fetch_json``
so the suite never depends on the network.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class WeatherLookupError(RuntimeError):
    """Raised when a weather lookup cannot produce a usable report."""


@dataclass(frozen=True)
class WeatherReport:
    city: str
    summary: str
    provider: str = "open-meteo"
    temperature_c: float | None = None
    condition: str = ""


FetchJson = Callable[[str, float], dict[str, Any]]


def _default_fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "DesktopCleaner/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise WeatherLookupError("weather API returned an invalid payload")
    return data


_WEATHER_CODE_LABELS = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "霜雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "雨",
    65: "大雨",
    71: "小雪",
    73: "雪",
    75: "大雪",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    95: "雷暴",
}


class OpenMeteoWeatherService:
    """Small Open-Meteo client for current weather by city name."""

    def __init__(
        self,
        *,
        fetch_json: FetchJson | None = None,
        timeout: float = 6.0,
    ) -> None:
        self._fetch_json = fetch_json or _default_fetch_json
        self._timeout = timeout

    def fetch_current(self, city: str) -> WeatherReport:
        city_name = str(city).strip()
        if not city_name:
            raise WeatherLookupError("city is required")

        location = self._lookup_location(city_name)
        latitude = location["latitude"]
        longitude = location["longitude"]
        forecast_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "timezone": "auto",
            }
        )
        forecast = self._fetch_json(forecast_url, self._timeout)
        current = forecast.get("current")
        if not isinstance(current, dict):
            raise WeatherLookupError("weather API returned no current conditions")

        temperature = self._number_or_none(current.get("temperature_2m"))
        weather_code = self._int_or_none(current.get("weather_code"))
        condition = (
            _WEATHER_CODE_LABELS.get(weather_code, f"Weather code {weather_code}")
            if weather_code is not None
            else "Weather"
        )
        summary = condition
        if temperature is not None:
            summary = f"{condition} · {temperature:g}°C"

        return WeatherReport(
            city=str(location["name"]),
            summary=summary,
            temperature_c=temperature,
            condition=condition,
        )

    def _lookup_location(self, city_name: str) -> dict[str, Any]:
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {
                "name": city_name,
                "count": 1,
                "language": "en",
                "format": "json",
            }
        )
        geocode = self._fetch_json(geocode_url, self._timeout)
        results = geocode.get("results")
        if not isinstance(results, list) or not results:
            raise WeatherLookupError(f"city not found: {city_name}")
        first = results[0]
        if not isinstance(first, dict):
            raise WeatherLookupError("weather API returned an invalid location")
        if "latitude" not in first or "longitude" not in first:
            raise WeatherLookupError("weather API returned a location without coordinates")
        return {
            "name": first.get("name") or city_name,
            "latitude": first["latitude"],
            "longitude": first["longitude"],
        }

    @staticmethod
    def _number_or_none(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None
