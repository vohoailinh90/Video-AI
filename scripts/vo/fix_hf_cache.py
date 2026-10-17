"""Replace the symlinks in the Hugging Face cache snapshots with real file copies.

ONNX Runtime 1.31 refuses external-data files whose resolved path leaves the model directory ("External data path escapes
model directory"), and the Hugging Face cache stores every file as a symlink into blobs/. VieNeu-TTS hits this when it loads
its ONNX graphs. Copying the content in place keeps the path inside the directory.

usage: python -I scripts/vo/fix_hf_cache.py [hub-dir]
       hub-dir defaults to $HF_HOME/hub, or ~/.cache/huggingface/hub
Run it after the first download, then use HF_HUB_OFFLINE=1 so the library does not recreate the links.
"""
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(sys.argv) > 1:
        hub = Path(sys.argv[1])
    else:
        hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    if not hub.is_dir():
        print(f"no such directory: {hub}", file=sys.stderr)
        return 1
    replaced = 0
    for link in sorted(hub.glob("models--*/snapshots/**/*")):
        if not link.is_symlink():
            continue
        tmp = link.with_name(link.name + ".tmp-copy")
        shutil.copyfile(link, tmp)  # copies the content the link points to
        os.replace(tmp, link)       # swaps the link itself for the real file
        replaced += 1
    print(f"{hub}: replaced {replaced} symlinks with real files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
