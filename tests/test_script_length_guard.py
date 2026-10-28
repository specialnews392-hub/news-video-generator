"""Offline regressions: no API requests, keys, TTS or application startup."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.script_quality import (
    ScriptQualityError, count_words, word_targets, validate_narration_duration,
)


class LengthChecks(unittest.TestCase):
    def test_minimum_and_duration_boundaries(self):
        self.assertEqual(word_targets(1000), (1800, 2000))
        self.assertEqual(word_targets(15000), (1800, 2000))
        self.assertEqual(count_words("EU-Reform für Bürger: 1.000 Euro."), 6)
        for seconds in (195, 270, 336, 377, 599.99, float('nan')):
            with self.assertRaises(ScriptQualityError):
                validate_narration_duration(seconds)
        validate_narration_duration(600)
        validate_narration_duration(900)
        validate_narration_duration(30, is_preview=True)

    def run_generator(self, replies):
        config = types.ModuleType('config')
        config.GEMINI_MODEL = 'offline-test'
        config.GEMINI_FALLBACK_MODELS = []
        config.GEMINI_KEYS = ['dummy']
        config._key_index = 0
        config.get_next_gemini_key = lambda: 'dummy'
        genai = types.ModuleType('google.genai')
        genai.types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: kw)
        generate = Mock(side_effect=[types.SimpleNamespace(text=r) for r in replies])
        genai.Client = lambda **kw: types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=generate))
        google = types.ModuleType('google')
        google.genai = genai
        fetcher = types.ModuleType('services.news_fetcher')
        fetcher._title_similarity = lambda a, b: 0
        translator = types.ModuleType('services.translator')
        translator.translate_to_ru = lambda text: text
        modules = {'config': config, 'google': google, 'google.genai': genai,
                   'services.news_fetcher': fetcher, 'services.translator': translator}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('offline_generator', ROOT / 'services/script_generator.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = asyncio.run(module.generate_script(
                [{'title': 'Test', 'full_text': 'Verified facts'}],
                'Test', lang='de', previous_titles=[], _is_retry=True))
        return result, generate

    @staticmethod
    def reply(words, **extras):
        return json.dumps(dict(status='ready', paragraphs=['Fakt ' * words],
                               title='Test', **extras))

    def test_short_draft_revised_before_acceptance(self):
        result, generate = self.run_generator([self.reply(729), self.reply(1800)])
        self.assertEqual(result['word_count'], 1800)
        self.assertEqual(generate.call_count, 2)
        self.assertIn('729', generate.call_args.kwargs['contents'])

    def test_repeated_short_drafts_rejected(self):
        with self.assertRaises(ScriptQualityError):
            self.run_generator([self.reply(826)] * 3)

    def test_wrapped_json_cannot_bypass_length_check(self):
        with self.assertRaises(ScriptQualityError):
            self.run_generator(['```json\n' + self.reply(500) + '\n```'] * 3)

    def test_research_status_cannot_be_forced_to_ready(self):
        with self.assertRaises(ScriptQualityError):
            self.run_generator([json.dumps({'status': 'needs_research',
                                           'research_gaps': ['More evidence']})])


if __name__ == '__main__':
    unittest.main()
