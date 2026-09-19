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


KANJI_DIGITS = '零一二三四五六七八九'
NUMBER_WIDTH = str.maketrans('０１２３４５６７８９，．', '0123456789,.')


def integer_kanji(n: int) -> str:
    if not 0 <= n <= MAX_NUMBER:
        raise ValueError('Supported integers: 0..999999999')
    if n == 0:
        return KANJI_DIGITS[0]
    result = ''
    for unit, label in ((100_000_000, '億'), (10_000, '万')):
        group, n = divmod(n, unit)
        if group:
            result += integer_kanji(group) + label
    for unit, label in ((1000, '千'), (100, '百'), (10, '十')):
        digit, n = divmod(n, unit)
        if digit:
            result += (KANJI_DIGITS[digit] if digit != 1 else '') + label
    return result + (KANJI_DIGITS[n] if n else '')


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
    'つ': ('つ', {}),
    '発': ('はつ', {'いち': 'いっ', 'ろく': 'ろっ', 'はち': 'はっ', 'じゅう': 'じゅっ'}),
    '連撃': ('れんげき', {'いち': 'いっ', 'はち': 'はっ', 'じゅう': 'じゅっ'}),
}
NUMBER = r'[0-9０-９]+(?:[,.，．][0-9０-９]+)*'
# One pass: protected spans are emitted unchanged, never fed back to replacements.
TOKENS = re.compile(
    r'(?P<protected>https?://[^\s<>「」]+|www\.[^\s<>「」]+'
    r'|(?:[A-Za-z]:[\\/]|\\\\|\.{0,2}/)[^\s<>「」、]+'
    r'|[^\s/\\<>「」、]+\.(?:wav|txt|mp3|json|irodori|py|png|jpg|csv|exe|zip)\b)'
    r'|(?P<label>(?<![A-Za-zＡ-Ｚａ-ｚ0-9０-９_])(?P<prefix>[lLｌＬ][vVｖＶ]|[sSｓＳ]|スキル|パッシブ|レベル)'
    r'(?P<labelnum>' + NUMBER + r')(?![A-Za-zＡ-Ｚａ-ｚ0-9０-９_.．-]))'
    r'|(?P<ordinal>第(?P<ordnum>[0-9０-９]+)章)'
    r'|(?P<identifier>[A-Za-zＡ-Ｚａ-ｚ_][A-Za-zＡ-Ｚａ-ｚ0-9０-９_.．-]*(?:[ \t]+[0-9０-９]+(?:[.．][0-9０-９]+)*)?|[0-9０-９]+[A-Za-zＡ-Ｚａ-ｚ_][A-Za-zＡ-Ｚａ-ｚ0-9０-９_.．-]*)'
    r'|(?P<numeric>' + NUMBER + r')(?P<suffix>ターン|体|回|人|個|倍|ダメージ|連撃|つ|発|[%％])?'
)


def normalize_numbers(text: str) -> str:
    def replace(match):
        if match['protected'] or match['identifier']:
            return match[0]
        raw = (match['labelnum'] or match['ordnum'] or match['numeric']).translate(NUMBER_WIDTH)
        if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', raw):
            return match[0]
        whole, dot, fraction = raw.replace(',', '').partition('.')
        if len(whole) > 9 or (len(whole) > 1 and whole.startswith('0')):
            return match[0]
        n = int(whole)
        reading = integer_reading(n)
        if match['label']:
            return match['prefix'] + integer_kanji(n) if not dot else match[0]
        suffix = '章' if match['ordinal'] else match['suffix']
        if not dot and suffix and not match['ordinal']:
            return integer_kanji(n) + suffix
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
        return ('だい' if match['ordinal'] else '') + reading + (suffix if suffix in ('倍', 'ダメージ') else '')
    return TOKENS.sub(replace, text)


def apply_dictionary(text, entries):
    mapping = {e['word']: e['reading'] for e in entries if e['enabled'] and e['word']}
    if not mapping:
        return text
    return re.sub('|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)),
                  lambda m: mapping[m.group()], text)


HP_READINGS = {
    '現在HP': 'ゲンザイエイチピー', 'HP割合': 'エイチピーワリアイ',
    '低HP': 'テイエイチピー', '高HP': 'コウエイチピー', 'HP': 'エイチピー',
}
HP_PATTERN = re.compile(
    r'(?<![A-Za-zＡ-Ｚａ-ｚ_])(?:現在[HＨ][PＰ]|[HＨ][PＰ]割合|[低高][HＨ][PＰ]|[HＨ][PＰ])(?![A-Za-zＡ-Ｚａ-ｚ_])',
    re.IGNORECASE,
)


def normalize_hp(text):
    def convert(part):
        return HP_PATTERN.sub(lambda m: HP_READINGS[m[0].replace('Ｈ', 'H').replace('Ｐ', 'P')
                                                    .replace('ｈ', 'H').replace('ｐ', 'P').replace('h', 'H').replace('p', 'P')], part)
    # Leave URLs and file paths untouched, as with number normalization.
    result, start = [], 0
    for match in TOKENS.finditer(text):
        if match['protected']:
            result.extend((convert(text[start:match.start()]), match[0]))
            start = match.end()
    result.append(convert(text[start:]))
    return ''.join(result)


def normalize_for_tts(text: str, entries=(), *, normalize_numeric: bool = True) -> str:
    # User readings are authoritative. Built-in HP conversion only touches unmatched text.
    mapping = {e['word']: e['reading'] for e in entries if e['enabled'] and e['word']}
    if mapping:
        pattern = re.compile('|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
        parts, start = [], 0
        for match in pattern.finditer(text):
            parts.extend((normalize_hp(text[start:match.start()]), mapping[match[0]]))
            start = match.end()
        parts.append(normalize_hp(text[start:]))
        text = ''.join(parts)
    else:
        text = normalize_hp(text)
    return normalize_numbers(text) if normalize_numeric else text
