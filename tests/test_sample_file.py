"""فایل نمونهٔ داخل مخزن باید با همان مبدلی که بازو استفاده می‌کند خوانده شود."""

from pathlib import Path

from excel_convert import convert_excel_to_text
from sample_loader import read_sample_from_disk
from sheba import validate_sheba

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "assets" / "sample.xlsx"


def test_committed_sample_matches_the_default_converter():
    data = SAMPLE.read_bytes()
    assert data == read_sample_from_disk()
    text = convert_excel_to_text(data)
    assert "SHOULD_NOT_APPEAR" not in text
    assert "سطر معتبر: 4" in text
    lines = [line for line in text.split("\n") if line and not line.startswith("سطر معتبر") and not line.startswith("ردیف")]
    channels = []
    for line in lines:
        if line.startswith("…"):
            continue
        fields = line.split("\t")
        assert len(fields) >= 8
        account = fields[3]
        if account.startswith("IR"):
            assert validate_sheba(account).valid
        channels.append(fields[-1])
    assert channels.count("داخلی") == 2
    assert "پایا" in channels
    assert "ساتنا" in channels
    assert any(line.startswith("علی رضایی") or "\tعلی رضایی\t" in line for line in lines)
