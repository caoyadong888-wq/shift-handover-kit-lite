#!/usr/bin/env python3
"""Draw docs/screenshot_terminal.png from the lite demo stdout.

Pillow is used for this image only. The generator stays on the standard library.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG = "#10161c"
PANEL = "#18222c"
MUTED = "#b7c4d1"
LED_OK = "#3ddc97"
LED_AMBER = "#e6b35a"
LED_CRIT = "#ff5d5d"
KICKER = "#8ee0c2"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    if not Path(path).is_file():
        raise SystemExit(f"font not found: {path}")
    return ImageFont.truetype(path, size)


def _line_color(line: str) -> str:
    if line.startswith("$ "):
        return LED_OK
    if line.startswith("status:"):
        if line.endswith("red"):
            return LED_CRIT
        if line.endswith("amber"):
            return LED_AMBER
        return LED_OK
    if line.startswith("wrote "):
        return KICKER
    if line.startswith("generator exit"):
        return LED_CRIT
    return "#d6deeb"


def _wrap_mono(line: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if font.getlength(line) <= max_width:
        return [line]
    words = line.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if font.getlength(trial) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def _paint_line(draw: ImageDraw.ImageDraw, x: int, y: int, line: str, font: ImageFont.ImageFont) -> None:
    if line.startswith("$ "):
        draw.text((x, y), "$ ", font=font, fill=LED_OK)
        draw.text((x + font.getlength("$ "), y), line[2:], font=font, fill="#d6deeb")
        return
    draw.text((x, y), line, font=font, fill=_line_color(line))


def draw_terminal(text: str) -> Image.Image:
    font = _font(MONO, 18)
    max_text = 1040
    lines: list[str] = []
    for raw in text.splitlines():
        lines.extend(_wrap_mono(raw, font, max_text))
    line_h = 26
    width = max_text + 56
    height = 48 + 20 + len(lines) * line_h + 22
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 42), fill=PANEL)
    for index, color in enumerate((LED_CRIT, LED_AMBER, LED_OK)):
        cx = 18 + index * 22
        draw.ellipse((cx, 15, cx + 12, 27), fill=color)
    draw.text((88, 12), "python3 demo.py", font=_font(SANS_BOLD, 14), fill=MUTED)
    y = 58
    for line in lines:
        _paint_line(draw, 24, y, line, font)
        y += line_h
    return image


def main() -> int:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "demo.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        sys.stderr.write(completed.stdout)
        return completed.returncode or 1
    text = completed.stdout
    if not text.endswith("\n"):
        text += "\n"
    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "demo_output.txt").write_text(text, encoding="utf-8")
    image = draw_terminal(text)
    path = docs / "screenshot_terminal.png"
    image.save(path, format="PNG", optimize=True)
    size = path.stat().st_size
    if size >= 300 * 1024:
        print(f"{path.name} is {size} bytes", file=sys.stderr)
        return 1
    print(f"wrote {path} {image.size[0]}x{image.size[1]} {size} bytes")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
