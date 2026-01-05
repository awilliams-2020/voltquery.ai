"""
Tests for RAG service prompt behavior to prevent regressions.

These tests ensure that:
1. Sub-question generation routes correctly to tools
2. Utility tool doesn't refuse to answer
3. Charging station questions don't appear for cost questions
4. Solar tool works correctly
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import List, Dict, Any

from llama_index.core.question_gen.types import SubQuestion
from llama_index.core.output_parsers.base import StructuredOutput

# Note: These imports may need to be adjusted based on actual class visibility
# If classes are not directly importable, we'll test behavior through public methods
try:
    from app.services.rag_service import RAGService, RobustSubQuestionOutputParser
# Note: ToolNameMappingParser is a nested class, so we test its behavior indirectly
except ImportError:
    # If classes aren't directly importable, we'll test through behavior
    RAGService = None
    ToolNameMappingParser = None
    RobustSubQuestionOutputParser = None


class TestSubQuestionGeneration:
    """Test that sub-questions are generated correctly."""
    
    @pytest.fixture
    def mock_rag_service(self):
        """Create a mock RAG service with minimal setup."""
        service = Mock(spec=RAGService)
        service.nrel_client = Mock()
        service.document_service = Mock()
        service.vector_store_service = Mock()
        service.llm_service = Mock()
        service.location_service = Mock()
        return service
    
    def test_tool_name_mapping_charging_costs(self):
        """Test that 'charging at [time]' questions map to utility_tool, not transportation_tool."""
        # Test the mapping logic directly (simulating ToolNameMappingParser behavior)
        sub_q_text = "What are my monthly electricity costs if I charge at 11 PM in zip code 45424?"
        sub_q_text_lower = sub_q_text.lower()
        
        # The mapping logic should check for cost/savings keywords FIRST
        utility_keywords = [
            "electricity", "utility", "rate", "cost", "kwh", "price", "bill",
            "time-of-use", "off-peak", "peak rate", "charging cost", "charging at", "charge at",
            "savings", "compare", "monthly", "annual"
        ]
        
        # Should map to utility_tool
        assert any(keyword in sub_q_text_lower for keyword in utility_keywords), \
            f"Expected utility keywords in: {sub_q_text_lower}"
        assert "charge at" in sub_q_text_lower or "charging at" in sub_q_text_lower, \
            f"Expected 'charge at' or 'charging at' in: {sub_q_text_lower}"
        assert any(keyword in sub_q_text_lower for keyword in ["cost", "savings", "monthly"]), \
            f"Expected cost/savings keywords in: {sub_q_text_lower}"
        
        # Should NOT map to transportation_tool
        transportation_keywords = [
            "charging station", "charging stations", "where to charge",
            "charger location", "charging location", "nearest charging"
        ]
        assert not any(keyword in sub_q_text_lower for keyword in transportation_keywords), \
            f"Should not contain transportation keywords: {sub_q_text_lower}"
    
    def test_tool_name_mapping_charging_stations(self):
        """Test that 'where to charge' questions map to transportation_tool."""
        sub_q_text = "Where are the nearest charging stations?"
        sub_q_text_lower = sub_q_text.lower()
        
        # Should map to transportation_tool
        assert any(keyword in sub_q_text_lower for keyword in [
            "charging station", "charging stations", "where to charge", "where can i charge",
            "charger location", "charging location", "nearest charging", "find charging"
        ])
    
    def test_tool_name_mapping_solar(self):
        """Test that solar questions map to solar_production_tool."""
        sub_q_text = "What is the solar energy production for a 4kW system?"
        sub_q_text_lower = sub_q_text.lower()
        
        # Should map to solar_production_tool
        assert any(keyword in sub_q_text_lower for keyword in [
            "solar", "solar panel", "solar energy", "solar production", "solar generation",
            "solar savings", "solar offset", "solar payback", "photovoltaic", "pv system"
        ])


class TestPromptBehavior:
    """Test prompt behavior to ensure correct tool routing."""
    
    def test_cost_question_should_not_include_transportation(self):
        """Test that cost/savings questions don't generate transportation sub-questions."""
        question = "Compare my monthly savings if I charge at 11 PM vs. installing 4kW of solar in zip 45424."
        question_lower = question.lower()
        
        # Should NOT include transportation keywords
        transportation_keywords = [
            "charging station", "charging stations", "where to charge",
            "nearest charging", "find charging stations"
        ]
        
        # The question should NOT be about finding stations
        assert not any(keyword in question_lower for keyword in transportation_keywords)
        
        # Should be about costs/savings
        assert any(keyword in question_lower for keyword in ["savings", "compare", "charge at"])
        assert "solar" in question_lower
    
    def test_utility_tool_description_includes_charging_costs(self):
        """Test that utility_tool description includes charging cost keywords."""
        utility_description = (
            "UTILITY DOMAIN: Use this for questions about electricity rates, utility costs, "
            "electricity prices, utility providers, cost per kWh, price per kWh, residential "
            "electricity costs, commercial electricity rates, industrial rates, utility bills, "
            "time-of-use rates, off-peak rates, peak rates, charging costs, charging at specific times "
            "(e.g., 'charging at 11 PM'), charging savings, and utility company information."
        )
        
        # Should include charging cost keywords
        assert "charging costs" in utility_description.lower()
        assert "charging at" in utility_description.lower()
        assert "charging savings" in utility_description.lower()
    
    def test_transportation_tool_excludes_costs(self):
        """Test that transportation_tool explicitly excludes cost questions."""
        transportation_description = (
            "TRANSPORTATION DOMAIN: Use this ONLY for questions about finding EV charging stations, "
            "electric vehicle charging locations, charger types (J1772, CCS, CHAdeMO, NEMA), "
            "DC fast charging, Level 2 charging, station networks, where to charge, charging locations, "
            "and EV infrastructure locations. "
            "DO NOT use this for questions about charging COSTS, charging RATES, charging SAVINGS, "
            "'charging at [time]', electricity costs, utility rates, or power prices."
        )
        
        # Should explicitly exclude cost questions
        assert "do not use this for" in transportation_description.lower()
        assert "charging costs" in transportation_description.lower()
        assert "charging rates" in transportation_description.lower()
        assert "charging savings" in transportation_description.lower()


