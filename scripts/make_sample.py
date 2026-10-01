#!/usr/bin/env python3
"""فایل assets/sample.xlsx را می‌سازد؛ همان نمونه‌ای که دکمهٔ «دریافت نمونه اکسل» می‌فرستد.

ستون‌ها همان ستون‌های انتقال وجه‌اند: نام ذینفع، کدملی، شبا یا حساب، مبلغ، شناسه واریز، شرح.
سطرها هر سه کانال را نشان می‌دهند: شبای بانک مهر (داخلی)، شبای بانک دیگر با مبلغ پایا،
شبای بانک دیگر با مبلغ ساتنا، و یک شماره حساب داخلی.
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
from transfer import with_national_check  # noqa: E402


def build_sheba(bban: str) -> str:
    """با رقم کنترلی درست، یک شبا می‌سازد تا نمونه در بررسی شبا هم معتبر باشد."""
    return f"IR{iban_check_digits('IR', bban)}{bban}"


def main() -> None:
    """نمونه را در assets می‌نویسد. شیت دوم فقط برای این است که تست، نادیده گرفتنش را ثابت کند."""
    # BBAN ایران ۲۲ رقم است: ۳ رقم کد بانک و ۱۹ رقم حساب.
    # ۰۶۰ کد بانک مهر است، پس این شبا در بازو داخلی طبقه‌بندی می‌شود.
    internal_sheba = build_sheba("060" + ("0" * 18) + "1")
    paya_sheba = build_sheba("012" + ("0" * 18) + "2")
    satna_sheba = build_sheba("017" + ("0" * 18) + "3")
    national_id = with_national_check("008457594")
    # ۱۳ رقم، داخل بازهٔ ۸ تا ۱۸، و ۱۶ نیست تا با شماره کارت اشتباه نشود.
    internal_account = "1234567890123"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "transfers"
    sheet.append(
        [
            "نام ذینفع",
            "کدملی",
            "شماره شبا / حساب ذینفع",
            "مبلغ",
            "شناسه واریز",
            "شرح",
        ]
    )
    sheet.append(["علی رضایی", national_id, internal_sheba, 1_500_000, "12345", "حقوق"])
    sheet.append(["سارا محمدی", None, paya_sheba, 250_000, None, None])
    sheet.append(["رضا کریمی", None, satna_sheba, 2_500_000_000, None, "نمونه ساتنا"])
    sheet.append(["نرگس احمدی", None, internal_account, 500_000, None, "حساب مهر"])

    ignored = workbook.create_sheet("ignore-me")
    ignored.append(["secret", "SHOULD_NOT_APPEAR"])

    destination = ROOT / "assets" / "sample.xlsx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    print(f"wrote {destination}")
    print(internal_sheba)
    print(paya_sheba)
    print(satna_sheba)
    print(national_id)


if __name__ == "__main__":
    main()
