"""Presentation contract: controlled values and composable, unique SVG definitions."""
import importlib
import re
from html.parser import HTMLParser

import pytest

from backend.services.rpe_service import RPE_LABELS


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


router = importlib.import_module("backend.today.router")


@pytest.mark.parametrize("value", [None, 1, 5, 10])
def test_controlled_selector_has_exact_bars_and_native_selection(value):
    template = router.templates.env.from_string(
        '{% from "today/rpe_selector.html" import rpe_selector %}'
        '{{ rpe_selector("test-rpe", value, options) }}'
    )
    html = template.render(value=value, options=list(RPE_LABELS.items()))
    tags = Tags(html).tags
    radios = [attrs for tag, attrs in tags if tag == 'input']
    assert [radio['value'] for radio in radios] == [str(i) for i in range(1, 11)]
    assert all('required' in radio for radio in radios)
    assert [radio['value'] for radio in radios if 'checked' in radio] == ([] if value is None else [str(value)])
    bars = [attrs for tag, attrs in tags if tag == 'rect' and 'rpe-paint' in attrs.get('class', '').split()]
    assert [int(bar['height']) for bar in bars] == [14 * i for i in range(1, 11)]
    assert all(int(bar['height']) + int(bar['y']) == 156 for bar in bars)
    assert not any(tag in {'button', 'form', 'script'} for tag, attrs in tags)


def test_selector_instances_namespace_all_svg_references():
    template = router.templates.env.from_string(
        '{% from "today/rpe_selector.html" import rpe_selector %}'
        '{{ rpe_selector("first", none, options) }}'
        '{{ rpe_selector("second", 6, options, "Save failed") }}'
    )
    html = template.render(options=list(RPE_LABELS.items()))
    tags = Tags(html).tags
    ids = [attrs['id'] for tag, attrs in tags if 'id' in attrs]
    assert len(ids) == len(set(ids))
    assert set(re.findall(r'url\(#([^)]*)\)', html)) <= set(ids)
    assert any(attrs.get("aria-describedby") == "second-help second-error" for tag, attrs in tags)
    assert 'id="second-error" class="error" role="alert">Save failed</p>' in html


def test_guidance_is_linked_to_each_radio_and_keeps_session_boundary():
    template = router.templates.env.from_string(
        '{% from "today/rpe_selector.html" import rpe_selector %}'
        '{{ rpe_selector("guidance", none, options) }}'
    )
    html = template.render(options=list(RPE_LABELS.items()))
    tags = Tags(html).tags
    radios = [attrs for tag, attrs in tags if tag == 'input']
    panels = [attrs for tag, attrs in tags if 'data-rpe-guidance' in attrs]
    assert [panel['data-rpe-guidance'] for panel in panels] == [str(i) for i in range(1, 11)]
    assert [radio['aria-describedby'] for radio in radios] == [panel['id'] for panel in panels]
    guidance = router.templates.env.get_template('today/rpe_guidance.html').module.guidance
    assert set(guidance) == set(RPE_LABELS)
    assert all(len(parts) == 4 and all(parts) for parts in guidance.values())
    assert 'Оцени всю тренировку, а не только её самый тяжёлый момент' in html
    assert 'субъективная оценка по шкале 1–10' in html
    assert 'Примеры условны' in html
    assert 'не задают точный RPE' in html
    assert 'один максимальный спринт не делает всю тренировку десяткой' in html
