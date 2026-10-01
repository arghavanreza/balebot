"""فرم اعلامیهٔ انتقال وجه به صورت PDF، بدون کتابخانهٔ سی.

ورکر پایتون کلادفلر افزونهٔ سی را بار نمی‌کند، برای همین reportlab این‌جا نیست.
خود PDF را می‌نویسیم و فونت نسخ (Noto Naskh) را داخل فایل می‌گذاریم.
حروف فارسی را arabic-reshaper به شکل چسبیده تبدیل می‌کند و python-bidi ترتیب دیداری را راست‌به‌چپ می‌چیند.
هر دو خالص پایتون‌اند. فونت از assets خوانده می‌شود، نه از یک سرویس بیرونی.

اگر استقرار به پوشهٔ python_modules نیاز داشت، در README آمده که pywrangler همان پوشه را
از روی pyproject می‌سازد و نباید commit شود.
"""

from __future__ import annotations

import struct
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display

FONT_FILE = "NotoNaskhArabic-Regular.ttf"
_PAGE_W = 595
_PAGE_H = 842
_MARGIN = 48
_FONT_SIZE = 12
_LINE = 18

_RESHAPER = arabic_reshaper.ArabicReshaper(
    configuration={
        "delete_harakat": True,
        "support_ligatures": True,
        "shift_harakat_position": False,
    }
)


def font_candidates() -> list[Path]:
    """مسیرهای محتمل فونت. تست از ریشه اجرا می‌شود و ورکر گاهی از پوشهٔ دیگری بالا می‌آید."""
    here = Path(__file__).resolve()
    return [
        here.parent.parent / "assets" / "fonts" / FONT_FILE,
        Path.cwd() / "assets" / "fonts" / FONT_FILE,
    ]


def read_font_from_disk() -> bytes:
    for path in font_candidates():
        if path.is_file():
            return path.read_bytes()
    raise FileNotFoundError(FONT_FILE)


def declaration_lines(
    full_name: str,
    national_id: str,
    groups: dict[str, list],
) -> list[str]:
    """متن منطقی اعلامیه، پیش از شکل‌دهی حروف. هر کانال خالی حذف می‌شود.

    groups کلیدهای internal و paya و satna دارد. هر ردیف name و amount و destination می‌خواهد.
    """
    lines = [
        f"اینجانب {full_name} با کد ملی {national_id} درخواست انتقال وجه به این شرح را دارم:",
        "",
    ]
    titles = {"internal": "داخلی", "paya": "پایا", "satna": "ساتنا"}
    for key in ("internal", "paya", "satna"):
        rows = list(groups.get(key) or [])
        if not rows:
            continue
        lines.append(titles[key])
        for row in rows:
            amount = getattr(row, "amount", None)
            name = getattr(row, "name", "")
            destination = getattr(row, "account", None) or getattr(row, "destination", "")
            description = getattr(row, "description", "") or ""
            if isinstance(row, dict):
                amount = row.get("amount")
                name = row.get("name") or ""
                destination = row.get("account") or row.get("destination") or ""
                description = row.get("description") or ""
            shown = f"{amount:,}" if isinstance(amount, int) else str(amount or "")
            extra = f"    {description}" if description else ""
            lines.append(f"{name}    {shown} ریال    {destination}{extra}")
        lines.append("")
    lines.extend(
        [
            "محل امضا و تاریخ",
            "",
            "امضا: ........................",
            "",
            "تاریخ: ........................",
        ]
    )
    return lines


class FontFace:
    """نقشهٔ یونیکد به شناسهٔ گلیف و پهنای هر گلیف. خود منحنی‌ها را نمی‌خوانیم؛ کل فونت در PDF می‌رود."""

    def __init__(self, data: bytes) -> None:
        tables = _table_map(data)
        self.data = data
        self.units, self.bbox = _head(data, tables["head"][0])
        self.ascender, self.descender, self.advances = _hhea_hmtx(data, tables)
        self.cmap = _cmap(data, tables["cmap"][0])

    def glyph(self, codepoint: int) -> int:
        return self.cmap.get(codepoint, 0)

    def advance(self, glyph_id: int) -> int:
        if not self.advances:
            return self.units // 2
        if 0 <= glyph_id < len(self.advances):
            return self.advances[glyph_id]
        return self.advances[-1]


