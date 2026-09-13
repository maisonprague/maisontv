#!/usr/bin/env python3
"""Generate filtered, deterministic M3U files from official iptv-org playlists."""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

LOG = logging.getLogger(__name__)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


class UpstreamError(RuntimeError):
    """The upstream data cannot safely be used for a generation run."""


@dataclass(frozen=True)
class Channel:
    name: str
    url: str
    tvg_id: str = ""
    tvg_name: str = ""
    tvg_logo: str = ""
    category: str = ""
    country: str = ""


def enabled_values(items: list[Any], key: str) -> list[str]:
    """Support concise strings and {key, enabled} config entries."""
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            result.append(item.lower() if key == "code" else item)
        elif isinstance(item, dict) and item.get("enabled", True):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                result.append(value.lower() if key == "code" else value.strip())
    return result


def enabled_countries(items: list[Any]) -> list[tuple[str, str]]:
    """Return (display_code, upstream_playlist_code) in configured order."""
    result: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, str):
            result.append((item.lower(), item.lower()))
        elif isinstance(item, dict) and item.get("enabled", True):
            code = item.get("code")
            upstream_code = item.get("upstream_code", code)
            if isinstance(code, str) and isinstance(upstream_code, str) and code and upstream_code:
                result.append((code.lower(), upstream_code.lower()))
    return result