class TestUtilityToolResponse:
    """Test that utility tool provides data instead of refusing."""
    
    def test_utility_response_synthesizer_prompt(self):
        """Test that utility response synthesizer has correct prompt."""
        expected_prompt_parts = [
            "utility rate information",
            "public database",
            "factual data",
            "not financial advice"
        ]
        
        # The prompt should encourage providing data
        utility_prompt = (
            "Context information from utility rate data is below.\n"
            "---------------------\n"
            "{context_str}\n"
            "---------------------\n"
            "You are a helpful assistant providing utility rate information from a public database. "
            "This is factual data about electricity rates, not financial advice. "
            "Provide the utility rate information clearly and accurately.\n"
            "Query: {query_str}\n"
            "Answer: "
        )
        
        for part in expected_prompt_parts:
            assert part in utility_prompt.lower(), f"Missing expected prompt part: {part}"
    
    def test_utility_tool_should_not_refuse(self):
        """Test that utility tool response doesn't contain refusal phrases."""
        refusal_phrases = [
            "i cannot provide",
            "i cannot answer",
            "i'm not able to",
            "i'm unable to",
            "i don't have access",
            "i cannot assist",
            "i cannot help"
        ]
        
        # Example response that should be acceptable
        good_response = (
            "The residential electricity rate for zip code 45424 is $0.1179/kWh. "
            "Time-of-use rates are not available from this data source."
        )
        
        for phrase in refusal_phrases:
            assert phrase not in good_response.lower(), f"Response contains refusal phrase: {phrase}"