def _table_map(data: bytes) -> dict[str, tuple[int, int]]:
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise ValueError("unsupported font")
    count = struct.unpack_from(">H", data, 4)[0]
    tables: dict[str, tuple[int, int]] = {}
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + index * 16)
        tables[tag.decode("latin1")] = (offset, length)
    return tables


def _head(data: bytes, offset: int) -> tuple[int, tuple[int, int, int, int]]:
    units = struct.unpack_from(">H", data, offset + 18)[0]
    x_min, y_min, x_max, y_max = struct.unpack_from(">hhhh", data, offset + 36)
    return units, (x_min, y_min, x_max, y_max)


def _hhea_hmtx(data: bytes, tables: dict[str, tuple[int, int]]) -> tuple[int, int, list[int]]:
    hhea = tables["hhea"][0]
    ascender, descender = struct.unpack_from(">hh", data, hhea + 4)
    number = struct.unpack_from(">H", data, hhea + 34)[0]
    hmtx = tables["hmtx"][0]
    advances: list[int] = []
    for index in range(number):
        advance, _lsb = struct.unpack_from(">Hh", data, hmtx + index * 4)
        advances.append(advance)
    return ascender, descender, advances


def _cmap(data: bytes, offset: int) -> dict[int, int]:
    """بهترین cmap را برمی‌گرداند. شکل ۴ و ۱۲ هر دو خوانده می‌شوند چون فونت‌ها یکی را کامل‌تر دارند."""
    _version, count = struct.unpack_from(">HH", data, offset)
    best: dict[int, int] = {}
    for index in range(count):
        _platform, _encoding, sub = struct.unpack_from(">HHI", data, offset + 4 + index * 8)
        parsed = _cmap_subtable(data, offset + sub)
        if len(parsed) > len(best):
            best = parsed
    if not best:
        raise ValueError("font has no unicode cmap")
    return best


def _cmap_subtable(data: bytes, start: int) -> dict[int, int]:
    fmt = struct.unpack_from(">H", data, start)[0]
    if fmt == 4:
        return _cmap4(data, start)
    if fmt == 12:
        return _cmap12(data, start)
    return {}


def _cmap4(data: bytes, start: int) -> dict[int, int]:
    # نگاشت تکه‌ای ویندوز. idRangeOffset صفر یعنی گلیف = نویسه + دلتا.
    # غیرصفر یعنی باید از روی خود جدول، خانهٔ آرایهٔ گلیف را پیدا کنیم.
    _fmt, _length, _language, seg_x2 = struct.unpack_from(">HHHH", data, start)
    seg_count = seg_x2 // 2
    end_at = start + 14
    ends = struct.unpack_from(f">{seg_count}H", data, end_at)
    start_at = end_at + seg_count * 2 + 2
    starts = struct.unpack_from(f">{seg_count}H", data, start_at)
    delta_at = start_at + seg_count * 2
    deltas = struct.unpack_from(f">{seg_count}h", data, delta_at)
    range_at = delta_at + seg_count * 2
    ranges = struct.unpack_from(f">{seg_count}H", data, range_at)
    mapping: dict[int, int] = {}
    for index, (lo, hi) in enumerate(zip(starts, ends)):
        if lo == 0xFFFF:
            continue
        for code in range(lo, hi + 1):
            if ranges[index] == 0:
                glyph = (code + deltas[index]) & 0xFFFF
            else:
                # فاصله تا آرایه از محل همین idRangeOffset حساب می‌شود، نه از ابتدای جدول.
                glyph_pos = range_at + index * 2 + ranges[index] + (code - lo) * 2
                glyph = struct.unpack_from(">H", data, glyph_pos)[0]
                if glyph != 0:
                    glyph = (glyph + deltas[index]) & 0xFFFF
            if glyph:
                mapping[code] = glyph
    return mapping


