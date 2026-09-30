"""A family denominator is only as good as the labels behind it.

Two classifications of this corpus exist side by side: one derived from keyword
markers, one where a reader decided each row from the code. They disagree, and
the disagreement moves denominators, not numerators -- the same sources read
"0 accepted of 22 viscoelastic" under the first and "0 accepted of 10" under
the second. A report that prints only the denominator lets either number be
quoted as if there were one answer.

So the report names the file it counted, digests it, and says how many labels
a reader actually decided -- per family, beside the count. An unreviewed
denominator has to look unreviewed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pass_report  # noqa: E402


def _registry(tmp_path, rows):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"records": rows}))
    return path


def _row(sid, *, accepted):
    # The registry writes each gate as a string, so a row built here has to as
    # well or it would pass a test the real data could not.
    gate = "true" if accepted else "false"
    row = {"source_id": sid, "adequately_specified": True, "is_umat": True,
           "terminal_state": "fully_verified" if accepted else "primal_disagreed",
           "kind": "internal", "verified_on_every_gate": accepted}
    row.update({f"gate_{name}": gate for name in pass_report.ACCEPTANCE_GATES})
    return row


def _families(tmp_path, rows, name="families.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"what_this_is": "a classification", "rows": rows}))
    return path


def test_the_report_counts_each_family_and_says_how_many_labels_were_reviewed(tmp_path):
    new = {"a": _row("a", accepted=True), "b": _row("b", accepted=False),
           "c": _row("c", accepted=False)}
    r = pass_report.report(new, None, {"a": "growth", "b": "growth", "c": "plasticity"},
                           families_reviewed={"b"})
    growth = r["families_d2"]["growth"]
    assert growth["accepted"] == 1
    assert growth["accepted"] + growth["not_accepted"] == 2
    assert growth["label_reviewed"] == 1
    assert "label_reviewed" not in r["families_d2"]["plasticity"]


def test_an_unreviewed_denominator_says_so_where_it_is_printed(tmp_path):
    new = {"a": _row("a", accepted=False), "b": _row("b", accepted=False)}
    families = {"a": "growth", "b": "growth"}
    unreviewed = pass_report.markdown("p", pass_report.report(new, None, families))
    assert "- growth: 0 accepted of 2 (0 of 2 labels reviewed)" in unreviewed

    reviewed = pass_report.markdown(
        "p", pass_report.report(new, None, families, families_reviewed={"a", "b"}))
    # Nothing to warn about once every label behind the number was decided.
    assert "- growth: 0 accepted of 2\n" in reviewed


def test_two_classifications_of_one_corpus_are_told_apart_by_the_basis(tmp_path):
    keyword = _families(tmp_path, [{"source_id": "a", "family": "viscoelasticity"}],
                        name="keyword.json")
    checked = _families(tmp_path, [{"source_id": "a", "family": "plasticity",
                                    "review": "checked", "basis": "reads a yield surface"}],
                        name="checked.json")
    reg = _registry(tmp_path, [_row("a", accepted=False)])

    bases = []
    for path in (keyword, checked):
        out = tmp_path / f"{path.stem}.md"
        pass_report.main.__globals__["sys"].argv = [
            "pass_report", "--registry", str(reg), "--families", str(path),
            "--markdown", str(out)]
        pass_report.main()
        bases.append(out.read_text())

    # The file is identified by its content, not by the name it was given.
    assert "sha256:" in bases[0] and "sha256:" in bases[1]
    assert bases[0] != bases[1]
    assert "0 decided from code evidence" in bases[0]
    assert "1 decided from code evidence" in bases[1]
    # And the same source lands in different families, which is the whole point.
    assert "viscoelasticity: 0 accepted of 1" in bases[0]
    assert "plasticity: 0 accepted of 1" in bases[1]