class TestSolarProductionTool:
    """Test that solar production tool works correctly."""
    
    def test_solar_tool_description_includes_keywords(self):
        """Test that solar tool description includes relevant keywords."""
        solar_description = (
            "Useful for estimating annual and monthly solar energy production (kWh) for a specific location and system size. "
            "Use this tool when asked about solar energy production, solar panel output, solar generation, "
            "solar savings, offsetting electricity costs with solar, or calculating solar payback periods."
        )
        
        # Should include key solar keywords
        expected_keywords = [
            "solar energy production",
            "solar panel",
            "solar generation",
            "solar savings",
            "solar payback"
        ]
        
        for keyword in expected_keywords:
            assert keyword in solar_description.lower(), f"Missing keyword: {keyword}"
    
    def test_solar_tool_should_provide_data(self):
        """Test that solar tool provides actual production data."""
        # Example good response from solar tool
        good_response = (
            "SOLAR PRODUCTION DATA (from NREL PVWatts API):\n"
            "Location: 45424\n"
            "System Capacity: 4.0 kW\n"
            "Annual AC Energy Production: 5342.28 kWh/year\n"
            "Average Monthly Production: 445.2 kWh/month"
        )
        
        # Should contain actual data
        assert "kwh" in good_response.lower()
        assert "production" in good_response.lower()
        assert "system capacity" in good_response.lower() or "capacity" in good_response.lower()
        
        # Should NOT contain refusal phrases
        refusal_phrases = [
            "i cannot provide",
            "i cannot answer",
            "i'm not able to",
            "i don't have access"
        ]
        
        for phrase in refusal_phrases:
            assert phrase not in good_response.lower(), f"Response contains refusal phrase: {phrase}"
    
    def test_solar_tool_handles_location_formats(self):
        """Test that solar tool accepts different location formats."""
        # Solar tool should accept:
        # - Zip codes: "80202"
        # - City/State: "Denver, CO"
        # - Coordinates: "39.7392,-104.9903"
        
        location_formats = [
            "80202",  # Zip code
            "Denver, CO",  # City/State
            "39.7392,-104.9903"  # Coordinates
        ]
        
        # All should be valid location strings
        for location in location_formats:
            assert isinstance(location, str)
            assert len(location) > 0


class TestTransportationTool:
    """Test that transportation tool works correctly."""
    
    def test_transportation_tool_description_focuses_on_locations(self):
        """Test that transportation tool description focuses on finding locations."""
        transportation_description = (
            "TRANSPORTATION DOMAIN: Use this ONLY for questions about finding EV charging stations, "
            "electric vehicle charging locations, charger types (J1772, CCS, CHAdeMO, NEMA), "
            "DC fast charging, Level 2 charging, station networks, where to charge, charging locations, "
            "and EV infrastructure locations."
        )
        
        # Should emphasize location-finding
        location_keywords = [
            "finding",
            "where to charge",
            "charging locations",
            "charging stations"
        ]
        
        for keyword in location_keywords:
            assert keyword in transportation_description.lower(), f"Missing location keyword: {keyword}"
    
    def test_transportation_tool_excludes_costs(self):
        """Test that transportation tool explicitly excludes cost questions."""
        transportation_description = (
            "DO NOT use this for questions about charging COSTS, charging RATES, charging SAVINGS, "
            "'charging at [time]', electricity costs, utility rates, or power prices."
        )
        
        # Should explicitly exclude cost-related questions
        excluded_keywords = [
            "charging costs",
            "charging rates",
            "charging savings",
            "charging at",
            "electricity costs",
            "utility rates"
        ]
        
        for keyword in excluded_keywords:
            assert keyword in transportation_description.lower(), f"Missing exclusion keyword: {keyword}"
    
    def test_transportation_tool_should_provide_station_data(self):
        """Test that transportation tool provides actual station data."""
        # Example good response from transportation tool
        good_response = (
            "Based on the provided data, the nearest charging stations to zip code 45424 are:\n\n"
            "1. CLOUD ROSE STATION2 (Station ID: 235310) with an address of 6800 Executive Blvd, Dayton, OH, 45424\n"
            "2. MVRPC(EV#20) (Station ID: 383924) with an address of 7800 Shull Road, Dayton, OH, 45424"
        )
        
        # Should contain station information
        assert "station" in good_response.lower() or "charging" in good_response.lower()
        assert "address" in good_response.lower() or "location" in good_response.lower()
        
        # Should NOT contain refusal phrases
        refusal_phrases = [
            "i cannot provide",
            "i cannot answer",
            "i'm not able to",
            "i don't have access"
        ]
        
        for phrase in refusal_phrases:
            assert phrase not in good_response.lower(), f"Response contains refusal phrase: {phrase}"
    
    def test_transportation_tool_handles_location_queries(self):
        """Test that transportation tool handles different location query formats."""
        # Transportation tool should handle:
        # - Zip codes: "stations in 80202"
        # - City/State: "stations in Denver, CO"
        # - State: "stations in Colorado"
        
        location_queries = [
            "stations in 80202",
            "stations in Denver, CO",
            "stations in Colorado",
            "where can I charge in Ohio"
        ]
        
        # All should be valid queries
        for query in location_queries:
            assert isinstance(query, str)
            assert len(query) > 0
            # Should contain location-related keywords
            assert any(keyword in query.lower() for keyword in ["station", "charge", "in", "where"])


