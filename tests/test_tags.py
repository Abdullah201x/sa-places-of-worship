"""
tests/test_tags.py - Tests for tag directory schemas and rule linkage.

Verifies:
1. Every YAML in content/tags/*.yaml conforms to the TagDoc schema.
2. Every rule in validator.js (RULE_IDS) is covered by at least one tag file.
3. Every rule referenced in any tag file exists in RULE_IDS.
4. tags.json compiles properly and includes usage_sa.
"""

import glob
import json
import os
import re
import yaml
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAGS_DIR = os.path.join(ROOT_DIR, "content", "tags")
TAGS_JSON_PATH = os.path.join(ROOT_DIR, "tags.json")
VALIDATOR_PATH = os.path.join(ROOT_DIR, "frontend", "src", "validator.js")

ALLOWED_STATUSES = {
    "approved", "de facto", "in use", "deprecated", "discouraged", "discussion"
}
ALLOWED_OSM_TYPES = {"node", "way", "relation"}


def load_validator_rule_ids():
    with open(VALIDATOR_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    matches = re.findall(r"id:\s*'([a-z0-9_]+)'", text)
    assert matches, "Could not extract rule IDs from validator.js"
    return set(matches)


def load_all_tag_docs():
    tag_files = glob.glob(os.path.join(TAGS_DIR, "*.yaml"))
    assert len(tag_files) > 0, f"No tag files found in {TAGS_DIR}"
    docs = []
    for path in tag_files:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            data["_filename"] = os.path.basename(path)
            docs.append(data)
    return docs


def test_tag_files_exist():
    docs = load_all_tag_docs()
    assert len(docs) >= 10, f"Expected at least 10 tag files, got {len(docs)}"


def test_tag_doc_schema():
    docs = load_all_tag_docs()
    for doc in docs:
        fn = doc["_filename"]
        # Required fields
        assert "key" in doc, f"{fn} missing 'key'"
        assert "status" in doc, f"{fn} missing 'status'"
        assert doc["status"] in ALLOWED_STATUSES, f"{fn} has invalid status {doc['status']}"
        assert "applies_to" in doc, f"{fn} missing 'applies_to'"
        assert isinstance(doc["applies_to"], list), f"{fn} applies_to must be a list"
        for t in doc["applies_to"]:
            assert t in ALLOWED_OSM_TYPES, f"{fn} invalid osm type {t}"

        # Localized label and notes
        assert "label" in doc and "ar" in doc["label"] and "en" in doc["label"], f"{fn} missing localized label"
        assert "saudi_notes" in doc and "ar" in doc["saudi_notes"] and "en" in doc["saudi_notes"], f"{fn} missing localized saudi_notes"

        # Examples
        assert "examples" in doc, f"{fn} missing 'examples'"
        assert "good" in doc["examples"] and isinstance(doc["examples"]["good"], list), f"{fn} missing good examples"
        assert len(doc["examples"]["good"]) > 0, f"{fn} must have at least one good example"

        # If bad examples exist, check 'why' explanation
        if "bad" in doc["examples"]:
            for bad in doc["examples"]["bad"]:
                assert "why" in bad, f"{fn} bad example missing 'why'"
                assert "ar" in bad["why"] and "en" in bad["why"], f"{fn} bad example 'why' must be localized"


def test_rule_linkage_completeness():
    """CI Check: Every rule in validator.js has a tag page, and every tag page's rules exist."""
    validator_rules = load_validator_rule_ids()
    docs = load_all_tag_docs()

    referenced_rules = set()
    for doc in docs:
        rules = doc.get("rules", [])
        assert isinstance(rules, list), f"{doc['_filename']} rules must be a list"
        for r in rules:
            assert r in validator_rules, (
                f"Tag file {doc['_filename']} references rule '{r}', which is not in validator.js RULE_IDS"
            )
            referenced_rules.add(r)

    # Every validator rule must be covered by at least one tag doc
    uncovered = validator_rules - referenced_rules
    assert not uncovered, (
        f"The following rules in validator.js have no tag page covering them: {uncovered}"
    )


def test_compiled_tags_json():
    """Verify tags.json exists and contains compiled tag documents."""
    assert os.path.exists(TAGS_JSON_PATH), f"Expected {TAGS_JSON_PATH} to exist"
    with open(TAGS_JSON_PATH, "r", encoding="utf-8") as f:
        tags = json.load(f)
    assert len(tags) >= 10
    # Find amenity=place_of_worship
    pow_tag = next((t for t in tags if t.get("key") == "amenity" and t.get("value") == "place_of_worship"), None)
    assert pow_tag is not None
    assert "usage_sa" in pow_tag
    assert pow_tag["usage_sa"]["count"] > 10000
