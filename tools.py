"""
tools.py -- the "hands" of the agent.

Every function with @tool is something the LLM can ask us to run.
The LLM never runs code itself. It only reads each tool's NAME, DOCSTRING and
ARGUMENT TYPES, then decides which tool to call and with what arguments.
That is why the docstrings are written for the LLM, not only for humans.

Rules every tool follows:
  1. Returns a JSON string (easy for the LLM to read).
  2. Never crashes. On any problem it returns {"error": "..."} instead,
     so the LLM can explain the problem to the user.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from langchain_core.tools import tool

# A small timeout so the agent never hangs forever if an API is slow.
TIMEOUT = 10
HEADERS = {"User-Agent": "TravelBuddyAgent/1.0 (university assignment)"}

# Where save_trip_plan writes files.
PLANS_DIR = Path("saved_plans")


def _ok(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _get_json(url: str, params: dict | None = None):
    """Small helper: GET a URL and return parsed JSON. May raise requests errors."""
    response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


# --------------------------------------------------------------------------
# Tool 1: weather (API: Open-Meteo, no key needed)
# --------------------------------------------------------------------------

# Open-Meteo returns a numeric "weather code". We translate it to words.
WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}
BAD_OUTDOOR_CODES = {65, 66, 67, 75, 82, 86, 95, 96, 99}


@tool
def get_weather_forecast(city: str, days: int = 3) -> str:
    """Get the real weather forecast for a city for the next 1-7 days.

    Use this whenever the user asks about weather, rain, temperature, or whether
    an outdoor activity (hiking, walking tour, beach) is a good idea.
    Returns for each day: the weekday and date, min/max temperature in Celsius, rain in mm,
    rain probability in %, a text description, and an 'outdoor_friendly' flag.

    Args:
        city: The DESTINATION city the user is asking about, in English, for example
            "Almaty" or "Istanbul". If the user says "there", use the last city they
            talked about in this conversation, NOT their home city.
        days: How many days to forecast, from 1 to 7. Default is 3.
    """
    try:
        days = max(1, min(int(days), 7))

        # Step 1: city name -> latitude/longitude (geocoding API).
        geo = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": city, "count": 1, "language": "en"},
        )
        if not geo.get("results"):
            return _err(f"City '{city}' was not found. Ask the user to check the spelling.")
        place = geo["results"][0]

        # Step 2: coordinates -> forecast.
        forecast = _get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_sum,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": days,
            },
        )
        daily = forecast["daily"]

        result_days = []
        for i, date in enumerate(daily["time"]):
            code = daily["weather_code"][i]
            rain_mm = daily["precipitation_sum"][i] or 0
            rain_prob = daily["precipitation_probability_max"][i] or 0
            outdoor_friendly = rain_mm < 2 and rain_prob < 50 and code not in BAD_OUTDOOR_CODES
            result_days.append({
                "weekday": datetime.strptime(date, "%Y-%m-%d").strftime("%A"),
                "date": date,
                "description": WEATHER_CODES.get(code, "unknown"),
                "temp_min_c": daily["temperature_2m_min"][i],
                "temp_max_c": daily["temperature_2m_max"][i],
                "rain_mm": rain_mm,
                "rain_probability_percent": rain_prob,
                "outdoor_friendly": outdoor_friendly,
            })

        return _ok({
            "city": place["name"],
            "country": place.get("country", ""),
            "forecast": result_days,
        })
    except requests.RequestException as exc:
        return _err(f"Weather service is not available right now ({type(exc).__name__}).")
    except (KeyError, ValueError, TypeError) as exc:
        return _err(f"Could not read the weather data ({type(exc).__name__}).")


# --------------------------------------------------------------------------
# Tool 2: currency (API: Frankfurter, with a fallback API)
# --------------------------------------------------------------------------

@tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert money between currencies using live exchange rates.

    Use this for any question about prices in another currency, for example
    "how much is 200 EUR in KZT". Never guess exchange rates yourself.

    Args:
        amount: The amount of money to convert, for example 200.
        from_currency: 3-letter code of the source currency, for example "EUR".
        to_currency: 3-letter code of the target currency, for example "KZT".
    """
    try:
        amount = float(amount)
        src = from_currency.strip().upper()
        dst = to_currency.strip().upper()
        if not (re.fullmatch(r"[A-Z]{3}", src) and re.fullmatch(r"[A-Z]{3}", dst)):
            return _err("Currency codes must be 3 letters, like USD, EUR, KZT.")
        if src == dst:
            return _ok({"amount": amount, "from": src, "to": dst, "rate": 1.0, "result": amount})

        # Main source: Frankfurter (European Central Bank rates).
        # It does not support every currency (for example KZT), so we have a backup.
        try:
            data = _get_json("https://api.frankfurter.dev/v1/latest", {"base": src, "symbols": dst})
            rate = data["rates"][dst]
            source, date = "Frankfurter (ECB)", data.get("date", "")
        except (requests.RequestException, KeyError, ValueError):
            data = _get_json(f"https://open.er-api.com/v6/latest/{src}")
            if data.get("result") != "success" or dst not in data.get("rates", {}):
                return _err(f"No exchange rate found for {src} -> {dst}.")
            rate = data["rates"][dst]
            source, date = "open.er-api.com", data.get("time_last_update_utc", "")

        return _ok({
            "amount": amount, "from": src, "to": dst,
            "rate": rate, "result": round(amount * rate, 2),
            "source": source, "date": date,
        })
    except (ValueError, TypeError):
        return _err("The amount must be a number.")
    except requests.RequestException as exc:
        return _err(f"Currency service is not available right now ({type(exc).__name__}).")


