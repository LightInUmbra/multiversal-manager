import mtgjson
import sealed


def test_product_types_read_like_a_store_listing():
    assert mtgjson.product_type("booster_box", "collector") == "Collector Booster Box"
    assert mtgjson.product_type("bundle", "gift_bundle") == "Gift Bundle"
    assert mtgjson.product_type("bundle_case", "gift_bundle") == "Gift Bundle Case"
    assert mtgjson.product_type("deck_box", "starter_deck") == "Starter Deck Box"
    assert mtgjson.product_type("limited_aid_tool", "prerelease_kit") == "Prerelease Kit"
    assert mtgjson.product_type("box_set", "mtgo_redemption") == "MTGO Redemption Box Set"
    assert mtgjson.product_type("deck", "default") == "Deck"
    assert mtgjson.product_type("unknown", "commander") == "Commander"
    assert mtgjson.product_type(None, None) == "Other"
    assert (mtgjson.sealed_group("booster_case"), mtgjson.sealed_group("subset")) == ("Cases", "Other")


def test_sealed_entries_and_totals(temp_db):
    temp_db.replace_sealed_catalog([
        {"uuid": "a", "name": "Modern Horizons 3 Collector Booster Box", "set_code": "MH3",
         "set_name": "Modern Horizons 3", "product_type": "Collector Booster Box", "category": "Booster Boxes",
         "released": "2024-06-14"},
        {"uuid": "b", "name": "Foundations Bundle", "set_code": "FDN", "set_name": "Foundations",
         "product_type": "Bundle", "category": "Bundles", "released": "2024-11-15"},
    ])
    assert [r["name"] for r in temp_db.search_sealed_catalog("horizons collector")] == \
        ["Modern Horizons 3 Collector Booster Box"]
    assert [r["uuid"] for r in temp_db.search_sealed_catalog()] == ["b", "a"]   # newest first
    assert [r["uuid"] for r in temp_db.search_sealed_catalog(category="Bundles")] == ["b"]
    assert sorted(temp_db.sealed_categories()) == ["Booster Boxes", "Bundles"]

    box = temp_db.add_sealed(name="Modern Horizons 3 Collector Booster Box", uuid="a", quantity=2,
                             paid=300.0, value=380.0)
    temp_db.add_sealed(name="Mystery shoebox", value=50.0)        # custom, no paid price
    temp_db.update_sealed(box, quantity=3)
    count, value, paid, value_of_paid = temp_db.sealed_summary()
    assert (count, value, paid, value_of_paid) == (4, 3 * 380.0 + 50.0, 900.0, 1140.0)
    [entry] = [r for r in temp_db.get_sealed() if r["id"] == box]
    assert sealed.gain(entry) == 240.0
    temp_db.remove_sealed([box])
    assert [r["name"] for r in temp_db.get_sealed()] == ["Mystery shoebox"]
    assert sealed.gain(temp_db.get_sealed()[0]) is None           # nothing paid, no gain to show


def test_table_items_sort_by_number_or_text_without_crashing():
    # Text comparisons used to call super().__lt__, which recursed until the app crashed
    items = [sealed._item("bundle"), sealed._item("Booster Box"), sealed._item("collector box")]
    assert [i.text() for i in sorted(items)] == ["Booster Box", "bundle", "collector box"]
    prices = [sealed._item("$10.00", 10.0), sealed._item("$9.00", 9.0)]
    assert [i.text() for i in sorted(prices)] == ["$9.00", "$10.00"]
