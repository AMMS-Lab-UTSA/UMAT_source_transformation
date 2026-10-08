"""B20: an informativeness_not_established row says the gate was never measured."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.unit


def test_an_unmeasured_gate_is_not_worded_like_a_pass():
    import build_corpus_registry as reg
    text = reg.unmeasured_reason("4 of 4 chosen states judged and every entry agrees",
                                 "no state variable ... never measured")
    assert text.startswith("NOT A PASS: the mechanically_informative gate was never measured (null)")
    assert "every entry agrees" in text
