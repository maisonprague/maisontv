import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from generate_playlists import (Channel, category_lookup, deduplicate, enabled_countries, m3u_text, parse_m3u, selected_channels, validate_m3u)


class PlaylistGenerationTests(unittest.TestCase):
    def test_country_configuration_filters_disabled_entries_and_maps_upstream_code(self) -> None:
        configured = [{"code": "cz", "enabled": True}, {"code": "ru", "enabled": False}, {"code": "gb", "upstream_code": "uk"}]
        self.assertEqual(enabled_countries(configured), [("cz", "cz"), ("gb", "uk")])

    def test_filters_country_and_category_metadata(self) -> None:
        metadata = parse_m3u('#EXTM3U\n#EXTINF:-1 tvg-id="one" group-title="Sports",One\nhttps://example.test/one\n')
        by_id_url, by_url = category_lookup(metadata)
        countries = [Channel("One", "https://example.test/one", "one", country="cz"), Channel("Two", "https://example.test/two", country="ua")]
        self.assertEqual(selected_channels(countries, ["Sports"], by_id_url, by_url), [Channel("One", "https://example.test/one", "one", category="Sports", country="cz")])

    def test_removes_duplicate_stream_urls(self) -> None:
        channels = [Channel("A", "https://example.test/a", country="cz"), Channel("B", "https://example.test/a", country="ua")]
        self.assertEqual(deduplicate(channels), channels[:1])

    def test_writes_valid_m3u(self) -> None:
        content = m3u_text([Channel("ČT Sport", "https://example.test/live", "ct", "ČT Sport", "https://logo.test/a.png", "Sports", "cz")], "country")
        self.assertIn('group-title="CZ | Sports"', content)
        self.assertEqual(validate_m3u(content, 1), 1)

    def test_missing_metadata_is_excluded(self) -> None:
        self.assertEqual(selected_channels([Channel("No category", "https://example.test/a", country="cz")], ["General"], {}, {}), [])


if __name__ == "__main__":
    unittest.main()
