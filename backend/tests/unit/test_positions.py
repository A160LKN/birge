"""Дробные ключи позиций: порядок, граничные случаи и свойство «вставка всегда между соседями»."""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.positions import DIGITS, PositionError, key_between, keys_after

pytestmark = pytest.mark.unit


def test_alphabet_is_in_byte_order():
    """Порядок символов алфавита должен совпадать с побайтным — на этом держится COLLATE "C"."""
    assert list(DIGITS) == sorted(DIGITS)
    assert all(ord(ch) < 128 for ch in DIGITS)


def test_first_key_is_in_the_middle():
    assert key_between(None, None) == "V"


@pytest.mark.parametrize(("before", "after"), [
    (None, "V"), ("V", None), ("V", "W"), ("V", "V1"), ("0V", "1"), ("a", "a0V"), ("z", None), (None, "01"),
])
def test_key_is_strictly_between_neighbours(before, after):
    key = key_between(before, after)
    assert (before is None or before < key) and (after is None or key < after)
    assert not key.endswith("0")


def test_appending_many_keeps_order_and_short_keys():
    keys = keys_after(None, 200)
    assert keys == sorted(keys) and len(set(keys)) == 200
    assert max(map(len, keys)) <= 40  # рост длины линейный, но медленный — для доски с запасом


def test_prepending_many_keeps_order():
    keys = ["V"]
    for _ in range(100):
        keys.insert(0, key_between(None, keys[0]))
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_inserting_into_the_same_gap_repeatedly():
    low, high = "V", "W"
    for _ in range(50):
        middle = key_between(low, high)
        assert low < middle < high
        high = middle  # каждый раз вставляем сразу после low — самый тяжёлый случай


@pytest.mark.parametrize(("before", "after"), [("W", "V"), ("V", "V")])
def test_wrong_order_is_rejected(before, after):
    with pytest.raises(PositionError):
        key_between(before, after)


@pytest.mark.parametrize("bad", ["", "V0", "ж", "V V", "-"])
def test_invalid_keys_are_rejected(bad):
    with pytest.raises(PositionError):
        key_between(bad, None)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=60))
def test_random_insertions_always_keep_a_valid_order(slots):
    """Hypothesis генерирует сотни случайных последовательностей вставок — порядок должен сохраняться всегда."""
    keys: list[str] = []
    for slot in slots:
        i = slot % (len(keys) + 1)
        before = keys[i - 1] if i > 0 else None
        after = keys[i] if i < len(keys) else None
        keys.insert(i, key_between(before, after))
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    assert all(not k.endswith("0") for k in keys)


def test_shared_vectors_match_frontend_contract():
    """Те же примеры проверяет фронтенд (src/lib/positions.test.ts): мгновенный перенос в браузере
    должен давать тот же ключ, что потом посчитает сервер."""
    import json
    from pathlib import Path

    vectors = json.loads((Path(__file__).parents[3] / "shared" / "position-vectors.json").read_text())
    for before, after, expected in vectors["cases"]:
        assert key_between(before, after) == expected
