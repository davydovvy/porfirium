from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

SERVER_NAME = "demo-mtg-catalog-mcp"
SERVER_VERSION = "1.0.0"
MAX_SEARCH_LIMIT = 20
MAX_COMPARE_CARDS = 5
DATA_DIR = Path(__file__).with_name("data")


def _load_catalog() -> tuple[list[dict[str, object]], dict[str, object]]:
    data_bytes = (DATA_DIR / "catalog-v1.json").read_bytes()
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(data_bytes).hexdigest() != manifest["sha256"]:
        raise RuntimeError("catalog checksum does not match manifest")
    cards = json.loads(data_bytes)
    if len(cards) != manifest["record_count"]:
        raise RuntimeError("catalog record count does not match manifest")
    return cards, manifest


CARDS, MANIFEST = _load_catalog()
BY_ID = {str(card["id"]): card for card in CARDS}
VALID_COLORS = frozenset("WUBRG")
VALID_RARITIES = frozenset({"common", "uncommon", "rare", "mythic"})

mcp = FastMCP(
    "Porfirium Demo MTG Catalog",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "demo-mtg-catalog-mcp:8093",
            "demo-mtg-catalog-mcp",
            "127.0.0.1:8093",
            "127.0.0.1:8089",
            "127.0.0.1",
            "agentgateway-spike:8090",
            "localhost:8093",
            "localhost",
        ]
    ),
)


def _bounded_text(value: str | None, field: str, maximum: int = 200) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized or None


def _price(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal amount") from exc
    if result < 0 or result > Decimal("1000000"):
        raise ValueError(f"{field} is outside the supported range")
    return result


def _summary(card: dict[str, object]) -> dict[str, object]:
    return {
        "id": card["id"],
        "name": card["name"],
        "set_code": card["set_code"],
        "collector_number": card["collector_number"],
        "rarity": card["rarity"],
        "mana_cost": card["mana_cost"],
        "mana_value": card["mana_value"],
        "colors": card["colors"],
        "type_line": card["type_line"],
        "price": card["price"],
    }


def search_catalog(
    query: str,
    set_code: str | None = None,
    colors: list[str] | None = None,
    card_type: str | None = None,
    rarity: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    limit: int = 10,
) -> dict[str, object]:
    needle = (_bounded_text(query, "query") or "").casefold()
    normalized_set = (_bounded_text(set_code, "set_code", 8) or "").upper()
    normalized_type = (_bounded_text(card_type, "card_type", 64) or "").casefold()
    normalized_rarity = (_bounded_text(rarity, "rarity", 16) or "").casefold()
    if normalized_rarity and normalized_rarity not in VALID_RARITIES:
        raise ValueError("rarity must be common, uncommon, rare, or mythic")
    normalized_colors = {color.upper() for color in (colors or [])}
    if not normalized_colors <= VALID_COLORS:
        raise ValueError("colors may contain only W, U, B, R, and G")
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    minimum = _price(min_price, "min_price")
    maximum = _price(max_price, "max_price")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("min_price cannot exceed max_price")

    matches: list[dict[str, object]] = []
    for card in CARDS:
        searchable = " ".join(
            str(card.get(field) or "") for field in ("name", "type_line", "oracle_text")
        ).casefold()
        amount = Decimal(str(card["price"]["amount"]))  # type: ignore[index]
        if needle and needle not in searchable:
            continue
        if normalized_set and card["set_code"] != normalized_set:
            continue
        if normalized_colors and not normalized_colors <= set(card["color_identity"]):
            continue
        if normalized_type and normalized_type not in str(card["type_line"]).casefold():
            continue
        if normalized_rarity and card["rarity"] != normalized_rarity:
            continue
        if minimum is not None and amount < minimum:
            continue
        if maximum is not None and amount > maximum:
            continue
        matches.append(_summary(card))
    return {
        "cards": matches[:limit],
        "returned": min(len(matches), limit),
        "total_matches": len(matches),
        "catalog_version": MANIFEST["schema_version"],
        "price_snapshot_date": MANIFEST["captured_at"],
    }


def card_detail(card_id: str) -> dict[str, object]:
    normalized = _bounded_text(card_id, "card_id", 64)
    card = BY_ID.get(normalized or "")
    if card is None:
        raise ValueError("card_id was not found in the catalog")
    return dict(card)


def compare_catalog_cards(card_ids: list[str]) -> dict[str, object]:
    if not 2 <= len(card_ids) <= MAX_COMPARE_CARDS:
        raise ValueError(f"card_ids must contain between 2 and {MAX_COMPARE_CARDS} IDs")
    if len(set(card_ids)) != len(card_ids):
        raise ValueError("card_ids must not contain duplicates")
    cards = [card_detail(card_id) for card_id in card_ids]
    return {
        "cards": cards,
        "comparison_fields": [
            "mana_value",
            "colors",
            "type_line",
            "oracle_text",
            "power",
            "toughness",
            "loyalty",
            "price",
        ],
        "catalog_version": MANIFEST["schema_version"],
        "price_disclaimer": "Static illustrative snapshots, not live quotes or purchasing advice.",
    }


def catalog_sets() -> dict[str, object]:
    sets: list[dict[str, object]] = []
    for code in MANIFEST["set_codes"]:
        cards = [card for card in CARDS if card["set_code"] == code]
        sets.append(
            {
                "set_code": code,
                "set_name": cards[0]["set_name"],
                "release_year": cards[0]["release_year"],
                "card_count": len(cards),
            }
        )
    return {"sets": sets, "catalog_version": MANIFEST["schema_version"]}


@mcp.tool()
def search_cards(
    query: str,
    set_code: str | None = None,
    colors: list[str] | None = None,
    card_type: str | None = None,
    rarity: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    limit: int = 10,
) -> dict[str, object]:
    """Search the bounded static MTG catalog using optional structured filters."""
    return search_catalog(
        query, set_code, colors, card_type, rarity, min_price, max_price, limit
    )


@mcp.tool()
def get_card(card_id: str) -> dict[str, object]:
    """Return full details for one stable catalog card ID."""
    return card_detail(card_id)


@mcp.tool()
def compare_cards(card_ids: list[str]) -> dict[str, object]:
    """Return two to five catalog cards with consistent comparison fields."""
    return compare_catalog_cards(card_ids)


@mcp.tool()
def list_sets() -> dict[str, object]:
    """List the five sets represented in the static catalog."""
    return catalog_sets()


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "component": SERVER_NAME,
            "version": SERVER_VERSION,
            "read_only": True,
            "catalog_version": MANIFEST["schema_version"],
            "card_count": len(CARDS),
            "tools": ["search_cards", "get_card", "compare_cards", "list_sets"],
        }
    )


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


application = Starlette(
    routes=[Route("/health", health), Mount("/mcp", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(application, host="0.0.0.0", port=8093)
