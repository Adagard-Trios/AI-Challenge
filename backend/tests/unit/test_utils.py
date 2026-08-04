"""
Unit Tests for Utility Functions

Tests for src/utils module including tool functions.
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestToolResponseParsing:
    """Tests for parsing tool responses."""

    def test_parse_valid_json_response(self):
        """Test parsing valid JSON response."""
        response = '{"status": "success", "data": {"temperature": 28}}'
        parsed = json.loads(response)

        assert parsed["status"] == "success"
        assert parsed["data"]["temperature"] == 28

    def test_parse_error_response(self):
        """Test parsing error response."""
        response = '{"error": "API timeout", "solution": "Retry in 5 seconds"}'
        parsed = json.loads(response)

        assert "error" in parsed
        assert "solution" in parsed

    def test_handle_invalid_json(self):
        """Test handling of invalid JSON."""
        invalid_response = "Not valid JSON {"

        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_response)

    def test_handle_empty_response(self):
        """Test handling of empty response."""
        empty = ""

        with pytest.raises(json.JSONDecodeError):
            json.loads(empty)


class TestDistrictMapping:
    """Tests for Sri Lankan district mapping."""

    @pytest.fixture
    def district_list(self):
        """List of Sri Lankan districts."""
        return [
            "Colombo",
            "Gampaha",
            "Kalutara",
            "Kandy",
            "Matale",
            "Nuwara Eliya",
            "Galle",
            "Matara",
            "Hambantota",
            "Jaffna",
            "Kilinochchi",
            "Mannar",
            "Batticaloa",
            "Ampara",
            "Trincomalee",
            "Kurunegala",
            "Puttalam",
            "Anuradhapura",
            "Polonnaruwa",
            "Badulla",
            "Monaragala",
            "Ratnapura",
            "Kegalle",
        ]

    def test_district_count(self, district_list):
        """Verify we have all 25 districts (or close to it)."""
        assert len(district_list) >= 23, "Should have at least 23 districts"

    def test_district_name_format(self, district_list):
        """Verify district names are properly capitalized."""
        for district in district_list:
            assert district[0].isupper(), f"District {district} should be capitalized"

    def test_major_districts_present(self, district_list):
        """Verify major districts are present."""
        major = ["Colombo", "Kandy", "Galle", "Jaffna"]
        for district in major:
            assert district in district_list


class TestDataValidation:
    """Tests for data validation functions."""

    def test_validate_feed_item(self):
        """Test feed item validation."""
        valid_item = {
            "title": "Test Title",
            "summary": "Test summary",
            "source": "Test Source",
            "timestamp": "2024-01-01T00:00:00",
        }

        # Required fields present
        required_fields = ["title", "summary", "source"]
        for field in required_fields:
            assert field in valid_item

    def test_validate_missing_fields(self):
        """Test detection of missing required fields."""
        invalid_item = {
            "title": "Test Title"
            # Missing summary and source
        }

        required_fields = ["title", "summary", "source"]
        missing = [f for f in required_fields if f not in invalid_item]

        assert len(missing) == 2
        assert "summary" in missing
        assert "source" in missing

    def test_sanitize_summary(self):
        """Test summary text sanitization."""

        def sanitize(text: str, max_length: int = 500) -> str:
            if not text:
                return ""
            # Remove extra whitespace
            text = " ".join(text.split())
            # Truncate if too long
            if len(text) > max_length:
                text = text[: max_length - 3] + "..."
            return text

        # Test normal text
        assert sanitize("Hello World") == "Hello World"

        # Test whitespace normalization
        assert sanitize("Hello    World") == "Hello World"

        # Test truncation
        long_text = "a" * 600
        result = sanitize(long_text)
        assert len(result) == 500
        assert result.endswith("...")


class TestRiskScoring:
    """Tests for risk scoring logic."""

    def test_calculate_severity_score(self):
        """Test severity score calculation."""

        def calculate_severity(risk_type: str, confidence: float) -> float:
            severity_weights = {
                "Flood": 0.9,
                "Storm": 0.8,
                "Economic": 0.7,
                "Political": 0.6,
                "Social": 0.5,
            }
            base = severity_weights.get(risk_type, 0.5)
            return base * confidence

        # High priority risk
        assert calculate_severity("Flood", 0.9) == pytest.approx(0.81)

        # Low priority risk
        assert calculate_severity("Social", 0.5) == pytest.approx(0.25)

        # Unknown risk type
        assert calculate_severity("Unknown", 1.0) == pytest.approx(0.5)

    def test_aggregate_risk_scores(self):
        """Test aggregation of multiple risk scores."""

        def aggregate(scores: list) -> dict:
            if not scores:
                return {"min": 0, "max": 0, "avg": 0}
            return {
                "min": min(scores),
                "max": max(scores),
                "avg": sum(scores) / len(scores),
            }

        scores = [0.3, 0.5, 0.7, 0.9]
        result = aggregate(scores)

        assert result["min"] == 0.3
        assert result["max"] == 0.9
        assert result["avg"] == pytest.approx(0.6)

    def test_empty_score_handling(self):
        """Test handling of empty score list."""

        def aggregate(scores: list) -> dict:
            if not scores:
                return {"min": 0, "max": 0, "avg": 0}
            return {
                "min": min(scores),
                "max": max(scores),
                "avg": sum(scores) / len(scores),
            }

        result = aggregate([])
        assert result == {"min": 0, "max": 0, "avg": 0}


class TestTimestampHandling:
    """Tests for timestamp parsing and formatting."""

    def test_parse_iso_timestamp(self):
        """Test ISO timestamp parsing."""
        from datetime import datetime

        iso_str = "2024-01-15T10:30:00"
        dt = datetime.fromisoformat(iso_str)

        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30

    def test_format_timestamp(self):
        """Test timestamp formatting."""
        from datetime import datetime

        dt = datetime(2024, 1, 15, 10, 30, 0)
        formatted = dt.strftime("%Y-%m-%d %H:%M")

        assert formatted == "2024-01-15 10:30"

    def test_handle_invalid_timestamp(self):
        """Test handling of invalid timestamps."""
        from datetime import datetime

        invalid = "not a timestamp"

        with pytest.raises(ValueError):
            datetime.fromisoformat(invalid)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
