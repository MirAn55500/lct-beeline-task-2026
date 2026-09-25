"""Подсказки адресов и адрес по точке — для выбора офиса бригады на карте.

Как на сайтах доставки: человек печатает адрес и выбирает его из списка (DaData
«Подсказки», по ФИАС), а точку уточняет, двигая карту под булавкой. Ответ нужен за доли
секунды, поэтому у подсказок свой HTTP-клиент:

- один на процесс, соединение держится 5 минут и открывается ещё при старте (`warm_up`);
- только IPv4: в Docker Desktop запрос AAAA к DNS висит 4 с на каждое новое соединение,
  а DaData отвечает по IPv4.

Нет ключа DaData или она не ответила — подсказки берутся у Photon (OpenStreetMap).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx
from geopy.exc import GeopyError
from geopy.geocoders import Photon

from core.config import get_settings
from modules.geocoding.geocoder import REGION_BBOX, address_text, has_house

logger = logging.getLogger(__name__)

_API = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"
_LOCATIONS = [{"region": "Москва"}, {"region": "Московская"}]
_client: httpx.AsyncClient | None = None
_photon: Photon | None = None


@dataclass(frozen=True, slots=True)
class Suggestion:
    address: str
    lat: float
    lon: float
    house: bool
    """Адрес с номером дома — только такой годится для офиса."""


def _dadata() -> httpx.AsyncClient | None:
    global _client
    settings = get_settings()
    if not settings.dadata_api_key:
        return None
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_API,
            headers={
                "Authorization": f"Token {settings.dadata_api_key}",
                "Accept": "application/json",
            },
            # local_address 0.0.0.0 — соединение и DNS только по IPv4
            transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=1),
            limits=httpx.Limits(keepalive_expiry=300),
            timeout=httpx.Timeout(settings.geocoder_timeout, connect=5),
        )
    return _client


async def _post(path: str, body: dict) -> list[dict]:
    client = _dadata()
    assert client is not None
    response = await client.post(path, json=body)
    response.raise_for_status()
    return response.json().get("suggestions", [])


async def warm_up() -> None:
    """Открыть соединение с DaData заранее — первая подсказка не ждёт TLS."""
    if _dadata() is None:
        return
    try:
        await _post("/suggest/address", {"query": "Москва", "count": 1})
    except httpx.HTTPError as exc:
        logger.warning("DaData: прогрев не удался: %r", exc)


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _osm() -> Photon:
    global _photon
    if _photon is None:
        settings = get_settings()
        _photon = Photon(user_agent=settings.geocoder_user_agent, timeout=settings.geocoder_timeout)
    return _photon


async def suggest(query: str, count: int = 7) -> list[Suggestion]:
    """Адреса Москвы и области, начинающиеся с того, что напечатали."""
    if _dadata() is not None:
        try:
            found = await _post(
                "/suggest/address", {"query": query, "count": count, "locations": _LOCATIONS}
            )
        except httpx.HTTPError as exc:
            logger.warning("DaData suggest: %r — подсказки от Photon", exc)
        else:
            return [
                Suggestion(
                    address=item["value"],
                    lat=float(item["data"]["geo_lat"]),
                    lon=float(item["data"]["geo_lon"]),
                    house=bool(item["data"].get("house")),
                )
                for item in found
                if item["data"].get("geo_lat") and item["data"].get("geo_lon")
            ]
    return await asyncio.to_thread(_photon_suggest, query, count)


def _photon_suggest(query: str, count: int) -> list[Suggestion]:
    south, west, north, east = REGION_BBOX
    try:
        found = _osm().geocode(
            query, exactly_one=False, limit=count, bbox=[(south, west), (north, east)]
        )
    except GeopyError as exc:
        logger.warning("Photon suggest: %r", exc)
        return []
    items: list[Suggestion] = []
    for location in found or []:
        parts = location.raw.get("properties", {})
        text = address_text(
            parts.get("city"), parts.get("street") or parts.get("name"), parts.get("housenumber")
        )
        if text:
            items.append(
                Suggestion(text, location.latitude, location.longitude, bool(parts.get("housenumber")))
            )
    return items


async def geolocate(lat: float, lon: float) -> str | None:
    """Ближайший к точке адрес по DaData — «г Москва, ул Тверская, д 13»."""
    if _dadata() is None:
        return None
    try:
        found = await _post(
            "/geolocate/address", {"lat": lat, "lon": lon, "count": 1, "radius_meters": 100}
        )
    except httpx.HTTPError as exc:
        logger.warning("DaData geolocate: %r", exc)
        return None
    return found[0]["value"] if found else None


__all__ = ["Suggestion", "close", "geolocate", "has_house", "suggest", "warm_up"]
