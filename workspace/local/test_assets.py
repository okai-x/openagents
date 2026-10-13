from assets import reconcile


def test_divergent_changes_are_never_silently_overwritten():
    assert reconcile("base", "local edit", "remote edit") == "conflict"
    assert reconcile(None, "local", "remote") == "conflict"
    assert reconcile("base", None, "remote edit") == "conflict"


def test_only_one_changed_side_wins_and_equal_edits_converge():
    assert reconcile("base", "base", "remote edit") == "pull"
    assert reconcile("base", "local edit", "base") == "push"
    assert reconcile("base", "same edit", "same edit") == "same"
    assert reconcile(None, None, "new remote") == "pull"
    assert reconcile(None, "new local", None) == "push"