def _cmap12(data: bytes, start: int) -> dict[int, int]:
    groups = struct.unpack_from(">I", data, start + 12)[0]
    mapping: dict[int, int] = {}
    cursor = start + 16
    for _index in range(groups):
        lo, hi, glyph = struct.unpack_from(">III", data, cursor)
        cursor += 12
        # بازهٔ بزرگ را خانه به خانه در دیکشنری نمی‌ریزیم اگر خیلی پهن باشد؛
        # برای این فونت گروه‌ها کوتاه‌اند. سقف محافظه است تا فونت خراب حافظه را پر نکند.
        if hi - lo > 200_000:
            continue
        for code in range(lo, hi + 1):
            mapping[code] = glyph + (code - lo)
    return mapping


def _bind_font(data: bytes) -> FontFace:
    return FontFace(data)


def _shape(text: str) -> str:
    """رشته را برای رسم چپ‌به‌راست آماده می‌کند: اول چسبیدن حروف، بعد ترتیب دیداری."""
    return get_display(_RESHAPER.reshape(text))


def _width(logical: str, font: FontFace, size: float) -> float:
    visual = _shape(logical)
    total = 0
    for char in visual:
        total += font.advance(font.glyph(ord(char)))
    return total * size / font.units


def _wrap(logical: str, font: FontFace, size: float, max_width: float) -> list[str]:
    if not logical:
        return [""]
    if _width(logical, font, size) <= max_width:
        return [logical]
    words = logical.split(" ")
    if len(words) == 1:
        return _break_token(logical, font, size, max_width)
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if _width(trial, font, size) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        if _width(word, font, size) <= max_width:
            current = word
        else:
            pieces = _break_token(word, font, size, max_width)
            lines.extend(pieces[:-1])
            current = pieces[-1]
    if current:
        lines.append(current)
    return lines or [""]


def _break_token(token: str, font: FontFace, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in token:
        trial = current + char
        if current and _width(trial, font, size) > max_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [token]


def _pdf_utf16(text: str) -> str:
    raw = b"\xfe\xff" + text.encode("utf-16-be")
    return "<" + raw.hex() + ">"


def _content_stream(lines: list[str], font: FontFace) -> list[bytes]:
    """هر صفحه یک جریان محتوا. متن از راست چیده می‌شود چون رشتهٔ دیداری را از لبهٔ راست شروع می‌کنیم."""
    max_width = _PAGE_W - 2 * _MARGIN
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap(line, font, _FONT_SIZE, max_width))
    pages: list[bytes] = []
    commands: list[str] = []
    y = _PAGE_H - _MARGIN

    def flush() -> None:
        nonlocal commands, y
        if commands:
            pages.append("".join(commands).encode("ascii"))
        commands = []
        y = _PAGE_H - _MARGIN

    for logical in wrapped:
        if y < _MARGIN + _LINE:
            flush()
        visual = _shape(logical) if logical else ""
        glyphs = [font.glyph(ord(char)) for char in visual]
        glyphs = [glyph for glyph in glyphs if glyph]
        if not glyphs:
            y -= _LINE
            continue
        width = sum(font.advance(glyph) for glyph in glyphs) * _FONT_SIZE / font.units
        x = max(_MARGIN, _PAGE_W - _MARGIN - width)
        hex_body = "".join(f"{glyph:04X}" for glyph in glyphs)
        commands.append(
            f"BT /F1 {_FONT_SIZE} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm <{hex_body}> Tj ET\n"
        )
        y -= _LINE
    if commands:
        pages.append("".join(commands).encode("ascii"))
    if not pages:
        pages.append(b"BT ET\n")
    return pages


def build_declaration_pdf(lines: list[str], font_bytes: bytes) -> bytes:
    """PDF را با فونت داده‌شده می‌سازد. lines متن منطقی فارسی است، نه رشتهٔ از قبل شکل‌داده‌شده."""
    font = _bind_font(font_bytes)
    contents = _content_stream(lines, font)
    title = next((line for line in lines if line.strip()), "declaration")
    return _assemble(contents, font, title)


