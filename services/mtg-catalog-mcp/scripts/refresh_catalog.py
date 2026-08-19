#!/usr/bin/env python3
"""Refresh the checked-in catalog with five bounded Scryfall API requests."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SETS = {
    "M11": ("Magic 2011", 2010),
    "ISD": ("Innistrad", 2011),
    "RTR": ("Return to Ravnica", 2012),
    "THS": ("Theros", 2013),
    "KTK": ("Khans of Tarkir", 2014),
}
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "catalog-v1.json"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
USER_AGENT = "Porfirium/0.1 catalog-refresh (local demonstration dataset)"


def fetch_set(set_code: str) -> list[dict[str, object]]:
    query = urllib.parse.urlencode(
        {
            "q": f"set:{set_code.lower()} game:paper usd>0",
            "unique": "prints",
            "order": "edhrec",
            "dir": "asc",
        }
    )
    request = urllib.request.Request(
        f"https://api.scryfall.com/cards/search?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json;q=0.9,*/*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    cards = payload.get("data", [])
    if len(cards) < 20:
        raise RuntimeError(f"Scryfall returned fewer than 20 priced cards for {set_code}")
    return cards[:20]


def text_field(card: dict[str, object], name: str) -> str | None:
    direct = card.get(name)
    if direct not in (None, ""):
        return str(direct)
    faces = card.get("card_faces") or []
    values = [str(face[name]) for face in faces if isinstance(face, dict) and face.get(name)]
    return " // ".join(values) or None


def normalize(card: dict[str, object], captured_at: str) -> dict[str, object]:
    set_code = str(card["set"]).upper()
    expected_name, expected_year = SETS[set_code]
    released_at = str(card["released_at"])
    if str(card["set_name"]) != expected_name or int(released_at[:4]) != expected_year:
        raise RuntimeError(f"unexpected set metadata for {set_code} {card['name']}")
    prices = card.get("prices") or {}
    usd = prices.get("usd") if isinstance(prices, dict) else None
    if usd is None:
        raise RuntimeError(f"selected card lacks a USD price: {card['name']}")
    collector_number = str(card["collector_number"])
    type_line = str(card["type_line"])
    type_parts = type_line.replace("—", "-").split("-", 1)
    card_types = type_parts[0].strip().split()
    subtypes = type_parts[1].strip().split() if len(type_parts) == 2 else []
    return {
        "id": f"{set_code.lower()}-{collector_number.lower()}",
        "name": str(card["name"]),
        "set_name": expected_name,
        "set_code": set_code,
        "collector_number": collector_number,
        "release_year": expected_year,
        "released_at": released_at,
        "rarity": str(card["rarity"]),
        "mana_cost": text_field(card, "mana_cost"),
        "mana_value": float(card["cmc"]),
        "colors": list(card.get("colors") or []),
        "color_identity": list(card.get("color_identity") or []),
        "type_line": type_line,
        "types": card_types,
        "subtypes": subtypes,
        "oracle_text": text_field(card, "oracle_text"),
        "power": text_field(card, "power"),
        "toughness": text_field(card, "toughness"),
        "loyalty": text_field(card, "loyalty"),
        "price": {
            "amount": str(usd),
            "currency": "USD",
            "basis": "Scryfall nonfoil USD market snapshot",
            "condition": "illustrative market value; condition not specified",
            "source": "Scryfall API",
            "source_url": str(card["scryfall_uri"]),
            "captured_at": captured_at,
        },
        "source_id": str(card["id"]),
        "reference_url": str(card["scryfall_uri"]),
        "popularity_basis": "Scryfall EDHREC ascending rank at snapshot time",
    }


def main() -> None:
    captured_at = datetime.now(UTC).date().isoformat()
    records: list[dict[str, object]] = []
    for index, set_code in enumerate(SETS):
        if index:
            time.sleep(0.15)
        records.extend(normalize(card, captured_at) for card in fetch_set(set_code))
    serialized = json.dumps(records, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(serialized, encoding="utf-8")
    checksum = hashlib.sha256(serialized.encode()).hexdigest()
    manifest = {
        "schema_version": "1.0.0",
        "record_count": len(records),
        "records_per_set": 20,
        "set_codes": list(SETS),
        "captured_at": captured_at,
        "selection": "first 20 priced paper printings ordered by Scryfall EDHREC rank",
        "source": "Scryfall API",
        "source_url": "https://scryfall.com/docs/api",
        "sha256": checksum,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(records)} records sha256={checksum}")


if __name__ == "__main__":
    main()
