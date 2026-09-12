"""Two-line subtitle wrapping, separate from speech preprocessing."""
import re
import unicodedata

PREFERRED_MIN = 25
PREFERRED_MAX = 30
SEARCH_MARGIN = 5
PUNCTUATION = '、。！？!?'
OPENING = '「『（([【〈《'
CLOSING = '、。，．！？!?」』）)]】〉》ーっゃゅょぁぃぅぇぉッャュョァィゥェォ'
PROTECTED = re.compile(
    r'https?://[^\s「」、]+|[A-Za-z]:[\\/][^\s「」、]+'
    r'|[A-Za-z0-9０-９]+(?:[._,:/+%％#-][A-Za-z0-9０-９]+)*[%％]?'
    r'|[ァ-ヶー]+|[一-龯々]+(?:は|が|を|に|で|と|も|へ)(?=[一-龯ァ-ヶ])'
)


def _kind(char):
    if '一' <= char <= '龯' or char == '々':
        return 'kanji'
    if 'ぁ' <= char <= 'ゖ':
        return 'hiragana'
    if 'ァ' <= char <= 'ヶ' or char == 'ー':
        return 'katakana'
    return 'other'


def format_subtitle(text: str, preferred_min: int = PREFERRED_MIN,
                    preferred_max: int = PREFERRED_MAX) -> str:
    """Insert at most one newline. Explicit manual line breaks always win.

    This is a conservative heuristic, not a Japanese morphological analyzer.
    An indivisible long token may remain a single line.
    """
    if not 1 <= preferred_min <= preferred_max:
        raise ValueError('Expected 1 <= preferred_min <= preferred_max')
    if len(text) <= preferred_max or len(text.splitlines()) > 1 or any(c in text for c in '\r\n\u2028\u2029'):
        return text
    blocked = set()
    for match in PROTECTED.finditer(text):
        blocked.update(range(match.start() + 1, match.end()))

    def safe(i):
        return (0 < i < len(text) and i not in blocked
                and text[i] not in CLOSING and text[i - 1] not in OPENING
                and not unicodedata.combining(text[i])
                and text[i] != '\u200d' and text[i - 1] != '\u200d')

    def score(i):
        if not safe(i) or len(text) - i < 5:
            return 0
        if text[i - 1] in PUNCTUATION:
            return 3
        if text[i - 1].isspace():
            return 2
        before = text[:i]
        if before.endswith(('から', 'まで', 'より', 'ので', 'ため', 'なら', 'けど', 'けれど')) and _kind(text[i]) != 'hiragana':
            return 2
        # Require a plausible noun + particle boundary; do not split arbitrary kana words.
        if i >= 2 and text[i - 1] in 'はがをにでともへ' and _kind(text[i - 2]) in ('kanji', 'katakana') and _kind(text[i]) != 'hiragana':
            return 2
        return 0

    ranges = ((preferred_min, preferred_max),
              (max(1, preferred_min - SEARCH_MARGIN), preferred_min - 1),
              (preferred_max + 1, preferred_max + SEARCH_MARGIN))
    cut = None
    for low, high in ranges:
        candidates = [(score(i), i) for i in range(low, min(high, len(text) - 1) + 1) if score(i)]
        if candidates:
            cut = max(candidates)[1]
            break
    if cut is None:
        # A slightly earlier comma can be much better than cutting a word at 30.
        candidates = [i for i in range(max(1, preferred_min - 2 * SEARCH_MARGIN), min(preferred_min, len(text)))
                      if safe(i) and text[i - 1] in PUNCTUATION]
        if candidates:
            cut = candidates[-1]
    if cut is None:
        candidates = [i for i in range(1, len(text)) if safe(i)]
        if not candidates:
            return text
        boundaries = [i for i in candidates if abs(i - preferred_max) <= SEARCH_MARGIN
                      and _kind(text[i - 1]) != _kind(text[i])]
        cut = min(boundaries or candidates, key=lambda i: (abs(i - preferred_max), -i))
    return text[:cut] + '\n' + text[cut:]
