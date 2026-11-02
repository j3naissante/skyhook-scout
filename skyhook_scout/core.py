"""Pure routing, filtering and timer calculations; no GUI or network dependencies."""
from datetime import datetime, timezone
import time

HUBS = {"Thera": 31000005, "Turnur": 30002086}
SIZES = {"small": 1, "medium": 2, "large": 3, "xlarge": 4, "capital": 5}


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%H:%M UTC")


def display_time(value, system_time=True, include_zone=True):
    moment = datetime.fromtimestamp(value, timezone.utc)
    if system_time:
        moment = moment.astimezone()
    text = moment.strftime("%H:%M")
    return text + " " + time_zone_label(system_time, moment) if include_zone else text


def time_zone_label(system_time=True, moment=None):
    if not system_time:
        return "UTC"
    moment = moment or datetime.now().astimezone()
    offset = moment.strftime("%z")
    return "UTC" if offset in ("+0000", "-0000", "") else "UTC" + offset[:3] + ":" + offset[3:]


def duration(seconds):
    minutes = max(0, int((seconds + 59) // 60))
    return f"{minutes // 60}h {minutes % 60:02}m" if minutes >= 60 else f"{minutes}m"


def status(hook, now=None):
    now = time.time() if now is None else now
    window = hook["theft_vulnerability"]
    if now < timestamp(window["start"]):
        return "Upcoming"
    return "Open now" if now < timestamp(window["end"]) else "Expired"


def active_connections(holes, size=0, now=None):
    now = time.time() if now is None else now
    result = []
    for h in holes:
        try:
            if (h.get("completed") is True and h.get("signature_type") == "wormhole"
                    and timestamp(h["expires_at"]) > now
                    and int(h["out_system_id"]) in HUBS.values()
                    and 30000000 <= int(h["in_system_id"]) < 31000000
                    and (not size or SIZES.get(h.get("max_ship_size"), 0) >= size)):
                result.append(h)
        except (KeyError, TypeError, ValueError):
            continue
    return result


def connection_edges(holes):
    return [edge for h in holes for edge in (
        {"from": int(h["out_system_id"]), "to": int(h["in_system_id"])},
        {"from": int(h["in_system_id"]), "to": int(h["out_system_id"])})]


def describe_route(systems, holes):
    edges = {}
    for h in holes:
        a, b = int(h["out_system_id"]), int(h["in_system_id"])
        edges[a, b] = edges[b, a] = h
    hops = [{"from": a, "to": b, "hole": edges.get((a, b))}
            for a, b in zip(systems, systems[1:])]
    wormholes = sum(h["hole"] is not None for h in hops)
    return {"systems": systems, "hops": hops, "wormholes": wormholes,
            "gates": len(hops) - wormholes}


def estimate_raid(jumps, hook, seconds=45, raid=10, buffer=3, now=None):
    now = time.time() if now is None else now
    travel = jumps * max(1, seconds)
    finish = max(now + travel, timestamp(hook["theft_vulnerability"]["start"]))
    finish += (max(1, raid) + max(0, buffer)) * 60
    return travel, finish < timestamp(hook["theft_vulnerability"]["end"])


def matches(hook, query="", region="", planet_type="", window="All windows", now=None, planet=""):
    state = status(hook, now)
    if state == "Expired" or (window != "All windows" and state != window):
        return False
    if region and hook.get("region") != region:
        return False
    if planet_type and hook.get("planet_type") != planet_type:
        return False
    if planet and hook.get("planet") != planet:
        return False
    text = " ".join(str(hook.get(k, "")) for k in
                    ("system", "planet", "region", "planet_type", "solar_system_id", "planet_id"))
    return query.casefold() in text.casefold()
