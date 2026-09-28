from gensys_assembly import build_fail_serial_num, is_fail_limit_reached


def test_build_fail_serial_num():
    assert build_fail_serial_num("ABC123", 0) == "ABC123_1"
    assert build_fail_serial_num("ABC123", 1) == "ABC123_2"
    assert build_fail_serial_num("ABC123", 2) == "ABC123_3"


def test_fail_limit_reached():
    assert is_fail_limit_reached(2) is False
    assert is_fail_limit_reached(3) is True