# --------------------------------------------------------------------------
# Tool 3: country info (API: ApiCountries, no key needed)
# The old REST Countries v3.1 API was shut down, so we use ApiCountries.
# --------------------------------------------------------------------------

@tool
def get_country_info(country: str) -> str:
    """Get basic facts about a country: capital, languages, currency, time zones, population.

    Use this when the user plans a trip to a country and needs practical basics,
    or when you need the local currency code before converting money.

    Args:
        country: Country name in English, for example "Turkey" or "Japan".
    """
    country = (country or "").strip()
    if not country:
        return _err("Please give a country name.")
    try:
        data = _get_json(f"https://www.apicountries.com/name/{quote(country)}")
        if not isinstance(data, list) or not data:
            return _err(f"Country '{country}' was not found.")
        # The API can return several partial matches. Prefer the exact name.
        c = next(
            (item for item in data if str(item.get("name", "")).lower() == country.lower()),
            data[0],
        )
        capital = c.get("capital") or "unknown"
        if isinstance(capital, list):
            capital = capital[0] if capital else "unknown"
        currencies = {
            cur.get("code", "?"): cur.get("name", "") for cur in (c.get("currencies") or [])
        }
        return _ok({
            "name": c["name"],
            "capital": capital,
            "region": c.get("region", ""),
            "languages": [lang.get("name", "") for lang in (c.get("languages") or [])],
            "currencies": currencies,
            "timezones": c.get("timezones", []),
            "population": c.get("population"),
        })
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return _err(f"Country '{country}' was not found.")
        return _err("Country service returned an error.")
    except requests.RequestException as exc:
        return _err(f"Country service is not available right now ({type(exc).__name__}).")
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        return _err(f"Could not read the country data ({type(exc).__name__}).")


# --------------------------------------------------------------------------
# Tool 4: Wikipedia summary (API: Wikipedia REST, no key needed)
# --------------------------------------------------------------------------

@tool
def get_place_summary(topic: str) -> str:
    """Get a short Wikipedia summary about a city, landmark, national park or other place.

    Use this when the user wants to know what a place is, what it is famous for,
    or you need background facts to suggest things to do.

    Args:
        topic: The Wikipedia page title, for example "Big Almaty Lake" or "Cappadocia".
    """
    try:
        title = quote(topic.strip().replace(" ", "_"), safe="")
        data = _get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
        if data.get("type") == "disambiguation":
            return _err(f"'{topic}' is ambiguous. Ask the user which one they mean, or use a more specific name.")
        return _ok({
            "title": data.get("title", topic),
            "summary": data.get("extract", ""),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        })
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return _err(f"No Wikipedia page found for '{topic}'. Try another name.")
        return _err("Wikipedia returned an error.")
    except requests.RequestException as exc:
        return _err(f"Wikipedia is not available right now ({type(exc).__name__}).")


# --------------------------------------------------------------------------
# Tool 5: packing advice (our own logic, no API)
# --------------------------------------------------------------------------

