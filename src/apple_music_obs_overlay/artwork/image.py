from __future__ import annotations

from pathlib import Path
from io import BytesIO
import subprocess
from typing import Tuple

from ..output import atomic_write_bytes

try:
    from PIL import Image, ImageCms, ImageOps
except ImportError:
    # Running straight from a clone without `pip install .` must keep working:
    # covers are then published at their original size and encoding.
    Image = ImageCms = ImageOps = None

PILLOW_AVAILABLE = Image is not None


# 104 CSS pixels at scale=3, with 2x sampling for crisp artwork.
MAX_ARTWORK_SIZE = 640


def normalize_artwork(data: bytes) -> bytes:
    """Bound static covers without lossy re-encoding; preserve animated originals."""
    if Image is None:
        return data
    with Image.open(BytesIO(data)) as image:
        if getattr(image, "is_animated", False):
            return data
        # Pillow's RGBA conversion clips 16-bit grayscale to 8-bit white. Keep
        # its original PNG encoding so the browser can display it correctly.
        if image.format == "PNG" and image.mode in ("I", "I;16", "I;16B", "I;16L"):
            return data
        # Preserve the browser's JPEG decoding (including chroma downsampling),
        # orientation and color profile when no size reduction is needed.
        if image.format == "JPEG" and max(image.size) <= MAX_ARTWORK_SIZE:
            return data
        image.seek(0)
        icc = image.info.get("icc_profile")
        image = ImageOps.exif_transpose(image)
        # PNG cannot carry CMYK/Lab pixels. Convert those through their profile;
        # RGB profiles (including Display P3) can be preserved without clipping.
        if icc and image.mode in ("CMYK", "LAB"):
            target = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            try:
                image = ImageCms.profileToProfile(
                    image, ImageCms.ImageCmsProfile(BytesIO(icc)), target, outputMode="RGB"
                )
                icc = target.tobytes()
            except (OSError, ValueError, ImageCms.PyCMSError):
                if image.mode != "CMYK":
                    raise
                image = image.convert("RGB")
                icc = None
        elif icc and image.mode in ("L", "LA"):
            # Keep grayscale pixels paired with their grayscale profile.
            if image.mode == "L" and "transparency" in image.info:
                image = image.convert("LA")
            image.thumbnail((MAX_ARTWORK_SIZE, MAX_ARTWORK_SIZE), Image.Resampling.LANCZOS)
            image.info.clear()
            out = BytesIO()
            image.save(out, "PNG", icc_profile=icc)
            return out.getvalue()
        rgba = image.convert("RGBA")
        rgba.thumbnail((MAX_ARTWORK_SIZE, MAX_ARTWORK_SIZE), Image.Resampling.LANCZOS)
        rgba.info.clear()
        out = BytesIO()
        rgba.save(out, "PNG", icc_profile=icc)
        return out.getvalue()


SUPPORTED_DIRECT_SUFFIXES = {".jpg", ".png", ".gif", ".webp"}


def detect_image_suffix(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"MM\x00*", b"II*\x00")):
        return ".tiff"
    return ""


def write_runtime_image(data: bytes, runtime_dir: Path, stem: str) -> Tuple[str, str]:
    if not data:
        return "", "empty_data"

    suffix = detect_image_suffix(data)
    if suffix in SUPPORTED_DIRECT_SUFFIXES:
        out = runtime_dir / f"{stem}{suffix}"
        atomic_write_bytes(out, data)
        return out.name, ""

    return "", f"unknown_image_format:first_bytes={data[:16].hex()}"


def convert_artwork_file(raw_path: Path, runtime_dir: Path, stem: str = "cover_direct") -> Tuple[str, str]:
    data = raw_path.read_bytes()
    if not data:
        raw_path.unlink(missing_ok=True)
        return "", "direct:empty_file"

    artwork_file, error = write_runtime_image(data, runtime_dir, stem)
    if artwork_file:
        raw_path.unlink(missing_ok=True)
        return artwork_file, ""

    out = runtime_dir / f"{stem}.png"
    try:
        result = subprocess.run(
            ["sips", "-s", "format", "png", str(raw_path), "--out", str(out)],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        raw_path.unlink(missing_ok=True)
        return "", f"direct:{error}:sips=not_found"
    except subprocess.TimeoutExpired:
        raw_path.unlink(missing_ok=True)
        return "", f"direct:{error}:sips=timeout"

    raw_path.unlink(missing_ok=True)
    if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return out.name, ""

    detail = (result.stderr or result.stdout).strip()
    return "", f"direct:{error}:sips={detail}"
