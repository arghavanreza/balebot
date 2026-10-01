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
    lines = text.split("\n")
    assert lines[0] == "name\tamount\tsheba"
    assert lines[1].startswith("علی رضایی\t1500000\tIR")
    assert lines[2].startswith("سارا محمدی\t250000\tIR")
    assert "SHOULD_NOT_APPEAR" not in text
    for line in lines[1:]:
        sheba = line.split("\t")[2]
        assert validate_sheba(sheba).valid
