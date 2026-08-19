# MTG catalog data provenance

`catalog-v1.json` is a static demonstration snapshot derived from the Scryfall API. It contains exactly 20 English paper printings with a non-null USD price from each required set, selected by ascending Scryfall EDHREC rank at refresh time. No card images are included.

The snapshot is intentionally not a live price service. Prices are illustrative Scryfall nonfoil USD market snapshots captured on the date in `manifest.json`; they do not specify physical condition and are not purchasing advice or guaranteed valuations.

Scryfall provides the source metadata and asks API clients to use a descriptive `User-Agent`, an `Accept` header, HTTPS, and fewer than ten requests per second. The refresh script makes five sequential requests with a delay. Source documentation: <https://scryfall.com/docs/api>. API usage guidance: <https://scryfall.com/docs/faqs/i-m-having-trouble-accessing-the-scryfall-api-or-i-m-blocked-17>.

Magic: The Gathering card names, rules text, set names, symbols, and trademarks are property of Wizards of the Coast. This repository is an unofficial local technical demonstration and is not endorsed by Wizards of the Coast or Scryfall. The snapshot contains factual/card text data and source links but no artwork. Review data and trademark terms again before redistribution beyond this demo.

## Refresh

From the repository root, with internet access:

```bash
python services/mtg-catalog-mcp/scripts/refresh_catalog.py
```

Review the diff for exactly 100 records, 20 per set, expected years/set names, non-null price metadata, and no image fields. Run the catalog tests; they recompute the checksum and validate the manifest. Commit a refresh as an explicit dataset version change rather than silently changing the snapshot.
