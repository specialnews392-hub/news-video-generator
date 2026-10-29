import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.visual_plan import build_visual_segments, search_queries, make_text_card


class VisualTests(unittest.TestCase):
    def test_paragraph_indices_not_plan_order(self):
        paragraphs = ['Erster Satz. ' * 40, 'Zweiter Absatz.']
        segments, queries = build_visual_segments(paragraphs, [
            {'paragraph_index': 1, 'search_query': 'second'},
            {'paragraph_index': 0, 'search_query': 'first'},
        ], 'Rente')
        self.assertGreater(len(segments), 2)
        self.assertEqual(queries[:-1], ['first'] * (len(segments)-1))
        self.assertEqual(queries[-1], 'second')
        self.assertEqual(' '.join(segments), ' '.join(' '.join(paragraphs).split()))

    def test_missing_plan_keeps_topic(self):
        self.assertEqual(build_visual_segments(['Eine Aussage.'], [], 'Rente')[1], ['Rente'])
        queries = search_queries('Beratung', 'Rentenreform Deutschland', 'Rente')
        self.assertTrue(all('Polizei' not in q and 'Grenz' not in q for q in queries))

    def test_card_renders(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = make_text_card(Path(directory) / 'card.png', 'Rente',
                                  'Die Rentenversicherung erklärt die Berechnung der Beiträge. ' * 3)
            with Image.open(path) as im:
                self.assertEqual(im.size, (1920, 1080))

    def run_selection(self, verdicts, queries=None):
        config = types.ModuleType('config')
        httpx = types.ModuleType('httpx')
        bs4 = types.ModuleType('bs4')
        bs4.BeautifulSoup = object
        analyzer = types.ModuleType('services.image_analyzer')
        analyzer.analyze_image_file = AsyncMock(side_effect=verdicts)
        with patch.dict(sys.modules, {'config': config, 'httpx': httpx, 'bs4': bs4,
                                     'services.image_analyzer': analyzer}):
            spec = importlib.util.spec_from_file_location('test_searcher', ROOT / 'services/image_searcher.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.search_images = AsyncMock(return_value=[{'url': 'https://example.org/a.jpg'},
                                                           {'url': 'https://example.org/b.jpg'}])
            async def download(url, path, **kwargs):
                path.write_bytes(b'test-image')
                return True
            module.download_image = download
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'images'
                paths = asyncio.run(module.search_and_download_images(
                    queries or ['Rentenberatung'], output, topic='Rente',
                    segments=['Die Rentenversicherung erklärt die Berechnung.']))
                manifest = json.loads((Path(directory) / 'visual_selection.json').read_text())
                self.assertEqual(len(paths), 1)
                self.assertTrue(Path(paths[0]).exists())
                return manifest[0], analyzer.analyze_image_file.call_count

    def test_reject_then_select(self):
        result, count = self.run_selection([
            {'status': 'rejected', 'relevant': False, 'score': 2},
            {'status': 'approved', 'relevant': True, 'score': 8},
        ])
        self.assertEqual(result['kind'], 'photo')
        self.assertTrue(result['source_url'].endswith('b.jpg'))
        self.assertEqual(count, 2)

    def test_outage_produces_card_not_random_image(self):
        result, _ = self.run_selection([{'status': 'unverified'}] * 3)
        self.assertEqual(result['kind'], 'text_card')

    def test_chart_request_produces_card_without_web_photo(self):
        result, count = self.run_selection([], ['Grafik Rentenentwicklung'])
        self.assertEqual(result['kind'], 'text_card')
        self.assertEqual(count, 0)

    def test_high_score_without_approval_is_not_accepted(self):
        result, _ = self.run_selection([{'status': 'rejected', 'relevant': False, 'score': 9}] * 2)
        self.assertEqual(result['kind'], 'text_card')

    def test_analyzer_does_not_accept_empty_or_string_boolean(self):
        config = types.ModuleType('config')
        config.get_next_gemini_key = lambda: 'dummy'
        config.GEMINI_VISION_MODEL = 'offline'
        google = types.ModuleType('google')
        genai = types.ModuleType('google.genai')
        api_types = types.SimpleNamespace(
            Content=lambda **kw: kw, GenerateContentConfig=lambda **kw: kw,
            Part=types.SimpleNamespace(from_text=lambda **kw: kw, from_bytes=lambda **kw: kw))
        genai.types = api_types
        google.genai = genai
        with patch.dict(sys.modules, {'config': config, 'google': google, 'google.genai': genai}):
            spec = importlib.util.spec_from_file_location('test_analyzer', ROOT / 'services/image_analyzer.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / 'image.jpg'
                image.write_bytes(b'image')
                for answer in ('', '{"relevant":"false","score":9}', 'invalid JSON'):
                    genai.Client = lambda **kw: types.SimpleNamespace(models=types.SimpleNamespace(
                        generate_content=lambda **kw: types.SimpleNamespace(text=answer)))
                    result = asyncio.run(module.analyze_image_file(image, 'Rente', 'Rente'))
                    self.assertFalse(result['relevant'])


if __name__ == '__main__':
    unittest.main()
