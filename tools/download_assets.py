"""Download the pretrained assets RVC inference needs.

Run with the RVC venv:
    .venv-rvc\\Scripts\\python.exe tools\\download_assets.py

Downloads:
  * ContentVec embedder  (~360 MB)  -> programs/rvc/models/embedders/contentvec
  * RMVPE pitch model     (~173 MB)  -> programs/rvc/models/predictors/rmvpe.pt
  * FCPE pitch model       (~41 MB)  -> programs/rvc/models/predictors/fcpe.pt
  * CMU pronouncing dict    (~3 MB)  -> assets/cmudict.dict
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]

ASSETS = {
    str(ROOT / "programs/rvc/models/embedders/contentvec/pytorch_model.bin"):
        "https://huggingface.co/IAHispano/Applio/resolve/main/Resources/embedders/contentvec/pytorch_model.bin",
    str(ROOT / "programs/rvc/models/embedders/contentvec/config.json"):
        "https://huggingface.co/IAHispano/Applio/resolve/main/Resources/embedders/contentvec/config.json",
    str(ROOT / "programs/rvc/models/predictors/rmvpe.pt"):
        "https://huggingface.co/IAHispano/Applio/resolve/main/Resources/predictors/rmvpe.pt",
    str(ROOT / "programs/rvc/models/predictors/fcpe.pt"):
        "https://huggingface.co/IAHispano/Applio/resolve/main/Resources/predictors/fcpe.pt",
}

MIN_SIZES = {
    "pytorch_model.bin": 100_000_000,
    "rmvpe.pt": 100_000_000,
    "fcpe.pt": 10_000_000,
    "config.json": 100,
}

CHUNK = 1024 * 512


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def download(name: str, url: str) -> None:
    dest = Path(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    minimum = MIN_SIZES.get(dest.name, 1024)
    if dest.is_file() and dest.stat().st_size >= minimum:
        print(f"  ok      {dest.relative_to(ROOT)} ({human(dest.stat().st_size)})")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  get     {dest.relative_to(ROOT)}")
    with requests.get(url, stream=True, timeout=120) as res:
        res.raise_for_status()
        total = int(res.headers.get("content-length") or 0)
        done = 0
        last = -1
        with open(tmp, "wb") as fh:
            for chunk in res.iter_content(CHUNK):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = int(done * 100 / total)
                    if pct != last and pct % 2 == 0:
                        print(f"\r          {pct:3d}%  {human(done)} / {human(total)}", end="", flush=True)
                        last = pct
    print()
    if tmp.stat().st_size < minimum:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download looks truncated: {dest.name} ({tmp.stat().st_size} bytes)")
    os.replace(tmp, dest)
    print(f"  saved   {dest.relative_to(ROOT)} ({human(dest.stat().st_size)})")


def download_cmudict() -> None:
    dest = ROOT / "assets" / "cmudict.dict"
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        print(f"  ok      assets/cmudict.dict")
        return
    print("  get     assets/cmudict.dict (PyPI: cmudict)")
    try:
        meta = requests.get("https://pypi.org/pypi/cmudict/json", timeout=60).json()
        urls = meta["urls"]
        wheel = next((u for u in urls if u["filename"].endswith(".whl")), None)
        if not wheel:
            raise RuntimeError("no wheel published")
        blob = requests.get(wheel["url"], timeout=120).content
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            candidates = [n for n in zf.namelist() if n.endswith("cmudict.dict")]
            if not candidates:
                raise RuntimeError("cmudict.dict not found inside wheel")
            data = zf.read(candidates[0])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  saved   assets/cmudict.dict ({human(len(data))})")
    except Exception as exc:  # noqa: BLE001
        print(f"  warn    could not fetch cmudict ({exc}); rule-based G2P will be used")


def main() -> int:
    print("Downloading RVC assets into", ROOT)
    ok = 0
    for name, url in ASSETS.items():
        try:
            download(name, url)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED  {name}: {exc}")
    download_cmudict()
    print(f"\nDone. {ok}/{len(ASSETS)} RVC assets ready.")
    print("Next: python app/server.py")
    return 0 if ok == len(ASSETS) else 1


if __name__ == "__main__":
    sys.exit(main())
