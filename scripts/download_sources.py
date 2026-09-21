"""Download the two user-approved public sources; never overwrite existing bytes."""
from pathlib import Path
import hashlib
import json
import sys
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy_import.models import ImportSpec

root = Path(__file__).resolve().parents[1]
for name in ("import_jrfu.json", "import_michibiku.json"):
    spec = ImportSpec.model_validate_json((root / "config" / name).read_text(encoding="utf-8"))
    target = (root / spec.source.file_path).resolve()
    if not target.is_relative_to(root / "data/policies/sources"):
        raise ValueError("configured download target is outside the sources directory")
    if target.exists():
        print("Kept existing source:", target.name)
        continue
    with requests.get(spec.source.url, timeout=(10, 30), stream=True) as response:
        response.raise_for_status()
        data = bytearray()
        for part in response.iter_content(65536):
            data.extend(part)
            if len(data) > 25 * 1024 * 1024:
                raise ValueError("source exceeds 25 MiB")
    if spec.source.type == "pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("download did not return PDF bytes")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)
    print(target.name, hashlib.sha256(data).hexdigest())
