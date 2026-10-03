import json
import os
from datetime import datetime

import pytest

from motor.subtipo_cobro import detectar

PATH = os.path.join(os.path.dirname(__file__), "fixtures", "cobros_indebidos.json")
CASES = json.load(open(PATH, encoding="utf-8"))


def _load(t):
    return dict(t, transaction_date=datetime.fromisoformat(t["transaction_date"]))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_subtipo_cobro(case):
    subtype, _ = detectar(_load(case["selected"]), [_load(o) for o in case["others"]])
    assert subtype == case["expected"]


def test_fixtures_cubren_los_tres_subtipos():
    assert {c["expected"] for c in CASES} == {"comision", "duplicado", "compra"}
