# Skyhook Scout

Native Python desktop tool for EVE Online skyhook raiding. Direct public APIs; no login, application server or API key. Open-source software under the MIT license.

* Current/upcoming skyhook theft windows, live countdowns and sortable targets.
* Separate system, planet, planet type and region columns.
* Region, planet and planet-type filters plus text search.
* System-local time by default, with a saved EVE/UTC display option.
* Click-to-route from Thera, Turnur or any named system, using EVE Scout's reported wormholes.
* Sort targets by total jumps from the selected departure using the Jumps column after Time Left.
* Separate gate/wormhole counts, signatures, reported size/expiry and configurable raid estimates.
* Background fetching, persistent caching, five-minute refreshes and stale-data warnings.
* Compact windows use full-width Targets/Route tabs; route details scroll instead of overlapping.

## Download / run

From releases 

For running from source and compiling portable Windows or Linux applications, see **[BUILD.md](BUILD.md)**.

## Data and limitations

Official ESI: `https://esi.evetech.net/skyhooks/raidable`, universe metadata and `POST /route/{origin}/{destination}`. Compatibility date: `2026-11-01`. Community wormhole reports: `https://api.eve-scout.com/v2/public/signatures` (EVE Scout / Signal Cartel).

Only completed, unexpired connections to known space are used. Unreported chains and private bridges are excluded. Reported ship size and expiry do not guarantee remaining mass or ship eligibility. Shortest routes may cross hostile space. Published theft windows do not reveal available loot or enemy stock. Timing estimates are assumptions.

Cache headers and rate-limit cooldowns are respected. Failed feeds may use clearly labelled cached data; routes refuse Scout snapshots over 15 minutes old. Cache/settings use standard Qt OS locations. No account tokens or telemetry are collected.

## License

MIT license. See `LICENSE` and `THIRD_PARTY_NOTICES.md` for license details and third-party notices.
