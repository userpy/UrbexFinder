import type * as MapLibre from "maplibre-gl";

// Keep retry available after permission or network failures.
export function locationControl(
  lib: typeof MapLibre,
  onStatus: (message: string) => void,
): MapLibre.IControl & { setAccuracyVisible: (visible: boolean) => void } {
  let map: MapLibre.Map | undefined;
  let dot: MapLibre.Marker | undefined;
  let accuracyCircle: MapLibre.Marker | undefined;
  let accuracyVisible = false;
  let position: { center: [number, number]; accuracy: number } | undefined;
  function updateAccuracy() {
    if (!map || !position || !accuracyVisible) {
      accuracyCircle?.remove();
      return;
    }
    if (!accuracyCircle) {
      const element = document.createElement("div");
      element.className = "maplibregl-user-location-accuracy-circle";
      element.style.pointerEvents = "none";
      element.setAttribute("aria-hidden", "true");
      accuracyCircle = new lib.Marker({ element, pitchAlignment: "map" });
    }
    const metersPerPixel =
      (40075016.686 * Math.cos((position.center[1] * Math.PI) / 180)) /
      (512 * 2 ** map.getZoom());
    const diameter = (2 * position.accuracy) / metersPerPixel;
    const element = accuracyCircle.getElement();
    element.style.width = `${diameter}px`;
    element.style.height = `${diameter}px`;
    accuracyCircle.setLngLat(position.center).addTo(map);
  }
  let watch: number | undefined;
  let fallbackWatch: number | undefined;
  let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
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
    clearTimeout(fallbackTimer);
    if (watch !== undefined) navigator.geolocation.clearWatch(watch);
    if (fallbackWatch !== undefined) navigator.geolocation.clearWatch(fallbackWatch);
    watch = undefined;
    fallbackWatch = undefined;
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
    const id = ++request;
    const distance = (accuracy: number) =>
      accuracy >= 1000
        ? `${(accuracy / 1000).toFixed(1)} км`
        : `${Math.round(accuracy)} м`;
    const fail = (code: number) => {
      if (!map || id !== request) return;
      finish(
        code === 1
          ? "Доступ к местоположению запрещён. Разрешите его в настройках сайта и системы, затем нажмите кнопку ещё раз."
          : code === 3
            ? "Браузер не сообщил местоположение. Проверьте геолокацию в настройках системы или укажите место двойным щелчком по карте."
            : "Служба геолокации браузера недоступна. Проверьте соединение и повторите попытку.",
      );
    };
    const success: PositionCallback = ({ coords }) => {
        if (!map || id !== request) return;
        const accuracy = coords.accuracy;
        if (!Number.isFinite(accuracy) || accuracy < 0) return;
        const center: [number, number] = [coords.longitude, coords.latitude];
        position = { center, accuracy };
        updateAccuracy();
        if (!dot) {
          const element = document.createElement("div");
          element.className = "maplibregl-user-location-dot";
          dot = new lib.Marker({ element });
        }
        dot.setLngLat(center).addTo(map);
        map.easeTo({ center, zoom: Math.max(map.getZoom(), 14) });
        finish(
          `Местоположение определено. Точность по данным браузера: ±${distance(accuracy)}.`,
        );
      };
    const startFallback = () => {
      if (!map || id !== request || fallbackWatch !== undefined) return;
      fallbackWatch = navigator.geolocation.watchPosition(
        success,
        ({ code }) => { if (code === 1) fail(code); },
        { enableHighAccuracy: false, maximumAge: 60000, timeout: 10000 },
      );
    };
    timer = setTimeout(() => fail(3), 20000);
    fallbackTimer = setTimeout(startFallback, 8000);
    watch = navigator.geolocation.watchPosition(
      success,
      ({ code }) => {
        if (code === 1) fail(code);
        else startFallback();
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    );
  };
  return {
    setAccuracyVisible(visible) {
      accuracyVisible = visible;
      updateAccuracy();
    },
    onAdd(instance) {
      map = instance;
      map.on("zoom", updateAccuracy);
      return container;
    },
    onRemove() {
      ++request;
      clearTimeout(timer);
      clearTimeout(fallbackTimer);
      if (watch !== undefined) navigator.geolocation.clearWatch(watch);
      if (fallbackWatch !== undefined) navigator.geolocation.clearWatch(fallbackWatch);
      watch = undefined;
      fallbackWatch = undefined;
      dot?.remove();
      accuracyCircle?.remove();
      map?.off("zoom", updateAccuracy);
      container.remove();
      map = undefined;
    },
  };
}
