"""SSR visual contracts: deterministic SVG baselines, geometry and accessibility."""
import importlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from backend.app import app

router = importlib.import_module("backend.today.router")
FIXTURES = Path(__file__).parent / "fixtures" / "visualizations"
SVG = {"svg": "http://www.w3.org/2000/svg"}


def _charts(html):
    return re.findall(r'<svg class="viz-chart".*?</svg>', html, re.S)


def test_preview_is_read_only_and_stable(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Preview must not access athlete data")

    monkeypatch.setattr(router.today_service, "get_today_data", unexpected)
    monkeypatch.setattr(router, "get_diary_data", unexpected)
    client = TestClient(app)
    first = client.get("/today/visual-system")
    assert first.status_code == 200
    assert first.text == client.get("/today/visual-system").text
    assert "Демонстрационные данные" in first.text
    assert '<form' not in first.text and '<script' not in first.text
    ids = re.findall(r'\bid="([^"]+)"', first.text)
    assert len(ids) == len(set(ids))
    for target in re.findall(r'url\(#([^)]*)\)', first.text):
        assert target in ids
    for svg in _charts(first.text):
        root = ET.fromstring(svg)
        assert root.attrib["role"] == "img"
        for target in root.attrib["aria-labelledby"].split():
            assert root.find(f".//*[@id='{target}']") is not None
        assert root.find("svg:desc", SVG).text
    assert client.post("/today/visual-system").status_code == 405


@pytest.mark.parametrize("index,name", [(0, "bars"), (1, "area"), (2, "annotations")])
def test_representative_svg_regression(index, name):
    # Review SVG changes visually before accepting new fixture geometry/labels.
    actual = _charts(TestClient(app).get("/today/visual-system").text)[index]
    expected = (FIXTURES / f"{name}.svg").read_text()
    assert ET.canonicalize(actual, strip_text=True) == ET.canonicalize(expected, strip_text=True)


def test_fill_and_stroke_preserve_exact_geometry():
    env = router.templates.env
    module = env.get_template("visualizations/primitives.html").module
    assert 'filter=' not in module.watercolor_fill("example", "sage")
    path = "M10 100V25h30V100Z"
    root = ET.fromstring(f'<svg>{module.hand_drawn_stroke(path, echo_path="M11 99V26")}</svg>')
    assert root[0].attrib["d"] == path
    assert root[1].attrib["aria-hidden"] == "true"
    grid = str(module.ink_grid("custom", 10, 20, 300, 100, minor=10, major=50, vertical=False))
    assert 'width="10" height="10"' in grid
    assert 'width="50" height="50"' in grid
    assert 'M0 0V' not in grid
    paper = str(module.paper_surface(texture="none", transparent=True, caller=lambda: "content"))
    assert "viz-texture-none viz-transparent" in paper and "content" in paper
