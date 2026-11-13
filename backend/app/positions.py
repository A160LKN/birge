"""Порядок карточек и колонок — дробные ключи (fractional indexing).

Вместо номеров 1, 2, 3 у каждой карточки строка-ключ, и порядок — это сортировка строк.
Чтобы поставить карточку между двумя соседями, нужен ключ строго между их ключами —
остальные карточки не трогаются. С номерами перенос одной карточки переписывал бы всю колонку,
а два одновременных переноса мешали бы друг другу.

Ключи сравниваются побайтно, поэтому в PostgreSQL у колонки position — COLLATE "C":
с правилами сортировки языка (en_US, ru_RU) «a» и «B» встали бы в другом порядке.
"""

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"  # порядок символов = порядок байтов
_INDEX = {digit: i for i, digit in enumerate(DIGITS)}
ZERO = DIGITS[0]


class PositionError(ValueError):
    pass


def _validate(key: str) -> None:
    if not key or key.endswith(ZERO) or any(ch not in _INDEX for ch in key):
        raise PositionError(f"Некорректный ключ позиции: {key!r}")


def _midpoint(low: str, high: str | None) -> str:
    """Ключ строго между low и high (high=None — «бесконечность»). low может быть пустой строкой."""
    if high is not None:
        # Общее начало ключей сохраняем и ищем середину в оставшейся части
        n = 0
        while (low[n] if n < len(low) else ZERO) == high[n]:
            n += 1
        if n > 0:
            return high[:n] + _midpoint(low[n:], high[n:])
    digit_low = _INDEX[low[0]] if low else 0
    digit_high = _INDEX[high[0]] if high is not None else len(DIGITS)
    if digit_high - digit_low > 1:
        return DIGITS[(digit_low + digit_high + 1) // 2]
    # Соседние цифры: между ними места нет, уходим на разряд глубже
    if high is not None and len(high) > 1:
        return high[0]
    return DIGITS[digit_low] + _midpoint(low[1:], None)


def key_between(before: str | None, after: str | None) -> str:
    """Ключ для элемента, который встаёт после before и перед after (None — край списка)."""
    if before is not None:
        _validate(before)
    if after is not None:
        _validate(after)
    if before is not None and after is not None and before >= after:
        raise PositionError(f"Ключи не по порядку: {before!r} >= {after!r}")
    return _midpoint(before or "", after)


def keys_after(last: str | None, count: int) -> list[str]:
    """Несколько ключей подряд в конец списка — для колонок новой доски."""
    keys = []
    for _ in range(count):
        last = key_between(last, None)
        keys.append(last)
    return keys
