from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple
import urllib.parse
import urllib.request

from ..output import atomic_write_bytes


def fetch_artwork_from_itunes_search(
    data: Dict[str, Any],
    runtime_dir: Path,
    country: str,
) -> Tuple[str, str]:
    title = data.get("title") or ""
    artist = data.get("artist") or ""
    if not title and not artist:
        return "", "itunes:no_search_terms"

    params = {
        "term": f"{artist} {title}".strip(),
        "country": country,
        "media": "music",
        "entity": "song",
        "limit": "1",
    }
    search_url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(search_url, timeout=5) as res:
            payload = json.loads(res.read().decode("utf-8"))

        results = payload.get("results") or []
        if not results:
            return "", "itunes:no_results"

        artwork_url = results[0].get("artworkUrl100")
        if not artwork_url:
            return "", "itunes:no_artwork_url"

        large_url = (
            artwork_url.replace("100x100bb", "600x600bb")
            .replace("100x100-75", "600x600-75")
            .replace("100x100", "600x600")
        )

        try:
            with urllib.request.urlopen(large_url, timeout=5) as img_res:
                image = img_res.read()
        except Exception:
            with urllib.request.urlopen(artwork_url, timeout=5) as img_res:
                image = img_res.read()

        out = runtime_dir / "cover_fallback.jpg"
        atomic_write_bytes(out, image)
        return out.name, ""
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return "", f"itunes:{detail}"
