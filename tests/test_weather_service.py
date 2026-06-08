from __future__ import annotations

import unittest

from desktop_tidy.services.weather import OpenMeteoWeatherService, WeatherLookupError


class WeatherServiceTests(unittest.TestCase):
    def test_open_meteo_fetches_geocoding_and_current_weather(self) -> None:
        calls: list[str] = []

        def fake_fetch(url: str, timeout: float) -> dict[str, object]:
            calls.append(url)
            if "geocoding-api.open-meteo.com" in url:
                return {
                    "results": [
                        {
                            "name": "London",
                            "country": "United Kingdom",
                            "latitude": 51.5,
                            "longitude": -0.12,
                        }
                    ]
                }
            if "api.open-meteo.com" in url:
                return {
                    "current": {
                        "temperature_2m": 18.4,
                        "weather_code": 3,
                    }
                }
            raise AssertionError(f"unexpected URL {url}")

        service = OpenMeteoWeatherService(fetch_json=fake_fetch)

        report = service.fetch_current("London")

        self.assertEqual(report.city, "London")
        self.assertEqual(report.temperature_c, 18.4)
        self.assertEqual(report.summary, "阴 · 18.4°C")
        self.assertEqual(report.provider, "open-meteo")
        self.assertEqual(len(calls), 2)
        self.assertIn("London", calls[0])
        self.assertIn("latitude=51.5", calls[1])
        self.assertIn("longitude=-0.12", calls[1])

    def test_open_meteo_reports_missing_city(self) -> None:
        def fake_fetch(_url: str, _timeout: float) -> dict[str, object]:
            return {"results": []}

        service = OpenMeteoWeatherService(fetch_json=fake_fetch)

        with self.assertRaises(WeatherLookupError):
            service.fetch_current("Missing City")


if __name__ == "__main__":
    unittest.main()
