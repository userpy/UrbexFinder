import type * as MapLibre from "maplibre-gl";

// Keep retry available after permission or network failures.
export function locationControl(
  lib: typeof MapLibre,
  onStatus: (message: string) => void,
): MapLibre.IControl {
  let map: MapLibre.Map | undefined;
  let dot: MapLibre.Marker | undefined;
  let request = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const container = document.createElement("div");
  container.className = "maplibregl-ctrl maplibregl-ctrl-group";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "maplibregl-ctrl-geolocate";
  button.title = "Моё местоположение";
  button.setAttribute("aria-label", button.title);
  const icon = document.createElement("span");
  icon.className = "maplibregl-ctrl-icon";
  icon.setAttribute("aria-hidden", "true");
  button.append(icon);
  container.append(button);
  function finish(message: string) {
    clearTimeout(timer);
    ++request;
    button.setAttribute("aria-disabled", "false");
    button.classList.remove("maplibregl-ctrl-geolocate-waiting");
    button.setAttribute("aria-busy", "false");
    onStatus(message);
  }
  button.onclick = () => {
    if (!map || button.getAttribute("aria-busy") === "true") return;
    if (!window.isSecureContext || !navigator.geolocation) {
      onStatus(
        "Геолокация недоступна. Откройте сайт по HTTPS или через localhost.",
      );
      return;
    }
    button.setAttribute("aria-disabled", "true");
    button.setAttribute("aria-busy", "true");
    button.classList.add("maplibregl-ctrl-geolocate-waiting");
    onStatus(
      "Определяем местоположение… Разрешите доступ, если браузер спросит.",
    );
    function locate(highAccuracy: boolean) {
      const id = ++request;
      clearTimeout(timer);
      const fail = (code: number) => {
        if (!map || id !== request) return;
        if (highAccuracy && code !== 1) {
          onStatus(
            "Точное местоположение недоступно. Пробуем обычную точность…",
          );
          locate(false);
          return;
        }
        finish(
          code === 1
            ? "Доступ к местоположению запрещён. Разрешите его в настройках сайта и системы, затем нажмите кнопку ещё раз."
            : code === 3
              ? "Браузер не сообщил местоположение в обоих режимах. Проверьте геолокацию в настройках системы или укажите место двойным щелчком по карте."
              : "Служба геолокации браузера недоступна. Проверьте соединение и повторите попытку.",
        );
      };
      timer = setTimeout(() => fail(3), 16000);
      navigator.geolocation.getCurrentPosition(
        ({ coords }) => {
          if (!map || id !== request) return;
          const center: [number, number] = [coords.longitude, coords.latitude];
          const accuracy = coords.accuracy;
          if (!dot) {
            const element = document.createElement("div");
            element.className = "maplibregl-user-location-dot";
            dot = new lib.Marker({ element });
          }
          dot.setLngLat(center).addTo(map);
          // Low desktop accuracy must not zoom the user out to an entire region.
          map.easeTo({ center, zoom: Math.max(map.getZoom(), 14) });
          const distance =
            accuracy >= 1000
              ? `${(accuracy / 1000).toFixed(1)} км`
              : `${Math.round(accuracy)} м`;
          finish(
            `Местоположение определено. Точность по данным браузера: ±${distance}.`,
          );
        },
        ({ code }) => fail(code),
        { enableHighAccuracy: highAccuracy, maximumAge: 0, timeout: 15000 },
      );
    }
    locate(true);
  };
  return {
    onAdd(instance) {
      map = instance;
      return container;
    },
    onRemove() {
      ++request;
      clearTimeout(timer);
      dot?.remove();
      container.remove();
      map = undefined;
    },
  };
}
