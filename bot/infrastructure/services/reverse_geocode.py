import httpx

async def reverse_geocode( lat: float, lon: float) -> dict:
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json"
    }
    headers = {
        "User-Agent": "AsyncReverseGeocoder/1.0"  # Nominatim требует User-Agent
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()  # выбросит ошибку, если статус не 200
        return response.json()
    