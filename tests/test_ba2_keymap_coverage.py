"""Full visible-key coverage using the calculator's generated DOM handlers."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.financial_calculator import _LOGIC


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "calculator_dom_harness.js"


SEQUENCES = [
    {"name": "sign_entry", "keys": ["1", "0", "0", "sign"]},
    {"name": "clear_tvm", "keys": ["5", "n", "2nd", "fv"]},
    {"name": "payments_compounding", "keys": ["2nd", "iy", "1", "2", "enter", "down", "4", "enter"]},
    {"name": "begin_mode", "keys": ["2nd", "pmt", "2nd", "enter"]},
    {
        "name": "cashflow_npv",
        "keys": [
            "cf", "7", "0", "0", "0", "sign", "enter", "down",
            "3", "0", "0", "0", "enter", "down", "down",
            "4", "0", "0", "0", "enter", "down", "down",
            "5", "0", "0", "0", "enter", "down", "4", "enter",
            "npv", "2", "0", "enter", "down", "cpt",
        ],
    },
    {"name": "memory", "keys": ["4", "2", "sto", "3", "clear", "rcl", "3"]},
    {"name": "clear_cashflow", "keys": ["cf", "1", "0", "0", "enter", "2nd", "rcl"]},
    {"name": "clear_tvm_preserves_settings", "keys": ["2nd", "iy", "1", "2", "enter", "2nd", "cpt", "2nd", "pmt", "2nd", "enter", "2nd", "cpt", "5", "n", "2nd", "fv"]},
    {"name": "worksheet_clear_isolation", "keys": ["9", "n", "4", "2", "sto", "3", "cf", "1", "0", "0", "enter", "2nd", "rcl"]},
    {"name": "last_answer", "keys": ["2", "+", "3", "=", "clear", "2nd", "="]},
    {"name": "decimal_format", "keys": ["2nd", ".", "4", "enter", "2nd", "cpt", "2", "÷", "3", "="]},
]


@pytest.fixture(scope="module")
def dom_results():
    if not shutil.which("node"):
        pytest.skip("Node.js is required for DOM-level calculator coverage")
    payload = {
        "logic": _LOGIC,
        "corePath": str(ROOT / "assets" / "financial_calculator_core.js"),
        "keymapPath": str(ROOT / "assets" / "financial_calculator_keymap.js"),
        "sequences": SEQUENCES,
    }
    result = subprocess.run(
        ["node", str(HARNESS)],
        input=json.dumps(payload),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_every_visible_primary_key_clicks_its_declared_action(dom_results):
    coverage = dom_results["primaryCoverage"]
    assert len(coverage) == 44
    assert len({row["primary"] for row in coverage}) == 44
    for row in coverage:
        assert row["dispatch"] == f'primary:{row["primary"]}'


def test_every_yellow_secondary_label_clicks_its_declared_action(dom_results):
    coverage = dom_results["secondaryCoverage"]
    assert len(coverage) == 31
    assert len({row["label"] for row in coverage}) == 31
    for row in coverage:
        assert row["dispatch"] == f'secondary:{row["action"]}'


def test_sign_entry_trace(dom_results):
    final = dom_results["traces"]["sign_entry"][-1]
    assert final["display"] == "-100"
    assert final["state"]["input"] == "-100"


def test_clear_tvm_trace_and_intermediate_second_indicator(dom_results):
    trace = dom_results["traces"]["clear_tvm"]
    assert trace[1]["state"]["tvm"]["n"] == 5
    assert "2nd" in trace[2]["indicators"]
    assert trace[-1]["state"]["tvm"] | {"py": 1, "cy": 1, "begin": False} == {
        "n": 0, "iy": 0, "pv": 0, "pmt": 0, "fv": 0, "py": 1, "cy": 1, "begin": False
    }


def test_payments_per_year_and_compounding_per_year_trace(dom_results):
    trace = dom_results["traces"]["payments_compounding"]
    assert trace[1]["state"]["mode"] == "py"
    assert trace[4]["state"]["tvm"]["py"] == 12
    assert trace[4]["state"]["tvm"]["cy"] == 12
    assert trace[-1]["state"]["tvm"]["cy"] == 4


def test_end_begin_trace(dom_results):
    trace = dom_results["traces"]["begin_mode"]
    assert trace[1]["display"] == "END"
    assert trace[-1]["state"]["tvm"]["begin"] is True
    assert "BGN" in trace[-1]["indicators"]


def test_literal_cashflow_npv_trace(dom_results):
    final = dom_results["traces"]["cashflow_npv"][-1]
    assert final["state"]["cash"]["cf0"] == -7000
    assert final["state"]["cash"]["groups"] == [
        {"value": 3000, "frequency": 1},
        {"value": 4000, "frequency": 1},
        {"value": 5000, "frequency": 4},
    ]
    assert final["state"]["npvResult"] == pytest.approx(7266.4394718793)
    assert final["display"] == "NPV = 7,266.44"


def test_memory_persistence_and_recall_trace(dom_results):
    final = dom_results["traces"]["memory"][-1]
    assert final["state"]["mem"][3] == 42
    assert final["state"]["input"] == "42"
    assert final["display"] == "42.00"


def test_registers_persist_when_the_ui_engine_is_recreated(dom_results):
    persistence = dom_results["persistence"]
    assert persistence["beforeRecreation"]["state"]["mem"][3] == 42
    assert persistence["beforeRecreation"]["state"]["tvm"]["n"] == 5
    assert persistence["afterRecreation"]["state"]["mem"][3] == 42
    assert persistence["afterRecreation"]["state"]["tvm"]["n"] == 5


def test_drawer_reserves_and_restores_test_area_width(dom_results):
    layout = dom_results["layout"]
    assert layout["openLayout"]["width"] == "calc(100% - 368px)"
    assert layout["openLayout"]["margin-right"] == "368px"
    assert "width" not in layout["closedLayout"]
    assert "margin-right" not in layout["closedLayout"]
    assert layout["expandedLayout"]["width"] == "calc(100% - 458px)"
    assert layout["expandedLayout"]["margin-right"] == "458px"


def test_clear_work_only_clears_current_cashflow_worksheet(dom_results):
    final = dom_results["traces"]["clear_cashflow"][-1]
    assert final["state"]["cash"] == {"cf0": 0, "groups": []}
    assert final["state"]["mode"] == "cf"


def test_clear_tvm_preserves_payment_and_begin_settings(dom_results):
    final = dom_results["traces"]["clear_tvm_preserves_settings"][-1]["state"]
    assert {name: final["tvm"][name] for name in ("n", "iy", "pv", "pmt", "fv")} == {
        "n": 0, "iy": 0, "pv": 0, "pmt": 0, "fv": 0
    }
    assert final["tvm"]["py"] == 12
    assert final["tvm"]["cy"] == 12
    assert final["tvm"]["begin"] is True


def test_clear_work_does_not_erase_tvm_or_memory(dom_results):
    final = dom_results["traces"]["worksheet_clear_isolation"][-1]["state"]
    assert final["cash"] == {"cf0": 0, "groups": []}
    assert final["tvm"]["n"] == 9
    assert final["mem"][3] == 42


def test_last_answer_trace(dom_results):
    final = dom_results["traces"]["last_answer"][-1]
    assert final["state"]["lastAnswer"] == 5
    assert final["display"] == "5.00"


def test_decimal_format_and_rounding_trace(dom_results):
    final = dom_results["traces"]["decimal_format"][-1]
    assert final["state"]["format"]["decimals"] == 4
    assert final["display"] == "0.6667"
