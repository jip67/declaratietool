from app.security import format_iban, hash_password, is_valid_iban, parse_amount, verify_password


def test_password_roundtrip():
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")


def test_iban():
    assert is_valid_iban("NL91 ABNA 0417 1643 00")
    assert is_valid_iban("nl91abna0417164300")
    assert not is_valid_iban("NL91 ABNA 0417 1643 01")
    assert not is_valid_iban("")
    assert format_iban("nl91abna0417164300") == "NL91 ABNA 0417 1643 00"


def test_amount():
    assert parse_amount("12,50") == 1250
    assert parse_amount("€ 1.234,56") == 123456
    assert parse_amount("7.5") == 750
    assert parse_amount("abc") is None
    assert parse_amount("0") is None
