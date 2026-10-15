"""Submit and collect one Gamma Earth job over the REST API (Task 24).

    python scripts/s2dr4_api.py --aoi "136.035105 -1.138913 136.044089 -1.129864" \
                                --date 2026-08-28 --label probe
    python scripts/s2dr4_api.py ... --submit          # actually spends the balance
    python scripts/s2dr4_api.py --job <job_id>        # poll and download a job already sent

**This runs on this laptop, not in Colab.** The wheel needed Colab for its CUDA
GPU; the API does the processing on Gamma Earth's side, so all this does is two
HTTP calls and a download. Standard library only.

**Without --submit nothing is sent and nothing is billed.** The default prints
the AOI area and what the request would be, which is the only safe default for a
call that spends a paid balance.

The key comes from GE_API_KEY in the environment or .env, never from a tracked
file. This API carries the key in the URL path, so no URL is ever printed: every
message masks it. A printed request URL here is a leaked credential.

Every response is written under data/raw/s2dr4_api/ before it is parsed
(AGENTS always-2). A failed request exits non-zero and says which call failed;
it is never reported as an empty result (never-2).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/s2dr4_api"
BASE = "https://api.gamma.earth/jobs"
# Region C, where Biak falls: 1 credit per 2 km2. The dashboard shows the
# balance as area, so the area is what this script reports.
KM2_PER_CREDIT = 2.0
AOI_MAX_KM2 = 150.0
POLL_SECONDS = 30
POLL_LIMIT = 120          # an hour, then give up and say so rather than hang


def load_env_file(path: Path = ROOT / ".env") -> None:
    """Populate os.environ from .env, a real environment variable winning.

    The same eight lines as src/ingest_firms.load_env_file. Importing that one
    pulls in the whole FIRMS ingest module and its dependencies, and this script
    is two HTTP calls: it broke on `ModuleNotFoundError: No module named
    'recurrence'` before a single request went out.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def mask(text: str, key: str) -> str:
    """Anything printed goes through this. The key lives in the URL path."""
    return text.replace(key, "<GE_API_KEY>") if key else text


def aoi_km2(aoi: str) -> tuple[float, float, float]:
    """(area, width_km, height_km) for a 'minx miny maxx maxy' box in degrees."""
    try:
        minx, miny, maxx, maxy = (float(v) for v in aoi.split())
    except ValueError:
        raise SystemExit('--aoi must be four numbers: "minx miny maxx maxy"')
    if minx >= maxx or miny >= maxy:
        raise SystemExit(f"--aoi is not a box with positive extent: {aoi}")
    mid = math.radians((miny + maxy) / 2)
    w = (maxx - minx) * 111.320 * math.cos(mid)
    h = (maxy - miny) * 110.574
    return w * h, w, h


