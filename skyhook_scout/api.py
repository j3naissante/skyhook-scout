"""Public APIs only. Persistent cache, ETags, shared cooldowns and TLS verification."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

import requests

from .core import HUBS, active_connections, connection_edges, describe_route

ESI = "https://esi.evetech.net"
SCOUT = "https://api.eve-scout.com/v2/public/signatures"
COMPATIBILITY_DATE = "2026-11-01"


class ApiError(RuntimeError):
    pass


@dataclass
class Snapshot:
    data: object
    checked: float
    stale: bool = False
    error: str = ""


class Cache:
    def __init__(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "cache.sqlite3"
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS responses "
                         "(key TEXT PRIMARY KEY, body TEXT, checked REAL, expires REAL, etag TEXT)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, key):
        with self.connect() as conn:
            row = conn.execute("SELECT body, checked, expires, etag FROM responses WHERE key=?", (key,)).fetchone()
        return (json.loads(row[0]), *row[1:]) if row else None

    def put(self, key, data, checked, expires, etag=""):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?)",
                         (key, json.dumps(data), checked, expires, etag))


class Client:
    def __init__(self, cache_dir):
        self.cache = Cache(cache_dir)
        self.local = threading.local()
        self.guard = threading.Lock()
        self.key_locks = {}
        self.cooldowns = {}
        self.cancelled = threading.Event()

    def session(self):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
            self.local.session.headers.update({"User-Agent": "SkyhookScout/1.0 (public EVE desktop client)",
                                               "Accept": "application/json"})
        return self.local.session

    def request(self, path, body=None, ttl=300, allow_stale=False, scout=False):
        if self.cancelled.is_set():
            raise ApiError("Request cancelled because the app is closing.")
        url = SCOUT if scout else ESI + path
        key = url + ("#" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() if body is not None else "")
        with self.guard:
            lock = self.key_locks.setdefault(key, threading.Lock())
        with lock:
            cached = self.cache.get(key)
            now = time.time()
            if cached and cached[2] > now:
                return Snapshot(cached[0], cached[1])
            group = "scout" if scout else "esi"
            try:
                with self.guard:
                    cooldown = self.cooldowns.get(group, 0)
                if cooldown > now:
                    raise ApiError(f"API cooling down; retry in {int(cooldown - now) + 1}s.")
                headers = {"If-None-Match": cached[3]} if cached and cached[3] and body is None else {}
                response = self.session().request("POST" if body is not None else "GET", url,
                    params={} if scout else {"compatibility_date": COMPATIBILITY_DATE},
                    headers=headers, json=body, timeout=(8, 25))
                if response.status_code in (420, 429):
                    try:
                        delay = max(1, float(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        delay = 60
                    with self.guard:
                        self.cooldowns[group] = now + delay
                    raise ApiError(f"API rate limit reached. Retry in {int(delay)}s.")
                response.raise_for_status()
                match = re.search(r"(?:^|,)\s*max-age=(\d+)", response.headers.get("Cache-Control", ""))
                age = int(match.group(1)) if match else ttl
                # Route POSTs are locally cached for five minutes, never shared outside this app.
                age = ttl if body is not None else age
                if response.status_code == 304:
                    if not cached:
                        raise ApiError("Received 304 without a cached response.")
                    data = cached[0]
                else:
                    data = response.json()
                now = time.time()
                self.cache.put(key, data, now, now + age, response.headers.get("ETag", cached[3] if cached else ""))
                return Snapshot(data, now)
            except (requests.RequestException, ValueError, ApiError) as exc:
                if cached and allow_stale:
                    return Snapshot(cached[0], cached[1], True, str(exc))
                raise ApiError(str(exc)) from exc

    def universe(self, kind, item_id):
        return self.request(f"/universe/{kind}/{int(item_id)}/", ttl=86400 * 30).data

    def metadata(self, hook):
        planet = self.universe("planets", hook["planet_id"])
        system = self.universe("systems", hook["solar_system_id"])
        constellation = self.universe("constellations", system["constellation_id"])
        region = self.universe("regions", constellation["region_id"])
        kind = self.universe("types", planet["type_id"])
        return {"system": system["name"], "planet": planet["name"], "region": region["name"],
                "planet_type": kind["name"].removeprefix("Planet (").removesuffix(")"),
                "security": system.get("security_status", 0)}

    def refresh(self, progress=lambda *_: None):
        errors = []
        try:
            hooks = self.request("/skyhooks/raidable", allow_stale=True)
            rows = [dict(h) for h in hooks.data["skyhooks"]]
            if hooks.stale:
                errors.append("Skyhooks: cached data — " + hooks.error)
        except ApiError as exc:
            hooks, rows = Snapshot({}, 0), []
            errors.append("Skyhooks: " + str(exc))
        try:
            scout = self.request("", scout=True, allow_stale=True)
            if not isinstance(scout.data, list):
                raise ApiError("Unexpected EVE Scout response.")
            if scout.stale:
                errors.append("EVE Scout: cached data — " + scout.error)
        except ApiError as exc:
            scout = Snapshot([], 0)
            errors.append("EVE Scout: " + str(exc))
        progress({"rows": [dict(h) for h in rows], "hooks": hooks, "scout": scout,
                  "errors": list(errors), "complete": False}, "Loading location names…")
        failed = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self.metadata, h): h for h in rows}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    futures[future].update(future.result())
                except ApiError:
                    failed += 1
                if i % 15 == 0:
                    progress({"rows": [dict(h) for h in rows], "hooks": hooks, "scout": scout,
                              "errors": list(errors), "complete": False}, f"Location names {i}/{len(rows)}")
        if failed:
            errors.append(f"Location lookup failed for {failed} targets; refresh to retry.")
        return {"rows": rows, "hooks": hooks, "scout": scout, "errors": errors, "complete": True}

    def resolve_origin(self, origin):
        if isinstance(origin, str):
            if origin in HUBS:
                origin = HUBS[origin]
            elif origin.strip().isdigit():
                origin = int(origin.strip())
            else:
                result = self.request("/universe/ids/", [origin.strip()], ttl=86400).data
                if not result.get("systems"):
                    raise ApiError("Starting system not found. Enter a solar system name, e.g. Jita.")
                origin = result["systems"][0]["id"]
        return origin

    def route_systems(self, origin, destination, holes):
        if origin == destination:
            systems = [origin]
        else:
            systems = self.request(f"/route/{origin}/{destination}",
                {"preference": "Shorter", "connections": connection_edges(holes)}).data["route"]
        if not systems or systems[0] != origin or systems[-1] != destination:
            raise ApiError("No valid route returned for this target.")
        return systems

    def jump_counts(self, origin, destinations, scout, size=0, progress=lambda *_: None, cancelled=lambda: False):
        if not scout.checked or time.time() - scout.checked > 900:
            raise ApiError("EVE Scout data is unavailable or over 15 minutes old. Refresh intel first.")
        origin = self.resolve_origin(origin)
        holes = active_connections(scout.data, size)
        for destination in sorted(set(destinations)):
            if cancelled() or self.cancelled.is_set():
                return
            if time.time() - scout.checked > 900:
                raise ApiError("Scout intel expired during distance calculation. Refresh intel.")
            try:
                count = len(self.route_systems(origin, destination, holes)) - 1
            except ApiError as exc:
                progress((destination, None, str(exc)), "")
            else:
                progress((destination, count, ""), "")

    def plan(self, origin, destination, scout, size=0):
        if not scout.checked or time.time() - scout.checked > 900:
            raise ApiError("EVE Scout data is unavailable or over 15 minutes old. Refresh intel first.")
        origin = self.resolve_origin(origin)
        holes = active_connections(scout.data, size)
        systems = self.route_systems(origin, destination, holes)
        result = describe_route(systems, holes)
        names = {}
        for i in range(0, len(systems), 500):
            for item in self.request("/universe/names/", systems[i:i + 500], ttl=86400).data:
                names[item["id"]] = item["name"]
        result.update(names=names, origin=origin, checked=time.time())
        return result
