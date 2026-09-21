import unittest
from app.preprocessing import normalize_for_tts, normalize_numbers


class NumberTests(unittest.TestCase):
    def test_required_examples(self):
        cases = {
            '0': 'ゼロ', '25': 'にじゅうご', '300': 'さんびゃく',
            '3136': 'さんぜんひゃくさんじゅうろく', '10000': 'いちまん',
            '3,136': 'さんぜんひゃくさんじゅうろく',
            '6ターンの間': '六ターンの間', '６ターン': '六ターン',
            '1920%×3体': '千九百二十%×三体',
            '1,920ダメージ': '千九百二十ダメージ',
            '１，９２０％': '千九百二十％',
            '1体、8体': '一体、八体', '1回、6回、10回': '一回、六回、十回',
            '1人、2人、4人': '一人、二人、四人', '1個、10個': '一個、十個',
            '10000倍': '一万倍', '100000001ダメージ': '一億一ダメージ',
            '0%': '零%', '999999999%': '九億九千九百九十九万九千九百九十九%',
            'S1とS2': 'S一とS二', 'S１、Ｓ２': 'S一、Ｓ二',
            'スキル１とスキル2': 'スキル一とスキル二',
            'パッシブ１、パッシブ2': 'パッシブ一、パッシブ二',
            'Lv240、LV２４０、lv240': 'Lv二百四十、LV二百四十、lv二百四十',
            'レベル１、レベル240': 'レベル一、レベル二百四十',
            '3.5': 'さんてんご', '10.25': 'じゅってんにご', '0.5': 'ゼロてんご',
            '3.5%': 'さんてんごぱーせんと', '1.05倍': 'いちてんゼロご倍',
            '１．５倍': 'いちてんご倍', '3.5体': '3.5体',
            '第1章': 'だいいっしょう', '第18章': 'だいじゅうはっしょう',
            '攻撃力が3136増加する': '攻撃力がさんぜんひゃくさんじゅうろく増加する',
            '1つ、2つ': '一つ、二つ', '1発、2発': '一発、二発', '1連撃、2連撃': '一連撃、二連撃',
            '2.5つ': '2.5つ', '1.5発': '1.5発', '2.5連撃': '2.5連撃',
            '1時、2分、3秒': '一時、二分、三秒', '1階、10階': '一階、十階', '1枚、5円': '一枚、五円',
            '10000円': '一万円', '1.5秒': '1.5秒', '2.5円': '2.5円',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_numbers(source), expected)
                self.assertEqual(normalize_numbers(expected), expected)

    def test_protected_and_unsupported(self):
        for text in ('RTX 3070','Windows 11','A.I.VOICE2','GPT-5','Irodori-TTS-Editor',
                     'https://example.com/3136?q=30','001.wav',r'E:\音声\3136.wav',
                     '../audio/123.wav','3D','LR5','1000000000','001','1,23','1.2.3', 'S01', 'S1A', 'AS1', 'Ｓ１Ａ', 'ＡＳ１', 'S１A', 'Lv1.2', 'S1.2',
                     'スキル1.2', 'スキル001', 'https://example.com/S1', 'S1.wav'):
            with self.subTest(text=text):
                self.assertEqual(normalize_numbers(text),text)

    def test_dictionary_order_and_disable(self):
        source = 'LR5の攻撃力30%'
        entries = [dict(word='LR5',reading='エルアールご',enabled=True)]
        self.assertEqual(normalize_for_tts(source,entries),'エルアールごの攻撃力三十%')
        self.assertEqual(normalize_for_tts(source,entries,normalize_numeric=False),'エルアールごの攻撃力30%')
        self.assertEqual(source,'LR5の攻撃力30%')

    def test_hp_readings(self):
        cases = {'HP':'エイチピー','低HP':'テイエイチピー','高HP':'コウエイチピー',
                 '現在HP':'ゲンザイエイチピー','HP割合':'エイチピーワリアイ',
                 '現在ＨＰの30%':'ゲンザイエイチピーの三十%',
                 '低hpの対象':'テイエイチピーの対象'}
        for source, expected in cases.items():
            self.assertEqual(normalize_for_tts(source),expected)
            self.assertEqual(normalize_for_tts(expected),expected)
        self.assertEqual(normalize_for_tts('HP30%',normalize_numeric=False),'エイチピー30%')
        for source in ['PHP','HPA','https://example.com/HP',r'E:\HP\voice.wav','HP.wav']:
            self.assertEqual(normalize_for_tts(source),source)

    def test_combined_and_disabled(self):
        source = '現在HPに対して10%なので、火力倍率は1920%×3体、S1とスキル１'
        expected = 'ゲンザイエイチピーに対して十%なので、火力倍率は千九百二十%×三体、S一とスキル一'
        self.assertEqual(normalize_for_tts(source), expected)
        self.assertEqual(normalize_for_tts(source, normalize_numeric=False), source.replace('現在HP', 'ゲンザイエイチピー'))
        entries = [dict(word='S1', reading='えすわん', enabled=True)]
        self.assertEqual(normalize_for_tts('S1とS2', entries), 'えすわんとS二')

    def test_hp_user_dictionary_wins(self):
        entries=[dict(word='HP',reading='えいちぴー',enabled=True)]
        self.assertEqual(normalize_for_tts('現在HP',entries),'現在えいちぴー')
        entries=[dict(word='現在HP',reading='現在HPの独自読み',enabled=True)]
        self.assertEqual(normalize_for_tts('現在HP',entries),'現在HPの独自読み')
        entries[0]['enabled']=False
        self.assertEqual(normalize_for_tts('現在HP',entries),'ゲンザイエイチピー')


if __name__ == '__main__':
    unittest.main()