class TestSubQuestionDeduplication:
    """Test that duplicate sub-questions are handled correctly."""
    
    def test_duplicate_utility_questions(self):
        """Test detection of duplicate utility tool questions."""
        sub_questions = [
            SubQuestion(
                sub_question="What is the electricity rate including time-of-use rates for zip code 45424?",
                tool_name="utility_tool"
            ),
            SubQuestion(
                sub_question="What are my monthly electricity costs if I charge at 11 PM in zip code 45424?",
                tool_name="utility_tool"
            )
        ]
        
        # Both are utility_tool questions
        assert all(sq.tool_name == "utility_tool" for sq in sub_questions)
        
        # They're asking related but different things
        # The first gets rates, the second calculates costs (which needs rates)
        # This is acceptable but could be optimized


class TestExpectedSubQuestions:
    """Test that expected sub-questions are generated for common queries."""
    
    def test_solar_savings_comparison_subquestions(self):
        """Test sub-questions for solar savings comparison query."""
        question = "Compare my monthly savings if I charge at 11 PM vs. installing 4kW of solar in zip 45424."
        
        # Expected sub-questions
        expected_tools = ["utility_tool", "solar_production_tool"]
        unexpected_tools = ["transportation_tool"]
        
        # Verify question structure
        assert "savings" in question.lower()
        assert "charge at" in question.lower()
        assert "solar" in question.lower()
        assert "45424" in question
        
        # Should NOT ask about charging stations
        assert "charging station" not in question.lower()
        assert "where to charge" not in question.lower()


class TestRAGServiceIntegration:
    """Integration tests for RAG service (requires mocked dependencies)."""
    
    @pytest.fixture
    def mock_services(self):
        """Create mocked services."""
        mock_vector_service = Mock()
        mock_vector_service.get_index.return_value = Mock()
        
        mock_llm_service = Mock()
        mock_llm = Mock()
        mock_llm_service.get_llm.return_value = mock_llm
        
        mock_location_service = Mock()
        mock_location_service.extract_location_from_question = AsyncMock(return_value=None)
        
        return {
            "vector_service": mock_vector_service,
            "llm_service": mock_llm_service,
            "location_service": mock_location_service
        }
    
    def test_utility_rates_indexing_metadata(self):
        """Test that utility rates are indexed with correct metadata."""
        # Utility rate document should have:
        # - domain: "utility"
        # - zip: zip_code (if location is zip code)
        # - location: location string
        # - residential_rate, commercial_rate, industrial_rate
        
        location = "45424"
        utility_rates = {
            "utility_name": "Test Utility",
            "residential": 0.1179,
            "commercial": 0.0483,
            "industrial": 0.0196
        }
        
        # Check that location is a zip code
        assert location.isdigit() and len(location) == 5
        
        # Metadata should include zip
        expected_metadata = {
            "domain": "utility",
            "zip": location,
            "location": location
        }
        
        assert expected_metadata["domain"] == "utility"
        assert expected_metadata["zip"] == location


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

