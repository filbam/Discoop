"""QR codes for the terminal: two module rows per text line using '▀' with explicit colors.

Explicit black-on-white colors keep the code scannable on dark and light terminal themes.
"""

import segno
from rich.style import Style
from rich.text import Text

DARK = "#000000"
LIGHT = "#ffffff"
QUIET_ZONE = 4


def qr_matrix(data: str) -> list[list[bool]]:
    """Modules of a regular (non-micro) QR code, ECC level M as on discord.com, with a quiet zone."""
    code = segno.make_qr(data, error="m", boost_error=False)
    return [[bool(cell) for cell in row] for row in code.matrix_iter(scale=1, border=QUIET_ZONE)]


def qr_text(data: str) -> Text:
    rows = qr_matrix(data)
    if len(rows) % 2:
        rows.append([False] * len(rows[0]))
    lines = []
    for top, bottom in zip(rows[0::2], rows[1::2]):
        line = Text()
        for upper, lower in zip(top, bottom):
            line.append("▀", Style(color=DARK if upper else LIGHT, bgcolor=DARK if lower else LIGHT))
        lines.append(line)
    return Text("\n").join(lines)
