"""Minimal two-set Korean keyboard composer used when native IME input is unavailable."""

from dataclasses import dataclass


@dataclass(frozen=True)
class _Consonant:
    initial: int
    final: int | None
    compatibility: str


_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_VOWELS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_FINALS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

_CONSONANTS = {
    "r": _Consonant(0, 1, "ㄱ"), "R": _Consonant(1, 2, "ㄲ"),
    "s": _Consonant(2, 4, "ㄴ"), "e": _Consonant(3, 7, "ㄷ"),
    "E": _Consonant(4, None, "ㄸ"), "f": _Consonant(5, 8, "ㄹ"),
    "a": _Consonant(6, 16, "ㅁ"), "q": _Consonant(7, 17, "ㅂ"),
    "Q": _Consonant(8, None, "ㅃ"), "t": _Consonant(9, 19, "ㅅ"),
    "T": _Consonant(10, 20, "ㅆ"), "d": _Consonant(11, 21, "ㅇ"),
    "w": _Consonant(12, 22, "ㅈ"), "W": _Consonant(13, None, "ㅉ"),
    "c": _Consonant(14, 23, "ㅊ"), "z": _Consonant(15, 24, "ㅋ"),
    "x": _Consonant(16, 25, "ㅌ"), "v": _Consonant(17, 26, "ㅍ"),
    "g": _Consonant(18, 27, "ㅎ"),
}
_VOWEL_KEYS = {
    "k": 0, "o": 1, "i": 2, "O": 3, "j": 4, "p": 5, "u": 6, "P": 7,
    "h": 8, "y": 12, "n": 13, "b": 17, "m": 18, "l": 20,
}
_COMPOUND_VOWELS = {
    (8, 0): 9, (8, 1): 10, (8, 20): 11,
    (13, 4): 14, (13, 5): 15, (13, 20): 16, (18, 20): 19,
}
_COMPOUND_FINALS = {
    (1, 19): 3, (4, 22): 5, (4, 27): 6, (8, 1): 9,
    (8, 16): 10, (8, 17): 11, (8, 19): 12, (8, 25): 13,
    (8, 26): 14, (8, 27): 15, (17, 19): 18,
}


def _tokens(keys: str) -> list[tuple[str, object]]:
    result = []
    for key in keys:
        consonant = _CONSONANTS.get(key)
        if consonant:
            result.append(("c", consonant))
        elif key in _VOWEL_KEYS:
            result.append(("v", _VOWEL_KEYS[key]))
    return result


def is_dubeolsik_key(key: str) -> bool:
    return key in _CONSONANTS or key in _VOWEL_KEYS


def compose_dubeolsik(keys: str) -> str:
    """Convert a run of English key events into Hangul syllables (two-set layout)."""
    tokens = _tokens(keys)
    output: list[str] = []
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind != "c":
            output.append(_VOWELS[int(value)])
            i += 1
            continue

        consonant = value
        assert isinstance(consonant, _Consonant)
        initial = consonant.initial
        i += 1
        if i >= len(tokens) or tokens[i][0] != "v":
            output.append(consonant.compatibility)
            continue

        vowel = int(tokens[i][1])
        i += 1
        if i < len(tokens) and tokens[i][0] == "v":
            compound = _COMPOUND_VOWELS.get((vowel, int(tokens[i][1])))
            if compound is not None:
                vowel = compound
                i += 1

        final = 0
        if i < len(tokens) and tokens[i][0] == "c":
            first = tokens[i][1]
            assert isinstance(first, _Consonant)
            next_is_vowel = i + 1 < len(tokens) and tokens[i + 1][0] == "v"
            second_is_consonant = i + 1 < len(tokens) and tokens[i + 1][0] == "c"
            vowel_after_second = i + 2 < len(tokens) and tokens[i + 2][0] == "v"

            if first.final is not None and second_is_consonant:
                second = tokens[i + 1][1]
                assert isinstance(second, _Consonant)
                cluster = (_COMPOUND_FINALS.get((first.final, second.final))
                           if second.final is not None else None)
                if cluster is not None and not vowel_after_second:
                    final = cluster
                    i += 2
                elif vowel_after_second:
                    final = first.final
                    i += 1
            elif first.final is not None and not next_is_vowel:
                final = first.final
                i += 1

        codepoint = 0xAC00 + ((initial * 21 + vowel) * 28) + final
        output.append(chr(codepoint))
    return "".join(output)
