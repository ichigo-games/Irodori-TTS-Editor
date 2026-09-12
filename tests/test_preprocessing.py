import unittest
from app.preprocessing import normalize_for_tts, normalize_numbers


class NumberTests(unittest.TestCase):
    def test_required_examples(self):
        cases = {
            '0':'ゼロ','1':'いち','4':'よん','10':'じゅう','25':'にじゅうご',
            '100':'ひゃく','123':'ひゃくにじゅうさん','300':'さんびゃく',
            '600':'ろっぴゃく','800':'はっぴゃく','1000':'せん','3000':'さんぜん',
            '8000':'はっせん','3136':'さんぜんひゃくさんじゅうろく',
            '10000':'いちまん','12345':'いちまんにせんさんびゃくよんじゅうご',
            '3,136':'さんぜんひゃくさんじゅうろく','100,000':'じゅうまん',
            '3.5':'さんてんご','10.25':'じゅってんにご','0.5':'ゼロてんご',
            '30%':'さんじゅっぱーせんと','50％':'ごじゅっぱーせんと',
            '100%':'ひゃくぱーせんと','3.5%':'さんてんごぱーせんと',
            'Lv240':'れべるにひゃくよんじゅう','LV240':'れべるにひゃくよんじゅう',
            'lv240':'れべるにひゃくよんじゅう',
            '1ターン':'いちたーん','3ターン':'さんたーん',
            '1体':'いったい','2体':'にたい','3体':'さんたい','4体':'よんたい',
            '1回':'いっかい','2回':'にかい','3回':'さんかい','6回':'ろっかい','8回':'はっかい','10回':'じゅっかい',
            '1人':'ひとり','2人':'ふたり','3人':'さんにん','4人':'よにん',
            '1個':'いっこ','2個':'にこ','6個':'ろっこ','8個':'はっこ','10個':'じゅっこ',
            '第1章':'だいいっしょう','第2章':'だいにしょう','第18章':'だいじゅうはっしょう',
            '攻撃力が3136増加する':'攻撃力がさんぜんひゃくさんじゅうろく増加する',
            '3ターンの間、攻撃力が30%増加する':'さんたーんの間、攻撃力がさんじゅっぱーせんと増加する',
            'Lv240でスキルが解放される':'れべるにひゃくよんじゅうでスキルが解放される',
            '999999999':'きゅうおくきゅうせんきゅうひゃくきゅうじゅうきゅうまんきゅうせんきゅうひゃくきゅうじゅうきゅう',
            '21回':'にじゅういっかい','14人':'じゅうよにん','1.05':'いちてんゼロご',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_numbers(source), expected)
                self.assertEqual(normalize_numbers(expected), expected)

    def test_protected_and_unsupported(self):
        for text in ('RTX 3070','Windows 11','A.I.VOICE2','GPT-5','Irodori-TTS-Editor',
                     'https://example.com/3136?q=30','001.wav',r'E:\音声\3136.wav',
                     '../audio/123.wav','3D','LR5','1000000000','001','1,23','1.2.3'):
            with self.subTest(text=text):
                self.assertEqual(normalize_numbers(text),text)

    def test_dictionary_order_and_disable(self):
        source = 'LR5の攻撃力30%'
        entries = [dict(word='LR5',reading='エルアールご',enabled=True)]
        self.assertEqual(normalize_for_tts(source,entries),'エルアールごの攻撃力さんじゅっぱーせんと')
        self.assertEqual(normalize_for_tts(source,entries,normalize_numeric=False),'エルアールごの攻撃力30%')
        self.assertEqual(source,'LR5の攻撃力30%')


if __name__ == '__main__':
    unittest.main()
