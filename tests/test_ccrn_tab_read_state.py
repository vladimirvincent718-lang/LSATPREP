import subprocess


def test_section_read_unread_interactions():
    result = subprocess.run(
        ["node", "tests/js/ccrn_tab_read_state.cjs"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
