#!/usr/bin/env python3
"""فایل assets/sample.xlsx را می‌سازد؛ همان نمونه‌ای که دکمهٔ «دریافت سمپل اکسل» می‌فرستد.

ستون‌ها name و amount و sheba هستند، چون مبدل پیش‌فرض هنوز همین‌ها را خط‌به‌خط می‌نویسد.
شیت دوم یک نشانگر دارد که مبدل نباید آن را در خروجی بیاورد.
شباها از نظر رقم کنترلی معتبرند ولی حساب واقعی نیستند.
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sheba import iban_check_digits  # noqa: E402


def build_sheba(bban: str) -> str:
    """با رقم کنترلی درست، یک شبا می‌سازد تا نمونه در بررسی شبا هم معتبر باشد."""
    return f"IR{iban_check_digits('IR', bban)}{bban}"


def main() -> None:
    """نمونه را در assets می‌نویسد. شیت دوم فقط برای این است که تست، نادیده گرفتنش را ثابت کند."""
    first = build_sheba("0120000000000000000001")
    second = build_sheba("0170000000000000000002")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "payments"
    sheet.append(["name", "amount", "sheba"])
    sheet.append(["علی رضایی", 1500000, first])
    sheet.append(["سارا محمدی", 250000, second])

    ignored = workbook.create_sheet("ignore-me")
    ignored.append(["secret", "SHOULD_NOT_APPEAR"])

    destination = ROOT / "assets" / "sample.xlsx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    print(f"wrote {destination}")
    print(first)
    print(second)


if __name__ == "__main__":
    main()
