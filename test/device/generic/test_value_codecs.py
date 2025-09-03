import pytest

from device.generic.value_codecs import ValueDecoder


def test_decode_u16():
    assert ValueDecoder.decode_words("u16", [65535]) == 65535


def test_decode_i16_positive():
    assert ValueDecoder.decode_words("i16", [123]) == 123


def test_decode_i16_negative():
    assert ValueDecoder.decode_words("i16", [0xFFFF]) == -1


def test_apply_bit():
    assert ValueDecoder.apply_bit(0b1010, 1) == 1
    assert ValueDecoder.apply_bit(0b1010, 0) == 0


def test_formula_and_scale():
    v = ValueDecoder.apply_formula(10, (1, 2, 3))  # (10+1)*2+3 = 25
    assert ValueDecoder.apply_scale(v, 0.1) == pytest.approx(2.5)
