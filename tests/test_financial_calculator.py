"""Regression checks for the browser-side financial calculator engine."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src import financial_calculator


CORE = Path(__file__).resolve().parents[1] / "assets" / "financial_calculator_core.js"


def _run_node(expression: str):
    if not shutil.which("node"):
        pytest.skip("Node.js is required to exercise the browser calculator engine")
    script = f"const m=require({json.dumps(str(CORE))}); console.log(JSON.stringify({expression}));"
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_tvm_payment_matches_reference_mortgage():
    payment = _run_node(
        "m.solveTvm('pmt',{n:360,iy:6,pv:300000,pmt:0,fv:0,py:12,begin:false})"
    )
    assert payment == pytest.approx(-1798.65157546)


def test_annuity_due_future_value():
    future_value = _run_node(
        "m.solveTvm('fv',{n:3,iy:8,pv:0,pmt:-10000,fv:0,py:1,begin:true})"
    )
    assert future_value == pytest.approx(35061.12)


def test_cash_flow_npv_and_irr():
    values = _run_node(
        "({npv:m.npv(10,-10000,[{value:3000,freq:1},{value:4000,freq:1},{value:5000,freq:1}]),"
        "irr:m.irr(-10000,[{value:3000,freq:1},{value:4000,freq:1},{value:5000,freq:1}])})"
    )
    assert values["npv"] == pytest.approx(-210.36814425)
    assert values["irr"] == pytest.approx(8.896339)


def test_calculator_injector_builds_collapsible_parent_drawer(monkeypatch):
    rendered = {}

    def capture(markup, **kwargs):
        rendered["markup"] = markup
        rendered["kwargs"] = kwargs

    monkeypatch.setattr(financial_calculator.components, "html", capture)
    financial_calculator.inject_financial_calculator()

    assert "sf-calc-fab" in rendered["markup"]
    assert "sf-calc-drawer" in rendered["markup"]
    assert "SFCalculatorMath" in rendered["markup"]
    assert "SFCalculatorKeyMap" in rendered["markup"]
    assert "fab.onclick=open" in rendered["markup"]
    assert "sf-calc-key.sf-num" in rendered["markup"]
    assert "AMORT" in rendered["markup"]
    assert "BRKEVN" in rendered["markup"]
    assert "background:transparent" in rendered["markup"]
    assert "sf_calc_y" in rendered["markup"]
    assert "sf-calc-page-open" in rendered["markup"]
    assert "--sf-calc-reserved" in rendered["markup"]
    assert "calc(100% - '+reserve+'px)" in rendered["markup"]
    assert "_sfCalcRestorePageSpace" in rendered["markup"]
    assert 'margin-right:0;visibility:hidden' not in rendered["markup"]
    assert "Keystroke history" not in rendered["markup"]
    assert rendered["kwargs"] == {"height": 0, "scrolling": False}
