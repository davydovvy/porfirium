import unittest

from server import (
    CARDS,
    MANIFEST,
    card_detail,
    catalog_sets,
    compare_catalog_cards,
    search_catalog,
)


class CatalogToolTests(unittest.TestCase):
    def test_dataset_has_required_shape(self) -> None:
        self.assertEqual(len(CARDS), 100)
        self.assertEqual(MANIFEST["record_count"], 100)
        counts = {item["set_code"]: item["card_count"] for item in catalog_sets()["sets"]}
        self.assertEqual(counts, {"M11": 20, "ISD": 20, "RTR": 20, "THS": 20, "KTK": 20})
        self.assertEqual(len({card["id"] for card in CARDS}), 100)
        self.assertTrue(all(card["price"]["amount"] for card in CARDS))

    def test_search_is_stable_and_bounded(self) -> None:
        result = search_catalog("", set_code="ISD", limit=3)
        self.assertEqual(result["returned"], 3)
        self.assertEqual(result["total_matches"], 20)
        self.assertEqual(
            [card["id"] for card in result["cards"]],
            [card["id"] for card in CARDS if card["set_code"] == "ISD"][:3],
        )

    def test_search_filters_type_color_rarity_and_price(self) -> None:
        result = search_catalog(
            "", colors=["G"], card_type="creature", rarity="rare", min_price="0.01"
        )
        self.assertGreater(result["total_matches"], 0)
        for card in result["cards"]:
            full = card_detail(card["id"])
            self.assertIn("G", full["color_identity"])
            self.assertIn("creature", full["type_line"].casefold())
            self.assertEqual(full["rarity"], "rare")

    def test_get_and_compare_cards(self) -> None:
        identifiers = [CARDS[0]["id"], CARDS[20]["id"]]
        self.assertEqual(card_detail(identifiers[0])["id"], identifiers[0])
        comparison = compare_catalog_cards(identifiers)
        self.assertEqual([card["id"] for card in comparison["cards"]], identifiers)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit"):
            search_catalog("", limit=21)
        with self.assertRaisesRegex(ValueError, "colors"):
            search_catalog("", colors=["X"])
        with self.assertRaisesRegex(ValueError, "min_price"):
            search_catalog("", min_price="10", max_price="1")
        with self.assertRaisesRegex(ValueError, "not found"):
            card_detail("unknown-card")
        with self.assertRaisesRegex(ValueError, "duplicates"):
            compare_catalog_cards([CARDS[0]["id"], CARDS[0]["id"]])


if __name__ == "__main__":
    unittest.main()