@tool
def get_packing_list(temp_min_c: float, temp_max_c: float, rain_mm: float, activity: str = "city") -> str:
    """Build a packing list from weather numbers and the planned activity.

    Use this AFTER you have the weather forecast. Pass the lowest temperature,
    the highest temperature and the total rain of the trip.

    Args:
        temp_min_c: Lowest temperature of the trip in Celsius.
        temp_max_c: Highest temperature of the trip in Celsius.
        rain_mm: Total expected rain in millimeters (0 if dry).
        activity: One of "city", "hiking", "beach", "business". Default "city".
    """
    try:
        t_min, t_max, rain = float(temp_min_c), float(temp_max_c), float(rain_mm)
        activity = (activity or "city").strip().lower()
        if t_min > t_max:
            t_min, t_max = t_max, t_min

        items = ["passport / ID", "phone charger", "power bank"]

        if t_min < 0:
            items += ["warm winter jacket", "hat, gloves and scarf", "thermal underwear"]
        elif t_min < 10:
            items += ["warm jacket", "sweater", "long pants"]
        elif t_min < 18:
            items += ["light jacket", "long sleeves"]
        if t_max >= 25:
            items += ["t-shirts", "sunglasses", "sunscreen"]
        if t_max >= 32:
            items += ["water bottle", "hat for the sun"]
        if rain >= 2:
            items += ["raincoat or umbrella", "waterproof shoes"]

        if activity == "hiking":
            items += ["hiking boots", "backpack", "first-aid kit", "snacks and water"]
            if rain >= 2:
                items += ["waterproof jacket (important on trails)"]
        elif activity == "beach":
            items += ["swimsuit", "beach towel", "flip-flops"]
        elif activity == "business":
            items += ["formal clothes", "laptop and charger"]
        else:
            items += ["comfortable walking shoes"]

        unique_items = list(dict.fromkeys(items))  # remove duplicates, keep order
        return _ok({"activity": activity, "packing_list": unique_items})
    except (ValueError, TypeError):
        return _err("Temperatures and rain must be numbers.")


# --------------------------------------------------------------------------
# Tool 6: budget calculator (our own logic: exact math the LLM is bad at)
# --------------------------------------------------------------------------

@tool
def calculate_trip_budget(
    days: int,
    hotel_per_night: float,
    food_per_day: float,
    transport_per_day: float,
    activities_total: float = 0.0,
    buffer_percent: float = 10.0,
) -> str:
    """Calculate the total cost of a trip with exact math.

    Use this whenever the user asks how much a trip will cost. All money
    values must be in ONE currency (convert first with convert_currency
    if needed). LLMs make arithmetic mistakes, so always use this tool.

    Args:
        days: Number of days of the trip (nights = days - 1, at least 1 night).
        hotel_per_night: Hotel price per night.
        food_per_day: Food cost per day.
        transport_per_day: Local transport cost per day.
        activities_total: Total cost of tickets and activities for the whole trip.
        buffer_percent: Extra safety money in percent. Default 10.
    """
    try:
        days = int(days)
        if days < 1:
            return _err("Days must be at least 1.")
        nights = max(days - 1, 1)
        hotel = nights * float(hotel_per_night)
        food = days * float(food_per_day)
        transport = days * float(transport_per_day)
        activities = float(activities_total)
        subtotal = hotel + food + transport + activities
        buffer = subtotal * float(buffer_percent) / 100
        return _ok({
            "days": days, "nights": nights,
            "hotel": round(hotel, 2), "food": round(food, 2),
            "transport": round(transport, 2), "activities": round(activities, 2),
            "subtotal": round(subtotal, 2),
            "buffer": round(buffer, 2),
            "total": round(subtotal + buffer, 2),
        })
    except (ValueError, TypeError):
        return _err("All money values and days must be numbers.")


# --------------------------------------------------------------------------
# Tool 7: save a plan to a file (our own logic: files)
# --------------------------------------------------------------------------

@tool
def save_trip_plan(filename: str, content: str) -> str:
    """Save a finished trip plan as a text file so the user can keep it.

    Use this only when the user asks to save or export the plan.

    Args:
        filename: Short file name without folders, for example "almaty_weekend".
        content: The full text of the plan to save.
    """
    try:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", filename.strip())[:60] or "trip_plan"
        PLANS_DIR.mkdir(exist_ok=True)
        path = PLANS_DIR / f"{safe}.txt"
        path.write_text(content, encoding="utf-8")
        return _ok({"saved": True, "path": str(path)})
    except OSError as exc:
        return _err(f"Could not save the file ({type(exc).__name__}).")


ALL_TOOLS = [
    get_weather_forecast,
    convert_currency,
    get_country_info,
    get_place_summary,
    get_packing_list,
    calculate_trip_budget,
    save_trip_plan,
]
