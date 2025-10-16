# app.py
import os
import math
import re
import logging
from datetime import datetime, timezone, timedelta
import pytz
import requests
import ephem
from flask import Flask, jsonify
from openai import OpenAI


# ---------- Logging-Konfiguration ----------
logging.basicConfig(
    level=logging.INFO,  # DEBUG fuer mehr Details
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ---------- Flask ----------
app = Flask(__name__)

# ---------- Standort / Beobachter ----------
DEFAULT_LAT = "47.3769"    # Zürich
DEFAULT_LON = "8.5417"
DEFAULT_ELEV = 408         # ca. Zürich in Metern

def _get_env_coord(var_name, default):
    try:
        val = os.environ.get(var_name, str(default))
        float(val)  # prüfen ob Zahl parsbar ist
        return val
    except Exception:
        logger.warning(f"Invalid value for {var_name}, using default {default}")
        return str(default)

def _get_env_int(var_name, default):
    try:
        val = int(os.environ.get(var_name, default))
        return val
    except Exception:
        logger.warning(f"Invalid value for {var_name}, using default {default}")
        return default

lat = _get_env_coord("LAT", DEFAULT_LAT)
lon = _get_env_coord("LON", DEFAULT_LON)
elevation = _get_env_int("ELEVATION", DEFAULT_ELEV)

observer = ephem.Observer()
observer.lat = lat
observer.lon = lon
observer.elevation = 420  # m
observer.date = datetime.now(pytz.utc)  # initiale Zeit

# ---------- ISS TLE Auto-Update (Cache + Fallback) ----------
TLE_URL = os.environ.get("ISS_TLE_URL", "https://live.ariss.org/iss.txt")
TLE_TTL = timedelta(hours=6)
_tle_cache = {
    "line1": None,
    "line2": None,
    "expires_at": datetime.min.replace(tzinfo=timezone.utc),
    "etag": None,
    "last_modified": None,
}

def _parse_tle_from_text(txt: str):
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    l1, l2 = None, None
    for i in range(len(lines) - 1):
        if lines[i].startswith("1 ") and lines[i+1].startswith("2 "):
            l1, l2 = lines[i], lines[i+1]
            break
    if not (l1 and l2):
        raise ValueError("Kein gueltiges TLE-Paar gefunden")
    return l1, l2

def _fetch_tle_remote():
    headers = {}
    if _tle_cache.get("etag"):
        headers["If-None-Match"] = _tle_cache["etag"]
    if _tle_cache.get("last_modified"):
        headers["If-Modified-Since"] = _tle_cache["last_modified"]

    resp = requests.get(TLE_URL, headers=headers, timeout=8)
    if resp.status_code == 304:
        return None, None, _tle_cache.get("etag"), _tle_cache.get("last_modified")

    resp.raise_for_status()
    l1, l2 = _parse_tle_from_text(resp.text)
    etag = resp.headers.get("ETag")
    last_modified = resp.headers.get("Last-Modified")
    return l1, l2, etag, last_modified

def get_iss_tle():
    now = datetime.now(timezone.utc)
    cache_valid = now < _tle_cache["expires_at"] and _tle_cache["line1"] and _tle_cache["line2"]

    if cache_valid:
        return _tle_cache["line1"], _tle_cache["line2"]

    try:
        l1, l2, etag, last_mod = _fetch_tle_remote()
        if l1 and l2:
            _tle_cache["line1"] = l1
            _tle_cache["line2"] = l2
            _tle_cache["etag"] = etag
            _tle_cache["last_modified"] = last_mod
            _tle_cache["expires_at"] = now + TLE_TTL
            logger.info("ISS TLE aktualisiert")
            return l1, l2
        elif _tle_cache["line1"] and _tle_cache["line2"]:
            _tle_cache["expires_at"] = now + TLE_TTL
            logger.info("ISS TLE unveraendert (304)")
            return _tle_cache["line1"], _tle_cache["line2"]
    except Exception as e:
        logger.warning(f"TLE Update fehlgeschlagen: {e}")

    if _tle_cache["line1"] and _tle_cache["line2"]:
        logger.info("Verwende letztes gueltiges TLE aus Cache")
        return _tle_cache["line1"], _tle_cache["line2"]

    logger.info("Verwende harteingebautes Fallback-TLE")
    return (
        "1 25544U 98067A   25222.48428578  .00007827  00000-0  14282-3 0  9993",
        "2 25544  51.6367  37.9417 0001853 175.3844 230.1801 15.50428464523587",
    )

# ---------- Helper ----------
def get_cardinal_direction(azimuth_rad):
    az_deg = azimuth_rad * 180 / 3.141592653589793
    directions = [
        "N","NNE","NE","ENE","E","ESE","SE","SSE",
        "S","SSW","SW","WSW","W","WNW","NW","NNW",
    ]
    idx = int((az_deg + 11.25) / 22.5)
    return az_deg, directions[idx % 16]

def iss_orbital_velocity(altitude_m):
    G = 6.67430e-11
    M = 5.972e24
    R = 6371000
    r = R + altitude_m
    return math.sqrt(G * M / r) / 1000.0  # km/s



# ---------- Routes ----------
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

################ POEM ################
@app.route("/poem")
def poem():
    logger.info("Route /poem aufgerufen")

    # Zeit Europe/Zurich
    utc_now = datetime.now(pytz.utc)
    local_tz = pytz.timezone("Europe/Zurich")
    current_date = utc_now.astimezone(local_tz).strftime("%d.%m.%Y")
    current_time = utc_now.astimezone(local_tz).strftime("%H:%M")

    # ENV
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OW_KEY = os.environ.get("OW_KEY")
    MODEL = os.environ.get("MODEL", "gpt-4o-mini")  # per docker-compose steuerbar
    if not OPENAI_API_KEY or not OW_KEY:
        return jsonify({"error": "OPENAI_API_KEY oder OW_KEY fehlt"}), 500

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Wetter holen (deutsch)
    try:
        ow_url = (
            "http://api.openweathermap.org/data/2.5/weather"
            f"?appid={OW_KEY}&lat={lat}&lon={lon}&units=metric&lang=de"
        )
        weather_data = requests.get(ow_url, timeout=10).json()
    except Exception as e:
        logger.exception("Fehler beim Laden der Wetterdaten")
        return jsonify({"error": "Weather API failure", "details": str(e)}), 502

    # Umweltdaten lokaler Dienst (failsafe ueberschreiben)
    try:
        umweltdaten = requests.get("http://192.168.0.42/getval.php", timeout=5).json()
        weather_data.setdefault("main", {})
        weather_data["main"]["temp"] = umweltdaten.get(
            "TempLuftAussen", weather_data["main"].get("temp")
        )
    except Exception as e:
        logger.warning(f"Konnte Umweltdaten nicht laden: {e}")

    # Temperatur fix (eine Nachkommastelle, Punkt, keine Einheit)
    try:
        temp_val = float(weather_data["main"]["temp"])
        temp_str = f"{temp_val:.1f}"
    except Exception:
        temp_str = "0.0"

    # Saison & Ton
    mon = utc_now.astimezone(local_tz).month
    season = ("Winter" if mon in (12, 1, 2) else
              "Fruehling" if mon in (3, 4, 5) else
              "Sommer" if mon in (6, 7, 8) else
              "Herbst")
    wx_desc = (weather_data.get("weather") or [{}])[0].get("description") or "passendes Wetter"

    # Prompts: KI soll zwei Saetze schreiben, aber mit Platzhaltern (ohne Zahlen)
    system_msg = (
        "Du schreibst sehr kurze, zum Denken anregende Gedichte auf Deutsch und verwendest nie das Zeichen ß, "
        "sondern immer ss."
    )
    user_msg = (
        "Schreibe ein zum Denken anregendes Gedicht passend zur Jahreszeit mit GENAU zwei Saetzen, "
        "jeder Satz hoechstens 16 Woerter. "
        "Verwende KEINE Ziffern. Stattdessen nutze GENAU EINMAL die Platzhalter [TIME], [DATE], [TEMP] "
        "fuer Uhrzeit, Datum und Temperatur. "
        "Die Platzhalter duerfen nicht veraendert, erweitert oder wiederholt werden. "
        f"Jahreszeit: {season}, Wetter: {wx_desc}. "
        "Keine Anfuehrungszeichen, keine englischen Woerter. "
        "Gib nur die zwei Saetze zurueck."
    )

    is_reasoning = MODEL.startswith("gpt-5")
    try:
        if is_reasoning:
            resp = client.responses.create(
                model=MODEL,
                reasoning={"effort": "minimal"},
                instructions=system_msg,
                input=[{"role": "user", "content": [{"type": "input_text", "text": user_msg}]}],
            )
        else:
            resp = client.responses.create(
                model=MODEL,
                temperature=0.8,
                top_p=0.95,
                instructions=system_msg,
                input=[{"role": "user", "content": [{"type": "input_text", "text": user_msg}]}],
            )
        text = (resp.output_text or "").replace("ß", "ss").replace('"', '').replace("'", "")
    except Exception as e:
        logger.exception("Fehler bei der OpenAI-Generierung")
        return jsonify({"error": "OpenAI failure", "details": str(e)}), 502

    # --- Post-Processing: genau 2 Saetze, Platzhalter ersetzen, Regeln sichern ---
    # 1) Auf saetze splitten
    parts = [p.strip() for p in re.split(r"[.!?]\s*", text) if p.strip()]
    if len(parts) == 0:
        parts = ["Heute fuehlt es sich gut an", "Und alles bleibt freundlich leicht"]
    elif len(parts) == 1:
        parts.append("Und alles fuehlt sich gut an")

    parts = parts[:2]

    # 2) Platzhalter-Pruefung & Ersetzung
    def replace_placeholders(s: str) -> str:
        # Keine Ziffern erlauben, Platzhalter ersetzen
        s = s.replace("ß", "ss")
        # Erst sicherstellen, dass keine Ziffern enthalten sind
        s = re.sub(r"\d", "", s)
        # Ersetzen
        s = s.replace("[TIME]", current_time)
        s = s.replace("[DATE]", current_date)
        s = s.replace("[TEMP]", temp_str)
        return s

    parts = [replace_placeholders(p) for p in parts]

    # 3) Falls ein Platzhalter vergessen wurde, fuege ihn sinnvoll hinzu
    joined = " ".join(parts)
    if current_time not in joined:
        parts[0] = (parts[0] + f" um {current_time}").strip()
    if current_date not in " ".join(parts):
        parts[0] = (parts[0] + f" am {current_date}").strip()
    if temp_str not in " ".join(parts):
        parts[1] = (parts[1] + f" bei {temp_str}").strip()

    # 4) Dezimal-Kommas korrigieren (Sicherheit) und doppelte Leerzeichen
    parts = [re.sub(r"(?<=\d),(?=\d)", ".", p) for p in parts]
    parts = [re.sub(r"\s+", " ", p).strip() for p in parts]

    # 5) Max 16 Woerter/Satz erzwingen
    def clip_words(s: str, max_words=16) -> str:
        words = s.split()
        return " ".join(words[:max_words])

    parts = [clip_words(p, 16) for p in parts]

    # 6) Satzendzeichen setzen
    for i in range(2):
        if not re.search(r"[.!?]$", parts[i]):
            parts[i] += "."

    poem_text = parts[0] + " " + parts[1]
    return jsonify({"poem": poem_text})


################ ISS ################
def iss_position():
    l1, l2 = get_iss_tle()
    iss = ephem.readtle("ISS (ZARYA)", l1, l2)

    observer.date = datetime.now(pytz.utc)
    iss.compute(observer)

    az_deg, card = get_cardinal_direction(iss.az)
    altitude_km = iss.elevation / 1000.0
    velocity_kmps = iss_orbital_velocity(iss.elevation)
    los_distance_km = iss.range / 1000.0

    return {
        "cardinal_direction": card,
        "azimuth_degrees": round(az_deg, 2),
        "altitude_kilometers": round(altitude_km, 2),
        "orbital_velocity_kmps": round(velocity_kmps, 2),
        "line_of_sight_distance_km": round(los_distance_km, 2),
    }

@app.route("/iss")
def iss():
    logger.info("Route /iss aufgerufen")
    try:
        data = iss_position()
        return jsonify(data)
    except Exception as e:
        logger.exception("Fehler bei ISS-Berechnung")
        return jsonify({"error": "ISS computation failure", "details": str(e)}), 500

################ MOON ################
def next_moon():
    now_utc = datetime.now(timezone.utc)
    next_full_moon = ephem.next_full_moon(now_utc)
    next_dt = datetime.strptime(str(next_full_moon), "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
    delta = next_dt - now_utc
    return {"days_to_full_moon": delta.days, "next_full_moon_date": next_dt.isoformat()}

@app.route("/moon")
def moon():
    logger.info("Route /moon aufgerufen")
    try:
        data = next_moon()
        return jsonify(data)
    except Exception as e:
        logger.exception("Fehler bei Mondberechnung")
        return jsonify({"error": "Moon computation failure", "details": str(e)}), 500

################ LOCATION ################
@app.route("/location")
def location():
    logger.info("Route /location aufgerufen")
    return jsonify({
        "lat": float(lat),
        "lon": float(lon),
        "elevation_meters": elevation
    })


# ---------- Main (lokales Debugging) ----------
if __name__ == "__main__":
    # In Produktion via gunicorn starten:
    # gunicorn -w 2 -b 0.0.0.0:8000 app:app --log-level info
    app.run(host="0.0.0.0", port=8000, debug=False)
