from sheba import iban_check_digits, iban_is_valid, validate_sheba

VALID = "IR430120000000000000000001"


def test_iso_reference_iban():
    assert iban_check_digits("GB", "WEST12345698765432") == "82"
    assert iban_is_valid("GB82WEST12345698765432")


def test_generated_iranian_sheba_is_valid():
    result = validate_sheba(VALID)
    assert result.valid
    assert result.reason == "ok"
    assert result.normalized == VALID


def test_spaces_case_and_persian_digits():
    spaced = "ir43 0120 0000 0000 0000 0000 01"
    assert validate_sheba(spaced).valid
    persian = "شبا IR۴۳۰۱۲۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۱"
    assert validate_sheba(persian).normalized == VALID
    assert validate_sheba(persian).valid


def test_bad_checksum_and_shape():
    flipped = "IR430120000000000000000002"
    checksum = validate_sheba(flipped)
    assert not checksum.valid
    assert checksum.reason == "checksum"
    assert checksum.normalized == flipped

    assert validate_sheba("IR000000000000000000000000").reason == "checksum"
    assert validate_sheba("IR123").reason == "format"
    assert validate_sheba("430120000000000000000001").reason == "format"
    # A real ISO IBAN from another country is not an Iranian Sheba.
    foreign = validate_sheba("GB82WEST12345698765432")
    assert not foreign.valid
    assert foreign.reason == "format"
    assert foreign.normalized == ""