def _stream(payload: bytes, extra: str = "") -> bytes:
    header = f"<< /Length {len(payload)} {extra}>>\nstream\n".encode("ascii")
    return header + payload + b"\nendstream"


def _assemble(contents: list[bytes], font: FontFace, title: str) -> bytes:
    page_count = len(contents)
    first_page = 9
    kids = " ".join(f"{first_page + index * 2} 0 R" for index in range(page_count))
    x_min, y_min, x_max, y_max = font.bbox
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 3 0 R >>",
        f"<< /Title {_pdf_utf16(title)} /Producer (bale-excel-bot) >>".encode("ascii"),
        f"<< /Type /Pages /Count {page_count} /Kids [{kids}] >>".encode("ascii"),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /NotoNaskhArabic /Encoding /Identity-H "
        b"/DescendantFonts [5 0 R] /ToUnicode 8 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /NotoNaskhArabic "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 6 0 R /DW 500 /CIDToGIDMap /Identity >>",
        (
            f"<< /Type /FontDescriptor /FontName /NotoNaskhArabic /Flags 4 "
            f"/FontBBox [{x_min} {y_min} {x_max} {y_max}] /ItalicAngle 0 "
            f"/Ascent {font.ascender} /Descent {font.descender} /CapHeight 700 /StemV 80 "
            f"/FontFile2 7 0 R >>"
        ).encode("ascii"),
        _stream(font.data, f"/Length1 {len(font.data)} "),
        _stream(_to_unicode(font).encode("ascii")),
    ]
    for index, content in enumerate(contents):
        content_id = first_page + index * 2 + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
                f"/Resources << /Font << /F1 4 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(_stream(content))
    return _pdf_bytes(objects)


def _to_unicode(font: FontFace) -> str:
    """نقشهٔ کوچک تا خوانندهٔ PDF بتواند بخشی از متن را بردارد. رسم صفحه به این نقشه وابسته نیست."""
    pairs = []
    for codepoint, glyph in font.cmap.items():
        if glyph <= 0 or glyph > 0xFFFF or codepoint > 0xFFFF:
            continue
        pairs.append((glyph, codepoint))
    # فایل را بزرگ نمی‌کنیم؛ حروف عربی و لاتین و ارقام کافی‌اند.
    chosen = [(glyph, code) for glyph, code in pairs if code <= 0x06FF or 0xFB50 <= code <= 0xFEFF or code < 128]
    chosen = chosen[:4000]
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    for start in range(0, len(chosen), 100):
        chunk = chosen[start : start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for glyph, code in chunk:
            lines.append(f"<{glyph:04X}> <{code:04X}>")
        lines.append("endbfchar")
    lines.extend(
        [
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ]
    )
    return "\n".join(lines) + "\n"


def _pdf_bytes(objects: list[bytes]) -> bytes:
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    chunks = [header]
    offsets = [0]
    position = len(header)
    for number, body in enumerate(objects, start=1):
        offsets.append(position)
        piece = f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
        chunks.append(piece)
        position += len(piece)
    xref_at = position
    xref = [f"xref\n0 {len(objects) + 1}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 2 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return b"".join(chunks + xref + [trailer])


async def load_font(env: object | None = None) -> bytes:
    """اول دارایی ثابت ورکر، بعد دیسک. نبودن دارایی در تست طبیعی است."""
    if env is not None:
        try:
            assets = getattr(env, "ASSETS")
        except Exception:
            assets = None
        if assets is not None:
            try:
                response = await assets.fetch(  # type: ignore[attr-defined]
                    f"https://assets.local/fonts/{FONT_FILE}"
                )
                status = int(response.status)
                if status == 200:
                    if hasattr(response, "bytes"):
                        data = bytes(await response.bytes())
                    else:
                        from sample_loader import buffer_to_bytes

                        data = buffer_to_bytes(await response.arrayBuffer())
                    if data:
                        return data
            except Exception as exc:
                print("font asset skipped:", type(exc).__name__)
    return read_font_from_disk()
