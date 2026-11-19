"""RVC inference worker — executed by the .venv-rvc interpreter, not the app.

Usage:  python rvc_worker.py <config.json>
"""

from __future__ import annotations

import json
import os
import sys
import traceback


def log(*args):
    print("[rvc]", *args, flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        log("missing config path")
        return 2
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    root = cfg["root"]
    os.chdir(root)
    sys.path.insert(0, root)

    log("loading RVC inference stack")
    import torch

    # Torch >= 2.6 defaults torch.load to weights_only=True, which rejects the
    # pickled metadata inside many RVC checkpoints. Models here are local files
    # the user installed themselves, so restore the pre-2.6 behaviour.
    _torch_load = torch.load

    def _load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return _torch_load(*args, **kwargs)

    torch.load = _load

    from programs.rvc.infer.infer import VoiceConverter

    vc = VoiceConverter()
    log("stack ready")

    if cfg.get("index") and not os.path.isfile(cfg["index"]):
        log(f"index not found, ignoring: {cfg['index']}")
        cfg["index"] = ""

    try:
        vc.convert_audio(
            audio_input_path=cfg["input"],
            audio_output_path=cfg["output"],
            model_path=cfg["model"],
            index_path=cfg.get("index", ""),
            embedder_model="contentvec",
            pitch=int(cfg.get("pitch", 0)),
            f0_file=None,
            f0_method=cfg.get("f0_method", "rmvpe"),
            index_rate=float(cfg.get("index_rate", 0.75)),
            volume_envelope=float(cfg.get("volume_envelope", 0.9)),
            protect=float(cfg.get("protect", 0.33)),
            hop_length=64,
            split_audio=False,
            f0_autotune=False,
            filter_radius=3,
            embedder_model_custom="",
            export_format=cfg.get("export_format", "WAV"),
            resample_sr=0,
            sid=int(cfg.get("sid", 0)),
        )
    except Exception:
        log("conversion raised:")
        log(traceback.format_exc())
        return 1

    if not os.path.isfile(cfg["output"]):
        log("no output file was written")
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
