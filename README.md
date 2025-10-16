# Pythonista – Fun Poem & Space Info API

**Pythonista** is a lightweight Flask application packaged in Docker that provides playful and informative endpoints:

- `/poem` – generates a short two-sentence German poem using OpenAI models and current weather data.
- `/iss` – returns real-time position and orbital data of the ISS (with automatic TLE updates).
- `/moon` – returns the next full moon date and days until it occurs.
- `/location` – shows the active coordinates (lat, lon, elevation) used by the container.
- `/health` – simple healthcheck endpoint.

The app can be configured with your own coordinates via environment variables and supports custom local weather data integration.

---

## Requirements

- Docker and Docker Compose
- An [OpenWeather API key](https://openweathermap.org/api)
- An [OpenAI API key](https://platform.openai.com/)

---

## Build and Run

Clone this repository and build the container:

```bash
docker build -t pythonista .
```

Run it via Docker Compose:

```yaml
services:
  pythonista:
    container_name: pythonista
    ports:
      - "5123:5000"
    image: pythonista
    pull_policy: never
    user: "1000:1000"
    environment:
      - OW_KEY=<your OpenWeather key>
      - OPENAI_API_KEY=<your OpenAI key>
      - MODEL=gpt-4o-mini    # or gpt-5
      - LAT=<your latitude>
      - LON=<your longitude>
      - ELEVATION=<your elevation>
```

Start it:

```bash
docker compose up -d
```

The API will be available at [http://localhost:5123](http://localhost:5123).

---

## Environment Variables

| Variable         | Description                                   | Default (if missing/invalid) |
|------------------|-----------------------------------------------|-------------------------------|
| `OW_KEY`         | OpenWeather API key                           | –                             |
| `OPENAI_API_KEY` | OpenAI API key                                | –                             |
| `MODEL`          | OpenAI model (`gpt-4o-mini`, `gpt-5`, …)     | `gpt-4o-mini`                 |
| `LAT`            | Latitude for calculations                     | `47.3769` (Zurich)            |
| `LON`            | Longitude for calculations                    | `8.5417` (Zurich)             |
| `ELEVATION`      | Elevation in meters                           | `408` (Zurich)                |

If latitude/longitude/elevation are invalid, defaults for Zurich will be used and a warning will be logged.

---

## Endpoints & Examples

### Health
```bash
curl http://localhost:5123/health
```
Response:
```json
{ "status": "ok" }
```

### Location
Check which coordinates and elevation are currently active:

```bash
curl http://localhost:5123/location
```
Response:
```json
{
  "lat": 43.14113453857449,
  "lon": 8.366385619250336,
  "elevation_meters": 110
}
```

### Poem
```bash
curl http://localhost:5123/poem
```
Example response:
```json
{
  "poem": "ie Blätter fallen, der Wind flüstert Geschichten um 23:23 am 16.10.2025. Wolken verhüllen die Sonne bei 8.7 Grad, doch die Farben leuchten."
}
```

### ISS
```bash
curl http://localhost:5123/iss
```
Example response:
```json
{
  "cardinal_direction": "SSE",
  "azimuth_degrees": 152.43,
  "altitude_kilometers": 419.72,
  "orbital_velocity_kmps": 7.66,
  "line_of_sight_distance_km": 1243.85
}
```

### Moon
```bash
curl http://localhost:5123/moon
```
Example response:
```json
{
  "days_to_full_moon": 13,
  "next_full_moon_date": "2025-10-29T23:47:00+00:00"
}
```

---

## Custom Weather Data

By default, `/poem` uses [OpenWeather](https://openweathermap.org/) for temperature and conditions.  
If you want to integrate your **own local weather data source**, adapt the corresponding code in `app.py` (see section marked **"Umweltdaten lokaler Dienst"**). Replace the request URL and JSON key mapping with your local service.

---

## Development Notes

- Production startup:
  ```bash
  gunicorn --workers 2 -b 0.0.0.0:5000 app:app --log-level info
  ```
- Local debugging:
  ```bash
  python app.py
  ```
- Logging is enabled at INFO level. Warnings will appear if invalid or missing environment variables are detected.

---

## License

MIT License – see [LICENSE](LICENSE).
