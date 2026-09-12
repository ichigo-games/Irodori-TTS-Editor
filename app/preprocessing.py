"""Editor-only speech preprocessing. Never mutates subtitle or speech source fields."""
import re

DIGITS = ('ゼロ', 'いち', 'に', 'さん', 'よん', 'ご', 'ろく', 'なな', 'はち', 'きゅう')
MAX_NUMBER = 999_999_999


def integer_reading(n: int) -> str:
    if not 0 <= n <= MAX_NUMBER:
        raise ValueError('Supported integers: 0..999999999')
    if n == 0:
        return DIGITS[0]
    result = ''
    for unit, reading in ((100_000_000, 'おく'), (10_000, 'まん')):
        group, n = divmod(n, unit)
        if group:
            result += integer_reading(group) + reading
    for unit, reading, irregular in (
        (1000, 'せん', {3: 'さんぜん', 8: 'はっせん'}),
        (100, 'ひゃく', {3: 'さんびゃく', 6: 'ろっぴゃく', 8: 'はっぴゃく'}),
        (10, 'じゅう', {}),
    ):
        digit, n = divmod(n, unit)
        if digit:
            result += irregular.get(digit, (DIGITS[digit] if digit != 1 else '') + reading)
    return result + (DIGITS[n] if n else '')


def contract(reading, endings):
    for old, new in endings.items():
        if reading.endswith(old):
            return reading[:-len(old)] + new
    return reading


COUNTERS = {
    'ターン': ('たーん', {}),
    '体': ('たい', {'いち': 'いっ', 'はち': 'はっ', 'じゅう': 'じゅっ'}),
    '回': ('かい', {'いち': 'いっ', 'ろく': 'ろっ', 'はち': 'はっ', 'じゅう': 'じゅっ'}),
    '個': ('こ', {'いち': 'いっ', 'ろく': 'ろっ', 'はち': 'はっ', 'じゅう': 'じゅっ'}),
    '章': ('しょう', {'いち': 'いっ', 'はち': 'はっ', 'じゅう': 'じゅっ'}),
    '人': ('にん', {'よん': 'よ'}),
}
NUMBER = r'[0-9]+(?:[,.][0-9]+)*'
# One pass: protected spans are emitted unchanged, never fed back to replacements.
TOKENS = re.compile(
    r'(?P<protected>https?://[^\s<>「」]+|www\.[^\s<>「」]+'
    r'|(?:[A-Za-z]:[\\/]|\\\\|\.{0,2}/)[^\s<>「」、]+'
    r'|[^\s/\\<>「」、]+\.(?:wav|txt|mp3|json|irodori|py|png|jpg|csv|exe|zip)\b)'
    r'|(?P<level>(?<![A-Za-z0-9_])(?i:lv)(?P<lvnum>[0-9]+)(?![A-Za-z0-9_]))'
    r'|(?P<ordinal>第(?P<ordnum>[0-9]+)章)'
    r'|(?P<identifier>[A-Za-z_][A-Za-z0-9_.-]*(?:[ \t]+[0-9]+(?:\.[0-9]+)*)?|[0-9]+[A-Za-z_][A-Za-z0-9_.-]*)'
    r'|(?P<numeric>' + NUMBER + r')(?P<suffix>ターン|体|回|人|個|[%％])?'
)


def normalize_numbers(text: str) -> str:
    def replace(match):
        if match['protected'] or match['identifier']:
            return match[0]
        raw = match['lvnum'] or match['ordnum'] or match['numeric']
        if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', raw):
            return match[0]
        whole, dot, fraction = raw.replace(',', '').partition('.')
        if len(whole) > 9 or (len(whole) > 1 and whole.startswith('0')):
            return match[0]
        n = int(whole)
        reading = integer_reading(n)
        if match['level']:
            return 'れべる' + reading
        suffix = '章' if match['ordinal'] else match['suffix']
        if dot:
            if suffix in COUNTERS:
                return match[0]  # Fractional counters need separate language rules.
            reading = contract(reading, {'じゅう': 'じゅっ'}) + 'てん' + ''.join(DIGITS[int(d)] for d in fraction)
        if suffix in ('%', '％'):
            return contract(reading, {'じゅう': 'じゅっ'}) + 'ぱーせんと'
        if suffix in COUNTERS:
            if suffix == '人' and n in (1, 2):
                return {1: 'ひとり', 2: 'ふたり'}[n]
            ending, irregular = COUNTERS[suffix]
            reading = contract(reading, irregular) + ending
        return ('だい' if match['ordinal'] else '') + reading
    return TOKENS.sub(replace, text)


def apply_dictionary(text, entries):
    mapping = {e['word']: e['reading'] for e in entries if e['enabled'] and e['word']}
    if not mapping:
        return text
    return re.sub('|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)),
                  lambda m: mapping[m.group()], text)


def normalize_for_tts(text: str, entries=(), *, normalize_numeric: bool = True) -> str:
    text = apply_dictionary(text, entries)
    return normalize_numbers(text) if normalize_numeric else text
