import unittest
from app.subtitle_formatter import format_subtitle


class SubtitleTests(unittest.TestCase):
    def test_short_and_threshold(self):
        for text in ('', '攻撃力が30%増加します', 'あ' * 30):
            self.assertEqual(format_subtitle(text), text)
        self.assertEqual(format_subtitle('あ' * 31).count('\n'), 1)

    def test_punctuation_and_example(self):
        source = 'このキャラは高い耐久力を持っているため、長期戦でも安定して活躍することができます'
        expected = 'このキャラは高い耐久力を持っているため、\n長期戦でも安定して活躍することができます'
        self.assertEqual(format_subtitle(source), expected)
        for position in (24, 28, 33):
            text = 'あ' * (position - 1) + '、' + 'い' * 35
            self.assertEqual(format_subtitle(text).index('\n'), position)

    def test_particle_and_false_particle(self):
        text = 'あ' * 23 + '攻撃力が' + '増加する効果を持っています'
        self.assertEqual(format_subtitle(text), 'あ' * 23 + '攻撃力が\n増加する効果を持っています')
        text = 'あ' * 23 + 'クリティカル' + 'い' * 20
        self.assertIn('クリティカル', format_subtitle(text))

    def test_atomic_tokens(self):
        for token in ('3136','30%','3.5%','3,136','Lv240','Irodori-TTS','A.I.VOICE2'):
            for offset in range(24, 31):
                source = 'あ' * offset + token + 'い' * 40
                result = format_subtitle(source)
                with self.subTest(token=token, offset=offset):
                    self.assertIn(token, result)
                    self.assertEqual(result.replace('\n',''),source)
                    self.assertEqual(result.count('\n'),1)
        self.assertEqual(format_subtitle('A' * 80), 'A' * 80)

    def test_long_and_manual_newlines(self):
        for size in (45, 70, 150):
            original = 'あ' * size
            result = format_subtitle(original)
            self.assertEqual(result.count('\n'),1)
            self.assertEqual(result.replace('\n',''),original)
            self.assertEqual(original,'あ' * size)
        for text in ('あ\nい', 'あ\r\nい', 'あ\nい\nう', 'あ' * 70 + '\nい'):
            self.assertEqual(format_subtitle(text),text)


if __name__ == '__main__':
    unittest.main()
