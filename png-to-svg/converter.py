#!/usr/bin/env python3
"""
PNG → SVG Converter
====================
Steps:
  1. Load a PNG image.
  2. Convert to black & white using a configurable grayscale threshold.
  3. Remove the white background (make near-white pixels transparent).
  4. Output as SVG.

Vectorization strategy (best → fallback):
  • potrace  – smooth, scalable vector paths (requires `potrace` to be installed).
  • pixel    – run-length-encoded <rect> elements; no external dependencies.

Usage:
  python converter.py input.png                         # → input.svg
  python converter.py input.png output.svg
  python converter.py input.png output.svg --threshold 100 --bg-threshold 220
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    sys.exit(
        "Missing packages. Install with:\n  pip install -r requirements.txt"
    )


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------

def convert_to_bw(image: Image.Image, threshold: int = 128) -> Image.Image:
    """Grayscale → hard black-and-white split at *threshold* (0-255)."""
    gray = image.convert("L")
    return gray.point(lambda p: 0 if p < threshold else 255, "L")


def remove_white_background(bw: Image.Image, bg_threshold: int = 240) -> Image.Image:
    """
    Make pixels at or above *bg_threshold* brightness fully transparent.
    Returns an RGBA image.
    """
    rgba = bw.convert("RGBA")
    data = np.array(rgba, dtype=np.uint8)

    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]
    white_mask = (r >= bg_threshold) & (g >= bg_threshold) & (b >= bg_threshold)
    data[:, :, 3] = np.where(white_mask, 0, 255).astype(np.uint8)

    return Image.fromarray(data, "RGBA")


# ---------------------------------------------------------------------------
# SVG generation — potrace (preferred)
# ---------------------------------------------------------------------------

def _potrace_available() -> bool:
    try:
        r = subprocess.run(
            ["potrace", "--version"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def svg_via_potrace(bw: Image.Image, output_path: str) -> bool:
    """
    Vectorize with potrace (smooth paths).
    Returns True on success; False if potrace is unavailable or fails.
    """
    if not _potrace_available():
        return False

    tmp_pbm = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pbm", delete=False) as f:
            tmp_pbm = f.name

        bw.convert("1").save(tmp_pbm)  # potrace requires 1-bit PBM

        result = subprocess.run(
            ["potrace", "--svg", "--output", output_path, tmp_pbm],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return True

        print(f"  potrace error: {result.stderr.strip()}", file=sys.stderr)
        return False

    except subprocess.TimeoutExpired:
        print("  potrace timed out.", file=sys.stderr)
        return False

    finally:
        if tmp_pbm and os.path.exists(tmp_pbm):
            os.unlink(tmp_pbm)


# ---------------------------------------------------------------------------
# SVG generation — pixel fallback
# ---------------------------------------------------------------------------

def svg_pixel_based(rgba: Image.Image, output_path: str) -> None:
    """
    Build SVG from run-length-encoded <rect> elements (no external tools needed).
    One rect per consecutive run of opaque pixels per scanline.
    """
    data = np.array(rgba)
    height, width = data.shape[:2]
    alpha = data[:, :, 3]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' width="{width}" height="{height}"'
            f' viewBox="0 0 {width} {height}">'
        ),
        '<g fill="black">',
    ]

    for y in range(height):
        row = alpha[y]
        x = 0
        while x < width:
            if row[x] > 128:
                start = x
                while x < width and row[x] > 128:
                    x += 1
                lines.append(
                    f'<rect x="{start}" y="{y}" width="{x - start}" height="1"/>'
                )
            else:
                x += 1

    lines += ["</g>", "</svg>"]

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main conversion pipeline
# ---------------------------------------------------------------------------

def convert(
    input_path: str,
    output_path: str,
    threshold: int = 128,
    bg_threshold: int = 240,
) -> None:
    print(f"  Input : {input_path}")
    print(f"  Output: {output_path}")

    image = Image.open(input_path)
    print(f"  Size  : {image.width}x{image.height}  Mode: {image.mode}")

    print("  [1/3] Converting to black & white …")
    bw = convert_to_bw(image, threshold)

    print("  [2/3] Removing white background …")
    rgba = remove_white_background(bw, bg_threshold)

    print("  [3/3] Generating SVG …")
    if svg_via_potrace(bw, output_path):
        print("  ✓  Done — used potrace (smooth vector paths).")
    else:
        svg_pixel_based(rgba, output_path)
        method = "pixel-based SVG"
        tip = "  Tip: install potrace for smoother, truly scalable paths."
        print(f"  ✓  Done — used {method}.")
        print(tip)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a PNG to SVG: black & white, white background removed.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="Path to input PNG file")
    parser.add_argument(
        "output",
        nargs="?",
        help="Path to output SVG (default: same name with .svg extension)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=128,
        metavar="0-255",
        help="Grayscale threshold — pixels below become black, above become white",
    )
    parser.add_argument(
        "--bg-threshold",
        type=int,
        default=240,
        metavar="0-255",
        help="Pixels brighter than this value are treated as background and removed",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        sys.exit(f"Error: file not found — {args.input}")

    output = args.output or str(Path(args.input).with_suffix(".svg"))
    convert(args.input, output, args.threshold, args.bg_threshold)


if __name__ == "__main__":
    main()
