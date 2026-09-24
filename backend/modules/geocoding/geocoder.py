"""Онлайн-геокодирование адресов заявок.

Порядок источников: DaData (ФИАС, лучше всех понимает российские адреса) → кэш
`solution/data/geocache.json` → Photon и Nominatim (OpenStreetMap). Берётся первый
ответ с точностью до дома или улицы; более грубый держится про запас. Если не нашёл
никто — точка рядом с центром района с пометкой «район».

Каждый ответ проверяется на правдоподобие: адрес в Москве обязан лечь в Москву, а
точка — не дальше MAX_KM от центра своего района. Так отсекаются промахи вида
«Орехово-Зуевский проезд → город Орехово-Зуево».
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from dadata import DadataAsync
from geopy.exc import GeopyError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim, Photon

from core.config import Settings

_SOLUTION = Path(__file__).resolve().parents[3] / "solution"
if str(_SOLUTION) not in sys.path:
    sys.path.insert(0, str(_SOLUTION))

from planner.io_csv import DATA_DIR, normalize_address  # noqa: E402
from tools.address import build_queries  # noqa: E402

logger = logging.getLogger(__name__)

HOUSE = "дом"
STREET = "улица"
SETTLEMENT = "населённый пункт"
DISTRICT = "район"
_RANK = {HOUSE: 0, STREET: 1, SETTLEMENT: 2, DISTRICT: 3}
SETTLED = frozenset({HOUSE, STREET})
"""Точности, после которых адрес больше не геокодируется."""

# (south, west, north, east)
MOSCOW_BBOX = (55.13, 36.80, 56.03, 37.97)
REGION_BBOX = (54.25, 35.14, 56.97, 40.21)  # Москва и Московская область
MOSCOW_CENTRE = (55.7522, 37.6156)
MAX_KM = {True: 15.0, False: 30.0}  # от центра района: Москва / область

_DADATA_LOCATIONS = [{"region": "Москва"}, {"region": "Московская"}]
_DADATA_QC_GEO = {"0": HOUSE, "1": HOUSE, "2": STREET, "3": SETTLEMENT, "4": SETTLEMENT}
_REGION_MARK = re.compile(r"\bобл\b|област|\bмо\b", re.IGNORECASE)
MAX_FAILURES = 3
"""Сетевых ошибок подряд, после которых источник пропускается до конца пакета."""


@dataclass(frozen=True, slots=True)
class GeoHit:
    lat: float
    lon: float
    precision: str
    source: str

    @property
    def rank(self) -> int:
        return _RANK.get(self.precision, len(_RANK))


def is_moscow(address: str) -> bool:
    """Адрес в самой Москве, а не в области: там допуск по расстоянию строже."""
    text = address.lower()
    return "москва" in text and not _REGION_MARK.search(text)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (a[0] - b[0]) * 111.2
    dlon = (a[1] - b[1]) * 111.2 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east


class Provider(Protocol):
    name: str
    broken: bool

    async def lookup(self, address: str) -> GeoHit | None: ...


class DadataProvider:
    """DaData: подсказки (`suggest`), а с секретным ключом — стандартизация (`clean`)."""

    name = "dadata"

    def __init__(self, token: str, secret: str | None, timeout: float) -> None:
        self._client = DadataAsync(token, secret, timeout=timeout)
        self._clean = bool(secret)
        self._failures = 0
        self.broken = False

    async def lookup(self, address: str) -> GeoHit | None:
        best: GeoHit | None = None
        # Сырой адрес DaData разбирает сам; нормализованный — для форматов вроде
        # «Самаркандский Квартал 137а, д. к5», где сырой не находится
        for query in [address, *build_queries(address)[:2]]:
            hit = await self._query(query)
            if hit is not None and (best is None or hit.rank < best.rank):
                best = hit
            if best is not None and best.precision in SETTLED:
                break
        return best

    async def _query(self, query: str) -> GeoHit | None:
        try:
            if self._clean:
                data = await self._client.clean("address", query)
            else:
                found = await self._client.suggest(
                    "address", query, count=1, locations=_DADATA_LOCATIONS
                )
                data = found[0]["data"] if found else None
        except httpx.HTTPError as exc:
            self._failures += 1
            self.broken = self._failures >= MAX_FAILURES
            logger.warning("DaData: %r%s", exc, " — дальше без неё" if self.broken else "")
            return None
        self._failures = 0
        if not data or not data.get("geo_lat") or not data.get("geo_lon"):
            return None
        precision = _DADATA_QC_GEO.get(str(data.get("qc_geo")))
        if precision is None:
            return None
        return GeoHit(float(data["geo_lat"]), float(data["geo_lon"]), precision, self.name)

    async def close(self) -> None:
        await self._client.close()


class FileCacheProvider:
    """Кэш из репозитория: адреса исходных выгрузок, геокодированные заранее."""

    name = "geocache"

    def __init__(self, path: Path = DATA_DIR / "geocache.json") -> None:
        self.broken = False
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self._addresses: dict[str, dict] = payload.get("addresses", {})
        self.districts: dict[str, tuple[float, float]] = {
            name.strip().lower(): (float(p["lat"]), float(p["lon"]))
            for name, p in payload.get("districts", {}).items()
        }

    async def lookup(self, address: str) -> GeoHit | None:
        entry = self._addresses.get(normalize_address(address))
        if entry is None:
            return None
        precision = str(entry.get("precision", HOUSE))
        return GeoHit(float(entry["lat"]), float(entry["lon"]), precision, self.name)


class OsmProvider:
    """Photon, затем Nominatim — по лестнице запросов «дом → улица → населённый пункт».

    Правила Nominatim: не чаще раза в секунду и осмысленный User-Agent. Сетевые вызовы
    geopy синхронные, поэтому идут в потоке и по одному.
    """

    name = "osm"

    def __init__(self, user_agent: str, timeout: float) -> None:
        self.broken = False
        self._failures = 0
        self._photon = Photon(user_agent=user_agent, timeout=timeout)
        nominatim = Nominatim(user_agent=user_agent, timeout=timeout)
        # swallow_exceptions=False: иначе RateLimiter прячет сетевые ошибки и счётчик не растёт
        self._nominatim = RateLimiter(
            nominatim.geocode, min_delay_seconds=1.1, max_retries=0, swallow_exceptions=False
        )
        self._lock = asyncio.Lock()
        south, west, north, east = REGION_BBOX
        self._box = [(south, west), (north, east)]

    async def lookup(self, address: str) -> GeoHit | None:
        async with self._lock:
            return await asyncio.to_thread(self._lookup, address)

    def _lookup(self, address: str) -> GeoHit | None:
        best: GeoHit | None = None
        for query in build_queries(address):
            for hit in (self._ask_photon(query), self._ask_nominatim(query)):
                if self.broken:
                    return best
                if hit is not None and (best is None or hit.rank < best.rank):
                    best = hit
                if best is not None and best.precision in SETTLED:
                    return best
        return best

    def _ask_photon(self, query: str) -> GeoHit | None:
        try:
            found = self._photon.geocode(query, bbox=self._box)
        except GeopyError as exc:
            logger.warning("Photon: %r", exc)
            return None
        if found is None:
            return None
        kind = found.raw.get("properties", {}).get("type", "")
        precision = HOUSE if kind == "house" else STREET if kind == "street" else SETTLEMENT
        return GeoHit(found.latitude, found.longitude, precision, "photon")

    def _ask_nominatim(self, query: str) -> GeoHit | None:
        try:
            found = self._nominatim(
                query, country_codes="ru", viewbox=self._box, bounded=True, language="ru"
            )
        except GeopyError as exc:
            self._failures += 1
            self.broken = self._failures >= MAX_FAILURES
            logger.warning("Nominatim: %r%s", exc, " — дальше без OSM" if self.broken else "")
            return None
        self._failures = 0
        if found is None:
            return None
        kind = found.raw.get("addresstype", "")
        if kind in ("building", "house") or found.raw.get("type") == "house":
            precision = HOUSE
        elif kind == "road":
            precision = STREET
        else:
            precision = SETTLEMENT
        return GeoHit(found.latitude, found.longitude, precision, "nominatim")


class AddressGeocoder:
    """Цепочка источников с проверкой правдоподобия. Использовать как `async with`."""

    def __init__(
        self, settings: Settings, anchors: dict[str, tuple[float, float]] | None = None
    ) -> None:
        cache = FileCacheProvider()
        self._providers: list[Provider] = []
        if settings.dadata_api_key:
            self._providers.append(
                DadataProvider(
                    settings.dadata_api_key, settings.dadata_secret_key, settings.geocoder_timeout
                )
            )
        self._providers.append(cache)
        if settings.geocoder_osm_enabled:
            self._providers.append(
                OsmProvider(settings.geocoder_user_agent, settings.geocoder_timeout)
            )
        # Центры районов: из кэша репозитория, поверх — медианы уже сохранённых точек
        self._anchors = {**cache.districts}
        self._anchors.update({k.strip().lower(): v for k, v in (anchors or {}).items()})
        self._limit = asyncio.Semaphore(5)

    async def __aenter__(self) -> "AddressGeocoder":
        return self

    async def __aexit__(self, *_: object) -> None:
        for provider in self._providers:
            if isinstance(provider, DadataProvider):
                await provider.close()

    def plausible(self, lat: float, lon: float, address: str, district: str) -> bool:
        moscow = is_moscow(address)
        if not _in_bbox(lat, lon, MOSCOW_BBOX if moscow else REGION_BBOX):
            return False
        anchor = self._anchors.get(district.strip().lower())
        return anchor is None or distance_km((lat, lon), anchor) <= MAX_KM[moscow]

    async def locate(self, address: str, district: str) -> GeoHit:
        best: GeoHit | None = None
        async with self._limit:
            for provider in self._providers:
                if provider.broken:
                    continue
                hit = await provider.lookup(address)
                if hit is None:
                    continue
                if not self.plausible(hit.lat, hit.lon, address, district):
                    logger.warning(
                        "Геокодер %s: %s → %.5f, %.5f вне района «%s», отброшено",
                        hit.source, address, hit.lat, hit.lon, district,
                    )
                    continue
                if hit.precision in SETTLED:
                    return hit
                if best is None or hit.rank < best.rank:
                    best = hit
        if best is not None:
            logger.info("Геокодер: %s — точность «%s» (%s)", address, best.precision, best.source)
            return best
        logger.warning("Геокодер: %s не найден, точка по району «%s»", address, district)
        return self.approximate(address, district)

    async def locate_many(self, items: list[tuple[str, str]]) -> dict[tuple[str, str], GeoHit]:
        """(district, address) → точка. Уникальные пары геокодируются параллельно."""
        unique = list(dict.fromkeys(items))
        hits = await asyncio.gather(*(self.locate(address, d) for d, address in unique))
        return dict(zip(unique, hits))

    def approximate(self, address: str, district: str) -> GeoHit:
        """Детерминированная точка около центра района — как заглушка планировщика."""
        centre = self._anchors.get(district.strip().lower(), MOSCOW_CENTRE)
        digest = hashlib.sha256(normalize_address(address).encode("utf-8")).digest()
        dlat = (int.from_bytes(digest[0:4], "big") / 0xFFFFFFFF - 0.5) * 0.02
        dlon = (int.from_bytes(digest[4:8], "big") / 0xFFFFFFFF - 0.5) * 0.034
        return GeoHit(centre[0] + dlat, centre[1] + dlon, DISTRICT, "approximate")
