import pytest

from datacraft.knowledge import pointer as jp

DOC = {"a": {"b/c": [1, None]}, "empty": [], "tins": {"United States": None}}


def test_walk_yields_containers_and_leaves():
    nodes = {p: (v, leaf) for p, v, leaf in jp.walk(DOC)}
    assert nodes["/a/b~1c/1"] == (None, True)
    assert nodes["/empty"] == ([], True)          # empty container is a meaningful leaf
    assert nodes["/a"][1] is False


def test_resolve_and_exists():
    assert jp.resolve(DOC, "/a/b~1c/0") == 1
    assert jp.resolve(DOC, "/tins/United States") is None
    assert jp.exists(DOC, "/tins/United States")      # present but null
    assert not jp.exists(DOC, "/tins/Germany")
    with pytest.raises(KeyError):
        jp.resolve(DOC, "/nope")
