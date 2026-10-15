"""Which date to ask S2DR4 for, when you want a particular scene.

S2DR4 does not process the date you give it. Documented in the SDK release notes
for s2dr4-20261014, read 2026-10-15: it looks at the Sentinel-2 images of the
**180 days before the target date, and up to 3 days after it**, drops anything at
99% cloud or more, and takes **the most recent of the rest**.

So the date is a ceiling plus three days, not a request. Asking for 23 August
2026 over tile 53MPU returned 25 August, and asking for 20 August returned 23
August - both exactly what the rule predicts, and both recorded in the notebook
as unexplained before the rule was documented.

request_date() inverts it: given the scene you want and the dates the catalogue
holds, it returns the date to put on the command line. Nothing here is guessed
from the wheel's behaviour; it is the published rule, and demo() checks it
against the three runs that were actually observed.

scene_dates() lists what the catalogue holds, from the same Element84 STAC on
AWS that S2DR4 reads (`fetch_S2L2A_STAC_aoi`, `pystac_client`, `stackstac` are in
the compiled module). It needs no credential and spends no credits.

    python scripts/s2dr4_dates.py --aoi "136.019 -1.154 136.060 -1.115" \
                                  --from 2026-08-01 --to 2026-09-30
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

STAC = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
# The two halves of the window S2DR4 searches, from the SDK release notes.
LOOK_BACK = timedelta(days=180)
LOOK_AHEAD = timedelta(days=3)
# Scenes at or above this cloud fraction are not candidates, same source.
CLOUD_CEILING = 99.0


def scene_dates(aoi: str, start: str, end: str, timeout: int = 60) -> list[dict]:
    """Sentinel-2 L2A scenes over `aoi` between `start` and `end`, oldest first.

    `aoi` is "minx miny maxx maxy" in degrees, the same string S2DR4 takes.
    Returns one dict per scene: date, cloud, platform, id.
    """
    try:
        bbox = [float(v) for v in aoi.split()]
    except ValueError:
        raise SystemExit('--aoi must be four numbers: "minx miny maxx maxy"')
    if len(bbox) != 4:
        raise SystemExit('--aoi must be four numbers: "minx miny maxx maxy"')
    body = json.dumps({
        "collections": [COLLECTION],
        "bbox": bbox,
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 100,
    }).encode()
    req = urllib.request.Request(
        STAC, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"the STAC search failed with status {e.code}: "
                         f"{e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"could not reach the STAC catalogue: {e.reason}")

    out = []
    for f in payload.get("features", []):
        p = f.get("properties", {})
        out.append({
            "date": p.get("datetime", "")[:10],
            "cloud": p.get("eo:cloud_cover"),
            "platform": p.get("platform", ""),
            "id": f.get("id", ""),
        })
    out.sort(key=lambda s: s["date"])
    return out


def _candidates(dates: list[str], cutoff: date) -> list[date]:
    """The scene dates S2DR4 would consider for a request of `cutoff`."""
    lo, hi = cutoff - LOOK_BACK, cutoff + LOOK_AHEAD
    return sorted(d for d in (date.fromisoformat(s) for s in dates) if lo <= d <= hi)


def resolve(asked: str, dates: list[str]) -> str | None:
    """What S2DR4 returns when asked for `asked`: the most recent candidate."""
    found = _candidates(dates, date.fromisoformat(asked))
    return found[-1].isoformat() if found else None


def request_date(wanted: str, dates: list[str]) -> str:
    """The date to put on the command line to be given the `wanted` scene.

    Ask for the scene itself unless a later one falls inside the three-day
    look-ahead; in that case back off so the window closes the day before that
    later scene, which leaves `wanted` as the most recent candidate.
    """
    want = date.fromisoformat(wanted)
    if wanted not in dates:
        raise SystemExit(f"{wanted} is not a scene the catalogue holds. "
                         f"It has: {', '.join(dates) or '(nothing)'}")
    later = sorted(d for d in (date.fromisoformat(s) for s in dates)
                   if want < d <= want + LOOK_AHEAD)
    if not later:
        return wanted
    # The window must end the day before the next scene, and it ends 3 days
    # after the date asked for.
    return (later[0] - LOOK_AHEAD - timedelta(days=1)).isoformat()


def demo() -> None:
    """The rule against the three runs that were actually observed in Colab.

    Asking for 23 August 2026 returned 25; asking for 20 August returned 23;
    asking for 28 August returned 28. The documented rule reproduces all three.

    The scene list is the real one, read from the STAC catalogue on 2026-10-15
    for the E0313 tile. Note what is not in it: 20 August, the date the notebook
    asked for and was answered with 23 August. It was never a scene.
    """
    have = ["2026-08-03", "2026-08-08", "2026-08-13", "2026-08-18",
            "2026-08-23", "2026-08-25", "2026-08-28"]  # 5 Aug omitted: 99.4% cloud
    assert resolve("2026-08-23", have) == "2026-08-25", resolve("2026-08-23", have)
    assert resolve("2026-08-20", have) == "2026-08-23", resolve("2026-08-20", have)
    assert resolve("2026-08-28", have) == "2026-08-28", resolve("2026-08-28", have)

    # And the inverse: every scene reachable by asking for the computed date.
    for wanted in have:
        asked = request_date(wanted, have)
        assert resolve(asked, have) == wanted, (wanted, asked, resolve(asked, have))
    assert request_date("2026-08-28", have) == "2026-08-28"
    assert request_date("2026-08-23", have) == "2026-08-21"
    print("s2dr4 dates: ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True, help='"minx miny maxx maxy" in degrees')
    ap.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    scenes = scene_dates(args.aoi, args.start, args.end)
    if not scenes:
        print("the catalogue holds no scene over this box in that window")
        return 1
    # Only the scenes S2DR4 would consider are candidates, so the 99% ones must
    # be out of the list before a back-off is computed against them.
    usable = [s["date"] for s in scenes
              if s["cloud"] is None or s["cloud"] < CLOUD_CEILING]
    print(f"{len(scenes)} scenes over {args.aoi}")
    print("cloud is the whole Sentinel-2 tile, not this box: a high figure here "
          "does not mean the box is clouded\n")
    print(f"{'scene':12s} {'cloud %':>8s}  {'platform':12s} ask for")
    for s in scenes:
        cloud = "-" if s["cloud"] is None else f"{s['cloud']:.1f}"
        ask = request_date(s["date"], usable) if s["date"] in usable else "(99%+ cloud)"
        print(f"{s['date']:12s} {cloud:>8s}  {s['platform']:12s} {ask}")
    return 0


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        sys.exit(main())
