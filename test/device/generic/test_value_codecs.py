import math
import pytest

from util.value_decoder import ValueDecoder


def test_extract_bit():
    assert ValueDecoder.extract_bit(0b1010, 1) == 1
    assert ValueDecoder.extract_bit(0b1010, 0) == 0


def test_formula_and_scale():
    v = ValueDecoder.apply_linear_formula(10, (1, 2, 3))  # (10+1)*2+3 = 25
    assert ValueDecoder.apply_scale(v, 0.1) == pytest.approx(2.5)


def test_u32_le():
    words = [0x5678, 0x1234]  # low word first
    val = ValueDecoder.decode_registers("u32_le", words)
    assert val == 0x12345678


def test_u32_be():
    words = [0x1234, 0x5678]  # high word first
    val = ValueDecoder.decode_registers("u32_be", words)
    assert val == 0x12345678


def test_uint32_alias():
    words = [0x5678, 0x1234]
    val = ValueDecoder.decode_registers("uint32", words)
    assert val == 0x12345678


def test_f32_be():
    words = [0x4048, 0xF5C3]  # 3.14 in IEEE754 (big-endian)
    val = ValueDecoder.decode_registers("f32_be", words)
    assert math.isclose(val, 3.14, rel_tol=1e-6)


def test_f32_le():
    words = [0xF5C3, 0x4048]  # 3.14 in IEEE754 (little-endian word order)
    val = ValueDecoder.decode_registers("f32_le", words)
    assert math.isclose(val, 3.14, rel_tol=1e-6)


def test_u16_and_i16():
    assert ValueDecoder.decode_registers("u16", [0xABCD]) == 0xABCD
    assert ValueDecoder.decode_registers("uint16", [0xABCD]) == 0xABCD
    assert ValueDecoder.decode_registers("i16", [0xFFFF]) == -1
