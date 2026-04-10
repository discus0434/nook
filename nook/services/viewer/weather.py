from __future__ import annotations

import requests

WEATHER_ICONS = {
    "100": "☀️",
    "101": "🌤️",
    "200": "☁️",
    "201": "⛅",
    "202": "🌧️",
    "300": "🌧️",
    "301": "🌦️",
    "400": "🌨️",
}


def get_weather_data() -> dict[str, str]:
    try:
        response = requests.get(
            "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        tokyo = next(
            (
                area
                for area in data[0]["timeSeries"][2]["areas"]
                if area["area"]["name"] == "東京"
            ),
            None,
        )
        tokyo_weather = next(
            (
                area
                for area in data[0]["timeSeries"][0]["areas"]
                if area["area"]["code"] == "130010"
            ),
            None,
        )
        if tokyo and tokyo_weather:
            temps = tokyo["temps"]
            weather_code = tokyo_weather["weatherCodes"][0]
            return {
                "temp": temps[0],
                "weather_code": weather_code,
                "weather_icon": WEATHER_ICONS.get(weather_code, ""),
            }
    except Exception:
        return {
            "temp": "--",
            "weather_code": "100",
            "weather_icon": WEATHER_ICONS.get("100", "☀️"),
        }

    return {
        "temp": "--",
        "weather_code": "100",
        "weather_icon": WEATHER_ICONS.get("100", "☀️"),
    }
