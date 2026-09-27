import json
import subprocess
from pathlib import Path
from src.utils import _SIDEBAR_PAGE_LABEL_CSS, _sidebar_page_label_js


def test_badges_move_inline_update_and_clear():
    script = Path(__file__).parent / 'js' / 'sidebar_badges.cjs'
    result = subprocess.run(['node', str(script)], input=json.dumps({
        'pending': _sidebar_page_label_js(140,450),
        'cleared': _sidebar_page_label_js(140,0),
    }), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ccrn_badge_uses_high_contrast_deep_amber():
    assert ".sf-review-nav-badge.sf-ccrn-nav-badge" in _SIDEBAR_PAGE_LABEL_CSS
    assert "background: #92400e !important" in _SIDEBAR_PAGE_LABEL_CSS
    assert "color: #ffffff !important" in _SIDEBAR_PAGE_LABEL_CSS

    def luminance(hex_color):
        channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

    lighter, darker = sorted((luminance("#92400e"), luminance("#ffffff")), reverse=True)
    assert (lighter + .05) / (darker + .05) >= 7
