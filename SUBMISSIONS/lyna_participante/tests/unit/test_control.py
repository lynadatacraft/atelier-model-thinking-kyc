"""Control assessment on synthetic records: ownership, votes and control are distinct."""

from datacraft.knowledge.control import assess
from datacraft.models import Evidence, SourceRole


def ev_for(name):
    def ev(key):
        return [Evidence(source="ownership.md", json_pointer=f"/people/0/{key}", excerpt=f"{name}.{key}",
                         role=SourceRole.PRIMARY, sha256="0")]
    return ev


LISTED = [Evidence(source="ownership.md", json_pointer="/people/0", excerpt="listed", role=SourceRole.PRIMARY, sha256="0")]
REL_EV = [Evidence(source="person_relationships.json", json_pointer="/0", excerpt="rel",
                   role=SourceRole.SUBJECT_RECORD, sha256="0")]


def test_zero_ownership_with_documented_contractual_control_is_controlling():
    record = {"direct_pct": 0, "indirect_pct": 0, "votes_pct": 0,
              "control_basis": "Contractual right to appoint/remove a majority of the board"}
    a = assess("X", record, [({"relationship_type": "controller_of", "control_basis": record["control_basis"]}, REL_EV)],
               LISTED, ev_for("X"))
    assert a.is_controlling and a.control_types == ["B"]
    assert a.total_ownership.result == 0 and a.voting_rights.value == 0
    assert a.contractual_control and a.board_appointment_rights


def test_person_with_0_ownership_and_no_control_is_not_controlling():
    a = assess("Y", {"direct_pct": 0, "indirect_pct": 0, "votes_pct": 0}, [], LISTED, ev_for("Y"))
    assert not a.is_controlling and a.control_types == [] and a.control_basis is None


def test_person_with_ownership_but_no_documented_control_gets_no_contractual_control():
    a = assess("Z", {"direct_pct": 60, "indirect_pct": 0, "votes_pct": 60}, [({"relationship_type": "ubo_of",
                                                                                "control_basis": None}, REL_EV)],
               LISTED, ev_for("Z"))
    assert a.is_controlling and a.control_types == ["A"]
    assert a.control_basis is None and not a.contractual_control and not a.board_appointment_rights


def test_ownership_without_any_documented_relationship_is_not_control():
    a = assess("W", {"direct_pct": 60, "indirect_pct": 0, "votes_pct": 60}, [], [], ev_for("W"))
    assert not a.is_controlling and "no documented" in a.reason


def test_votes_alone_above_threshold_is_type_a():
    a = assess("V", {"direct_pct": 10, "indirect_pct": 0, "votes_pct": 51}, [], LISTED, ev_for("V"))
    assert a.control_types == ["A"] and a.total_ownership.result == 10    # capital is not replaced by votes


def test_threshold_is_strictly_more_than_25():
    a = assess("T", {"direct_pct": 25, "indirect_pct": 0, "votes_pct": 25}, [], LISTED, ev_for("T"))
    assert not a.is_controlling


def test_direct_and_indirect_are_kept_and_summed_explicitly():
    a = assess("U", {"direct_pct": 20, "indirect_pct": 15, "votes_pct": 35}, [], LISTED, ev_for("U"))
    assert (a.direct_ownership.value, a.indirect_ownership.value) == (20, 15)
    assert a.total_ownership.formula == "direct_pct + indirect_pct" and a.total_ownership.result == 35
    assert [e.json_pointer for i in a.total_ownership.inputs for e in i.evidence] == ["/people/0/direct_pct",
                                                                                      "/people/0/indirect_pct"]