def load_config(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read configuration {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a mapping")
    return data


def fetch_text(url: str, timeout: int, retries: int) -> str:
    request = Request(url, headers={"User-Agent": "iptv-org-playlist-generator/1.0"})
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310: configured HTTPS upstream
                if response.status != 200:
                    raise UpstreamError(f"HTTP {response.status} for {url}")
                return response.read().decode("utf-8-sig")
        except (HTTPError, URLError, OSError, UnicodeDecodeError, UpstreamError) as exc:
            last_error = exc
            LOG.warning("Upstream request failed (%s/%s): %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(attempt)
    raise UpstreamError(f"Could not download {url}: {last_error}")


def valid_stream_url(value: str) -> bool:
    if not value or any(char.isspace() for char in value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password


def parse_m3u(text: str, country: str = "") -> list[Channel]:
    """Read the EXTINF/URL pairs used by iptv-org; ignore unrelated M3U tags."""
    entries: list[Channel] = []
    pending: tuple[dict[str, str], str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXTINF:"):
            info, separator, display_name = line.partition(",")
            if not separator:
                pending = None
                continue
            pending = ({key: value for key, value in ATTR_RE.findall(info)}, display_name.strip())
        elif pending and line and not line.startswith("#"):
            attrs, name = pending
            if valid_stream_url(line):
                entries.append(Channel(
                    name=name or attrs.get("tvg-name", ""), url=line,
                    tvg_id=attrs.get("tvg-id", ""), tvg_name=attrs.get("tvg-name", ""),
                    tvg_logo=attrs.get("tvg-logo", ""), category=attrs.get("group-title", ""),
                    country=country,
                ))
            pending = None
        elif line and not line.startswith("#"):
            pending = None
    return entries


def category_lookup(channels: Iterable[Channel]) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    by_id_url: dict[tuple[str, str], str] = {}
    by_url: dict[str, str] = {}
    for channel in channels:
        if channel.category:
            by_id_url[(channel.tvg_id, channel.url)] = channel.category
            by_url.setdefault(channel.url, channel.category)
    return by_id_url, by_url


def selected_channels(
    country_channels: Iterable[Channel], categories: list[str], by_id_url: dict[tuple[str, str], str], by_url: dict[str, str]
) -> list[Channel]:
    allowed = {category.casefold(): category for category in categories}
    result: list[Channel] = []
    for channel in country_channels:
        category = by_id_url.get((channel.tvg_id, channel.url), by_url.get(channel.url, ""))
        canonical = allowed.get(category.casefold())
        if canonical:
            result.append(Channel(**{**channel.__dict__, "category": canonical}))
    return result


def deduplicate(channels: Iterable[Channel]) -> list[Channel]:
    """A stream URL is the stable duplicate key; retain the first configured country."""
    seen: set[str] = set()
    result: list[Channel] = []
    for channel in channels:
        if channel.url not in seen:
            seen.add(channel.url)
            result.append(channel)
    return result


def m3u_text(channels: Iterable[Channel], group_by: str) -> str:
    rows = ["#EXTM3U"]
    for channel in channels:
        group = f"{channel.country.upper()} | {channel.category}" if group_by == "country" else channel.category
        name = channel.name if group_by == "country" else f"[{channel.country.upper()}] {channel.name}"
        attrs = [
            f'tvg-id="{m3u_attribute(channel.tvg_id)}"', f'tvg-name="{m3u_attribute(channel.tvg_name or channel.name)}"',
            f'tvg-logo="{m3u_attribute(channel.tvg_logo)}"', f'group-title="{m3u_attribute(group)}"',
        ]
        rows.extend((f'#EXTINF:-1 {" ".join(attrs)},{name}', channel.url))
    return "\n".join(rows) + "\n"


def m3u_attribute(value: str) -> str:
    """Keep a malformed upstream attribute from breaking this output record."""
    return value.replace('"', "'").replace("\r", " ").replace("\n", " ")


def validate_m3u(content: str, minimum_records: int) -> int:
    lines = [line for line in content.splitlines() if line]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("M3U header is missing")
    records = 0
    for index, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            if index + 1 >= len(lines) or not valid_stream_url(lines[index + 1]):
                raise ValueError("An EXTINF record has no valid HTTP(S) URL")
            records += 1
    if records < minimum_records:
        raise ValueError(f"Generated only {records} records; safety minimum is {minimum_records}")
    return records


def write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def generate(config: dict[str, Any], output_dir: Path) -> tuple[int, int]:
    countries = enabled_countries(config.get("countries", []))
    categories = enabled_values(config.get("categories", []), "name")
    if not countries or not categories:
        raise ValueError("At least one enabled country and category is required")
    upstream = config.get("upstream", {})
    base_url = str(upstream.get("base_url", "https://iptv-org.github.io/iptv")).rstrip("/")
    timeout, retries = int(upstream.get("timeout_seconds", 30)), int(upstream.get("retries", 3))

    category_source = fetch_text(f"{base_url}/index.category.m3u", timeout, retries)
    by_id_url, by_url = category_lookup(parse_m3u(category_source))
    if not by_url:
        raise UpstreamError("Category playlist contains no usable metadata")

    collected: list[Channel] = []
    failures: list[str] = []
    for country, upstream_country in countries:
        try:
            collected.extend(parse_m3u(fetch_text(f"{base_url}/countries/{upstream_country}.m3u", timeout, retries), country))
        except UpstreamError as exc:
            failures.append(country)
            LOG.warning("Skipping unavailable country %s: %s", country, exc)
    if not collected:
        raise UpstreamError(f"No selected country playlists could be downloaded ({', '.join(failures)})")

    channels = deduplicate(selected_channels(collected, categories, by_id_url, by_url))
    minimum = int(config.get("safety", {}).get("minimum_records", 1))
    countries_output = m3u_text(channels, "country")
    categories_output = m3u_text(sorted(channels, key=lambda item: (categories.index(item.category), item.country, item.name.casefold())), "category")
    countries_count = validate_m3u(countries_output, minimum)
    categories_count = validate_m3u(categories_output, minimum)
    write_atomically(output_dir / "countries.m3u", countries_output)
    write_atomically(output_dir / "categories.m3u", categories_output)
    if failures:
        LOG.warning("Completed with unavailable country playlists: %s", ", ".join(failures))
    return countries_count, categories_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/config.yml"))
    parser.add_argument("--output-dir", type=Path, default=Path("playlists"))
    args = parser.parse_args()
    try:
        countries, categories = generate(load_config(args.config), args.output_dir)
        LOG.info("Generated countries.m3u (%d) and categories.m3u (%d)", countries, categories)
        return 0
    except (ValueError, UpstreamError) as exc:
        LOG.error("Generation stopped without replacing playlists: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
