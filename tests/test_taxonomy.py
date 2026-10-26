from src.read.text_utils import label_matches, load_taxonomy

TAX = load_taxonomy()
METRICS = {"ghg_scope1", "ghg_scope2_location", "ghg_scope2_market", "ghg_scope3", "ghg_total_location", "ghg_total_market"}


def test_six_metrics_with_required_fields():
    assert set(TAX) == METRICS
    for d in TAX.values():
        assert {"esrs", "unit", "description", "labels_seen", "not_this", "rules"} <= set(d)
        assert d["unit"] == "tCO2e"


def test_every_real_label_maps_to_exactly_its_metric():
    for metric, d in TAX.items():
        for label in d["labels_seen"]:
            assert [m for m in TAX if label_matches(TAX[m]["rules"], label)] == [metric], label


def test_look_alike_rows_are_rejected():
    for metric, d in TAX.items():
        for label in d["not_this"]:
            assert not label_matches(d["rules"], label), (metric, label)
