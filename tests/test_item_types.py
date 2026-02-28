"""Tests for item type configs and title parsers."""

import pytest

from marketplace_appraiser.item_types import ITEM_TYPE_REGISTRY, get_config
from marketplace_appraiser.item_types._base import ItemTypeConfig
from marketplace_appraiser.item_types.electronics import parse_electronics_title
from marketplace_appraiser.item_types.furniture import parse_furniture_title
from marketplace_appraiser.item_types.vehicle import parse_vehicle_title


class TestRegistry:
    def test_all_types_present(self):
        assert "vehicle" in ITEM_TYPE_REGISTRY
        assert "electronics" in ITEM_TYPE_REGISTRY
        assert "furniture" in ITEM_TYPE_REGISTRY

    def test_get_config_valid(self):
        cfg = get_config("vehicle")
        assert isinstance(cfg, ItemTypeConfig)
        assert cfg.name == "vehicle"

    def test_get_config_invalid(self):
        with pytest.raises(KeyError, match="Unknown item type"):
            get_config("spaceship")

    def test_all_configs_have_required_fields(self):
        for name, cfg in ITEM_TYPE_REGISTRY.items():
            assert cfg.name == name
            assert cfg.display_name
            assert cfg.vision_checklist
            assert cfg.condition_role
            assert cfg.price_role
            assert isinstance(cfg.fraud_patterns, list)
            assert isinstance(cfg.market_search_templates, list)


class TestParseVehicleTitle:
    def test_basic(self):
        result = parse_vehicle_title("2015 Toyota Camry LE")
        assert result["year"] == 2015
        assert result["make"] == "Toyota"
        assert result["model"] == "Camry"

    def test_with_price(self):
        result = parse_vehicle_title("2020 Honda Civic - $15,000")
        assert result["year"] == 2020
        assert result["make"] == "Honda"
        assert result["model"] == "Civic"

    def test_multi_word_make(self):
        result = parse_vehicle_title("2018 Land Rover Discovery Sport")
        assert result["make"] == "Land Rover"

    def test_no_year(self):
        result = parse_vehicle_title("Honda Civic")
        assert result["year"] is None

    def test_empty(self):
        result = parse_vehicle_title("")
        assert result["year"] is None
        assert result["make"] is None
        assert result["model"] is None


class TestParseElectronicsTitle:
    def test_iphone(self):
        result = parse_electronics_title("Apple iPhone 14 Pro Max 256GB")
        assert result["brand"] == "Apple"
        assert "iPhone" in result["product"]

    def test_samsung_tv(self):
        result = parse_electronics_title("Samsung 65 inch 4K Smart TV")
        assert result["brand"] == "Samsung"

    def test_gaming_console(self):
        result = parse_electronics_title("Sony PlayStation 5 PS5 Disc Edition")
        assert result["brand"] == "Sony"

    def test_unknown_brand(self):
        # Unknown brands get first word as brand
        result = parse_electronics_title("Random Gadget Thing")
        assert result["brand"] == "Random"

    def test_empty(self):
        result = parse_electronics_title("")
        assert result["brand"] is None
        assert result["product"] is None


class TestParseFurnitureTitle:
    def test_ikea(self):
        result = parse_furniture_title("IKEA KALLAX Shelf Unit")
        assert result["brand"] == "IKEA"

    def test_with_material(self):
        result = parse_furniture_title("Solid Oak Dining Table")
        assert result["material"] == "Oak"

    def test_with_type(self):
        result = parse_furniture_title("Leather Sectional Sofa")
        # "sectional" is longer than "sofa" and appears first in sorted list
        assert result["furniture_type"] in ("Sofa", "Sectional")

    def test_empty(self):
        result = parse_furniture_title("")
        assert result["brand"] is None
        assert result["furniture_type"] is None


class TestConfigProperties:
    def test_vehicle_has_safety_api(self):
        cfg = get_config("vehicle")
        assert cfg.safety_api == "nhtsa"

    def test_electronics_no_safety_api(self):
        cfg = get_config("electronics")
        assert cfg.safety_api is None

    def test_furniture_has_safety_api(self):
        cfg = get_config("furniture")
        assert cfg.safety_api == "cpsc"

    def test_all_have_parse_title(self):
        for name, cfg in ITEM_TYPE_REGISTRY.items():
            assert cfg.parse_title is not None, f"{name} missing parse_title"
            result = cfg.parse_title("Test Item Title")
            assert isinstance(result, dict)
