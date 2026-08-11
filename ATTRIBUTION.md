# Attribution and data terms

## Scryfall

Card data comes from [Scryfall bulk data](https://scryfall.com/docs/api/bulk-data).
It is free and requires no API key, but it is **not** public domain.

- Use the daily bulk exports, not the API, for anything at volume. Scryfall asks
  for this explicitly; `manalab.cards.bulk` only ever touches two URLs.
- Requests identify themselves via a `User-Agent` header, as Scryfall requires.
- `data/` is gitignored. Do not redistribute the bulk files; point people at
  `manalab fetch` instead.

## Wizards of the Coast

manalab is unofficial Fan Content permitted under the
[Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy).
Not approved or endorsed by Wizards. Portions of the materials used are property
of Wizards of the Coast LLC. Magic: The Gathering is a trademark of Wizards of
the Coast.

## Planned sources

- **MTGJSON** (MIT) — relational/Parquet exports, for joins Scryfall can't do.
- **17Lands public datasets** (CC BY 4.0) — real Limited game outcomes, the only
  ground truth available for validating search results. Attribution required.
- **Moxfield** — explicitly forbids scraping. Access is granted by request to
  support@moxfield.com with a custom User-Agent. Ask; do not scrape.
