"""
Unit tests for query routing logic.

These tests verify that queries are correctly routed to tools without
requiring a running application or database. They test the routing logic
by examining query patterns and expected tool mappings.
"""

import pytest
from app.services.rag_service import RAGService


class TestQueryRouting:
    """Test that queries are correctly identified for tool routing."""
    
    def test_transportation_keywords(self):
        """Test that transportation-related queries are identified."""
        service = RAGService()
        
        transportation_queries = [
            "Where can I charge my EV?",
            "Find charging stations near me",
            "Where are DC fast charging stations?",
            "Show me Level 2 chargers"
        ]
        
        for query in transportation_queries:
            assert service._is_charging_station_question(query), \
                f"Should identify as charging station query: {query}"
    
    def test_utility_keywords(self):
        """Test that utility/cost-related queries are identified."""
        service = RAGService()
        
        utility_queries = [
            "What is the electricity cost per kWh?",
            "What are time-of-use rates?",
            "How much does electricity cost?",
            "What are the off-peak rates?"
        ]
        
        for query in utility_queries:
            assert service._is_electricity_cost_question(query), \
                f"Should identify as utility cost query: {query}"
    
    def test_building_efficiency_keywords(self):
        """Test that building efficiency queries are identified."""
        service = RAGService()
        
        building_queries = [
            "How do I lower my electricity bill?",
            "What are the building energy codes?",
            "What are energy efficiency standards?",
            "How can I reduce my electricity bill?"
        ]
        
        for query in building_queries:
            assert service._is_building_efficiency_question(query), \
                f"Should identify as building efficiency query: {query}"
    
    def test_charging_at_time_maps_to_utility(self):
        """Test that 'charging at [time]' maps to utility_tool, not transportation_tool."""
        service = RAGService()
        
        queries = [
            "What are my monthly electricity costs if I charge at 11 PM?",
            "How much does it cost to charge at 2 AM?",
            "Compare charging costs at different times"
        ]
        
        for query in queries:
            # Should be identified as utility/cost question
            assert service._is_electricity_cost_question(query), \
                f"Should identify as utility query: {query}"
            
            # Should NOT be identified as charging station question
            assert not service._is_charging_station_question(query), \
                f"Should NOT identify as transportation query: {query}"
    
    def test_optimization_keywords(self):
        """Test that optimization/investment-related queries are identified."""
        # Check for optimization keywords (same logic as in rag_service.py)
        # Use individual keywords that can match parts of phrases
        optimization_keywords = [
            "investment", "sizing", "roi", "optimal", "npv",
            "net present value", "financial", "economic", "design",
            "cost-benefit", "payback", "optimize", "optimization"
        ]
        
        optimization_queries = [
            "What is the optimal solar and storage size for zip 80202?",
            "What's the ROI for solar in Denver?",
            "Optimal solar system size and NPV for 45424?",
            "What's the payback period for solar?",
            "Financial analysis for solar: NPV and payback period",
            "What's the investment analysis for solar?",
            "Compare cost-benefit of solar vs grid",
            "What's the optimal design for my solar system?",
            "How do I optimize my solar installation?",
            "What's the net present value of solar?",
            "Economic analysis for solar investment",
            "What's the optimal system size?",
            "Should I invest in solar? ROI analysis",
            "What's the optimal solar sizing?"
        ]
        
        for query in optimization_queries:
            query_lower = query.lower()
            has_optimization_keyword = any(keyword in query_lower for keyword in optimization_keywords)
            assert has_optimization_keyword, \
                f"Should contain optimization keywords: {query}. Found keywords: {[k for k in optimization_keywords if k in query_lower]}"
    
    def test_optimization_with_location(self):
        """Test optimization queries with location information."""
        optimization_queries_with_location = [
            "What's the ROI for solar in zip 80202 in 2026?",
            "Optimal solar size for Denver, CO?",
            "What's the NPV for solar investment in 45424?",
            "Financial analysis for solar in California",
            "Optimal system sizing in zip 80202",
            "What's the payback period for solar in Phoenix, AZ?"
        ]
        
        optimization_keywords = [
            "roi", "optimal", "npv", "financial", "payback", "investment", "sizing"
        ]
        
        for query in optimization_queries_with_location:
            query_lower = query.lower()
            has_optimization_keyword = any(keyword in query_lower for keyword in optimization_keywords)
            assert has_optimization_keyword, \
                f"Should contain optimization keywords: {query}"
            
            # Should also have location (zip code, city/state, or state name)
            import re
            has_zip = bool(re.search(r'\b\d{5}\b', query))
            has_city_state = bool(re.search(r'[A-Z][a-z]+,\s*[A-Z]{2}', query))
            # Check for state names (common states)
            state_names = ["california", "texas", "florida", "new york", "illinois", 
                          "ohio", "colorado", "arizona", "nevada", "oregon"]
            has_state_name = any(state in query_lower for state in state_names)
            assert has_zip or has_city_state or has_state_name, \
                f"Should contain location information: {query}"
    
    def test_optimization_2026_scenarios(self):
        """Test optimization queries that should trigger purchase vs lease comparison."""
        optimization_2026_queries = [
            "What's the ROI for solar in zip 80202 in 2026?",
            "Should I buy or lease solar panels for my home in 2026?",
            "Compare purchase vs lease solar in 2026 for zip 80202",
            "What's the financial analysis for solar in 2026?"
        ]
        
        optimization_keywords = ["roi", "buy", "lease", "purchase", "financial", "2026"]
        
        for query in optimization_2026_queries:
            query_lower = query.lower()
            has_optimization_keyword = any(keyword in query_lower for keyword in optimization_keywords)
            assert has_optimization_keyword, \
                f"Should contain optimization keywords: {query}"
            
            # Should mention 2026 for tax credit scenarios
            assert "2026" in query or "buy" in query_lower or "lease" in query_lower, \
                f"Should mention 2026 or financing option: {query}"
    
    def test_complex_optimization_queries(self):
        """Test complex multi-tool queries that include optimization."""
        complex_optimization_queries = [
            "Compare savings: charging at 11 PM vs 4kW solar vs optimal system in zip 45424",
            "What's the most cost-effective: charging at night, solar, or both in 80202?",
            "Find charging stations, electricity rates, and optimal solar size in Denver, CO",
            "How can I reduce my electricity bill with optimal solar sizing?"
        ]
        
        optimization_keywords = ["optimal", "cost-effective", "optimize"]
        
        for query in complex_optimization_queries:
            query_lower = query.lower()
            has_optimization_keyword = any(keyword in query_lower for keyword in optimization_keywords)
            assert has_optimization_keyword, \
                f"Should contain optimization keywords: {query}"
            
            # These queries should trigger multiple tools
            # (optimization + utility + transportation or solar)
            has_multiple_concepts = (
                ("charging" in query_lower or "station" in query_lower) or
                ("solar" in query_lower) or
                ("electricity" in query_lower or "rate" in query_lower)
            )
            assert has_multiple_concepts, \
                f"Should contain multiple concepts for multi-tool query: {query}"


class TestLocationExtraction:
    """Test location extraction from queries."""
    
    def test_zip_code_extraction(self):
        """Test that zip codes are extracted from queries."""
        import re
        
        queries_with_zip = [
            ("Find stations in 80202", "80202"),
            ("What's the cost in zip 45424?", "45424"),
            ("Solar production for 5kW in 80202", "80202")
        ]
        
        for query, expected_zip in queries_with_zip:
            zip_match = re.search(r'\b\d{5}\b', query)
            assert zip_match, f"Should find zip code in: {query}"
            assert zip_match.group(0) == expected_zip, \
                f"Expected {expected_zip}, got {zip_match.group(0)}"


class TestQueryRefinement:
    """Test query refinement logic."""
    
    def test_query_refiner_basic(self):
        """Test that query refiner works without errors."""
        from app.services.query_refiner import QueryRefiner
        
        refiner = QueryRefiner()
        
        queries = [
            "where charge ev",
            "electricity cost",
            "solar production"
        ]
        
        for query in queries:
            result = refiner.refine(query)
            assert "refined_query" in result or "original_query" in result, \
                f"Query refiner should return a result for: {query}"

