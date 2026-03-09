import requests
import simplekml
import time
import sys
from loguru import logger

# ================== НАСТРОЙКИ ==================

WIKIMAPIA_API_KEY = "DE78E139-2B064BBC-857C77B0-714E47D2-61E51FEC-9F388503-07F10D5D-49DBD4E"

# Категория Wikimapia (ID)
CATEGORY_ID = 44690  # Бомбоубежища
#CATEGORY_ID = 2390 # Заброшенное
#TOP_POINT — сверху слева (lat, lon)
TOP_POINT = [56.0, 37.0]

# BOTTOM_POINT — снизу справа (lat, lon)
BOTTOM_POINT = [55.0, 38.0]

MAX_PAGES = 10
RESULTS_PER_PAGE = 100
REQUEST_DELAY = 1.0  # секунды

OUTPUT_FILE = f"wikimapia_{CATEGORY_ID}_{TOP_POINT}_{BOTTOM_POINT}.kml"

# ===============================================


def build_bbox(top_point, bottom_point):
    lat_top, lon_left = top_point
    lat_bottom, lon_right = bottom_point

    if lat_top <= lat_bottom:
        raise ValueError("TOP_POINT.lat должен быть больше BOTTOM_POINT.lat")
    if lon_right <= lon_left:
        raise ValueError("BOTTOM_POINT.lon должен быть больше TOP_POINT.lon")

    left = lon_left
    bottom = lat_bottom
    right = lon_right
    top = lat_top

    return f"{left},{bottom},{right},{top}"


def fetch_page(page, bbox):
    url = "http://api.wikimapia.org/"
    params = {
        "key": API_KEY,
        "function": "box",
        "bbox": bbox,
        "category": CATEGORY_ID,
        "page": page,
        "count": RESULTS_PER_PAGE,
        "format": "json"
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def main():
    try:
        bbox = build_bbox(TOP_POINT, BOTTOM_POINT)
    except ValueError as e:
        logger.info(f"Ошибка координат: {e}")
        sys.exit(1)

    logger.info(f"Используем bbox: {bbox}")
    logger.info("Начинаю загрузку данных...")

    kml = simplekml.Kml()
    total = 0

    for page in range(1, MAX_PAGES + 1):
        logger.info(f"  Страница {page}")

        try:
            data = fetch_page(page, bbox)
        except Exception as e:
            logger.info(f"  Ошибка запроса: {e}")
            break

        places = data.get("places", [])
        if not places:
            logger.info("  Больше объектов нет")
            break

        for place in places:
            title = place.get("title", "Без названия")
            location = place.get("location")
            if not location:
                continue

            lon = location.get("lon")
            lat = location.get("lat")
            if lon is None or lat is None:
                continue

            point = kml.newpoint(
                name=title,
                coords=[(lon, lat)]
            )

            description = []

            if "description" in place:
                description.append(place["description"])

            if "categories" in place:
                cats = ", ".join(
                    c.get("title", "") for c in place["categories"]
                )
                description.append(f"Категории: {cats}")

            point.description = "\n".join(description)
            total += 1

        time.sleep(REQUEST_DELAY)

    kml.save(OUTPUT_FILE)
    logger.info(f"Готово. Сохранено объектов: {total}")
    logger.info(f"Файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