def call(url: str, key: str, timeout: int = 120) -> tuple[int, str]:
    """(status, body). A transport failure is an exception, never an empty body."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise SystemExit(f"could not reach the API: {e.reason}")


def persist(name: str, body: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW / f"{stamp}_{name}.json"
    path.write_text(body, encoding="utf-8")
    return path


def parsed(body: str, path: Path) -> dict:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise SystemExit(f"the API did not return JSON. The response is at {path}")


def submit(key: str, args) -> dict:
    params = {"aoi": args.aoi, "date": args.date}
    for name in ("date_range", "max_clouds", "bands_out"):
        if getattr(args, name) is not None:
            params[name] = str(getattr(args, name))
    if args.cogs:
        params["cogs"] = "true"
    url = f"{BASE}/{key}?{urllib.parse.urlencode(params)}"
    print("POST", mask(url, key))
    status, body = call(url, key)
    path = persist(f"submit_{args.label}", body)
    print(f"  status {status}, response saved to {path.relative_to(ROOT)}")
    if status >= 400:
        raise SystemExit(f"the submission failed with status {status}. "
                         f"The response is at {path}, and nothing was downloaded.")
    return parsed(body, path)


def poll(key: str, job_id: str, label: str) -> dict:
    url = f"{BASE}/{key}/{urllib.parse.quote(job_id)}"
    for attempt in range(POLL_LIMIT):
        status, body = call(url, key)
        if status >= 400:
            path = persist(f"poll_{label}", body)
            raise SystemExit(f"polling failed with status {status}; response at {path}")
        state = parsed(body, persist(f"poll_{label}", body)).get("state", "unknown")
        print(f"  [{attempt * POLL_SECONDS // 60:3d} min] state {state}")
        if state in ("completed", "failed", "error"):
            if state != "completed":
                raise SystemExit(f"the job finished in state {state!r}, so there is "
                                 f"nothing to download and nothing to compare")
            return parsed(body, persist(f"final_{label}", body))
        time.sleep(POLL_SECONDS)
    raise SystemExit(f"the job was still running after "
                     f"{POLL_LIMIT * POLL_SECONDS // 60} minutes. It may finish later: "
                     f"re-run with --job {job_id}")


def download(urls: list[str], out: Path, key: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    got = []
    for url in urls:
        name = url.rstrip("/").split("/")[-1] or "download"
        dest = out / name
        print(f"  {name} ...", end=" ", flush=True)
        try:
            with urllib.request.urlopen(url, timeout=600) as r, dest.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"FAILED ({e})")
            print(f"    the path is in the saved response; fetch it by hand into {out}")
            continue
        print(f"{dest.stat().st_size / 1e6:.1f} MB")
        got.append(dest)
    return got


def product_urls(job: dict) -> list[str]:
    """The MS file is the one the comparison needs; take whatever paths the
    response actually carries rather than assuming a naming scheme."""
    base = job.get("save_path_S3_TCI") or ""
    pid = job.get("pid") or ""
    urls = [v for k, v in job.items()
            if isinstance(v, str) and v.startswith("http") and v.endswith(".tif")]
    if base.startswith("http") and pid:
        root = base.rsplit("/", 1)[0]
        for prefix in ("S2L2Ax10", "S2L3Ax10"):
            urls.append(f"{root}/{prefix}_{pid}_MS.tif")
    return list(dict.fromkeys(urls))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", help='"minx miny maxx maxy" in degrees')
    ap.add_argument("--date", help="exact Sentinel-2 scene date, YYYY-MM-DD")
    ap.add_argument("--label", default="job", help="name for the saved response files")
    ap.add_argument("--date_range", type=int, default=None,
                    help="days back to search; without it the date must exist exactly")
    ap.add_argument("--max_clouds", type=int, default=None)
    ap.add_argument("--bands_out", default=None, help="bands in Sentinel-2 names")
    ap.add_argument("--cogs", action="store_true", help="also produce TCI/NDVI/IRP COGs")
    ap.add_argument("--job", default=None, help="poll an existing job id instead of submitting")
    ap.add_argument("--submit", action="store_true",
                    help="actually send the job. Without it nothing is spent")
    ap.add_argument("--out", type=Path, default=None,
                    help="download directory (default data/raw/s2dr4_api/<label>)")
    args = ap.parse_args()

    load_env_file()
    key = os.environ.get("GE_API_KEY", "").strip()
    out = args.out or (RAW / args.label)

    if args.job:
        if not key:
            raise SystemExit("GE_API_KEY is not set; put it in .env (see .env.example)")
        print(f"polling job {args.job}")
        job = poll(key, args.job, args.label)
        urls = product_urls(job)
        print(f"\n{len(urls)} product paths in the response")
        got = download(urls, out, key) if urls else []
        print(f"\n{len(got)} files in {out.relative_to(ROOT)}")
        return 0 if got else 1

    if not args.aoi or not args.date:
        raise SystemExit("--aoi and --date are both required (or --job to poll)")
    area, w, h = aoi_km2(args.aoi)
    if area > AOI_MAX_KM2:
        raise SystemExit(f"the AOI is {area:.1f} km2 and the documented maximum is "
                         f"{AOI_MAX_KM2:.0f} km2")
    print(f"AOI {args.aoi}")
    print(f"  {w:.3f} x {h:.3f} km = {area:.2f} km2, about "
          f"{area / KM2_PER_CREDIT:.2f} credits at Region C")
    print(f"  date {args.date}" + ("" if args.date_range is None else
                                   f", searching back {args.date_range} days"))

    if not args.submit:
        print("\nnothing sent. Re-run with --submit to spend "
              f"{area:.2f} km2 of the balance.")
        return 0

    if not key:
        raise SystemExit("GE_API_KEY is not set; put it in .env (see .env.example)")
    job = submit(key, args)
    job_id = job.get("job_id")
    print(json.dumps({k: v for k, v in job.items() if "path" not in k.lower()},
                     indent=1, sort_keys=True)[:1200])
    if not job_id:
        raise SystemExit("the response carried no job_id, so there is nothing to poll. "
                         "The full response is in data/raw/s2dr4_api/.")
    print(f"\njob {job_id}, polling every {POLL_SECONDS}s")
    job = {**job, **poll(key, job_id, args.label)}
    urls = product_urls(job)
    print(f"\n{len(urls)} product paths in the response")
    got = download(urls, out, key) if urls else []
    print(f"\n{len(got)} files in {out.relative_to(ROOT)}")
    if got:
        print("\nnext, with the wheel tile that covers the same ground:")
        print("  python scripts/s2dr4_compare.py \\")
        print("    data/raw/s2dr4_biak_2026-08-28/output/ID/T53MPU/"
              "T53MPU-0c59f172e/S2L3Ax10_T53MPU-0c59f172e-20260828_MS.tif \\")
        print(f"    {out.relative_to(ROOT)}/<the MS file> "
              "--json data/processed/s2dr4_route_compare.json")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
