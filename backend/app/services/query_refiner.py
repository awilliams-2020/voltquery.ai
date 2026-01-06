"""
Query refinement service for improving RAG retrieval quality.

Preprocesses and refines user queries to improve retrieval accuracy.
"""

import re
from typing import Dict, Any, Optional
from app.services.logger_service import get_logger


class QueryRefiner:
    """
    Service for refining user queries to improve retrieval quality.
    
    Performs:
    - Abbreviation expansion
    - Location normalization
    - Entity extraction
    - Query expansion with synonyms
    """
    
    # Common abbreviations and their expansions
    ABBREVIATIONS = {
        "ev": "electric vehicle",
        "evs": "electric vehicles",
        "ev charging": "electric vehicle charging",
        "dc fast": "direct current fast charging",
        "level 2": "level 2 charging",
        "kwh": "kilowatt hour",
        "kw": "kilowatt",
        "solar pv": "solar photovoltaic",
        "pv": "photovoltaic",
        "tou": "time-of-use",
        "to-u": "time-of-use",
        "off-peak": "off peak",
        "peak rate": "peak electricity rate",
        "utility rate": "electricity utility rate",
        "electricity cost": "electricity price cost",
        "energy efficiency": "energy efficient",
        "building code": "building energy code",
        "iecc": "international energy conservation code",
        "ashrae": "american society of heating refrigerating and air conditioning engineers"
    }
    
    # Location-related keywords
    LOCATION_KEYWORDS = [
        "in", "near", "around", "within", "at", "located", "location",
        "zip", "zip code", "city", "state", "address"
    ]
    
    # Question type indicators
    QUESTION_TYPES = {
        "cost": ["cost", "price", "rate", "bill", "expensive", "cheap", "affordable"],
        "location": ["where", "location", "near", "close", "find", "locate"],
        "availability": ["available", "exist", "have", "has", "number", "count", "how many"],
        "comparison": ["compare", "difference", "versus", "vs", "better", "best"],
        "efficiency": ["efficient", "efficiency", "save", "reduce", "lower", "improve"]
    }
    
    def __init__(self):
        """Initialize query refiner."""
        self.logger = get_logger("query_refiner")
    
    def refine(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Refine a user query to improve retrieval quality.
        
        Args:
            query: Original user query
            context: Optional context (e.g., detected location)
            
        Returns:
            Dictionary with refined query and metadata:
            - original_query: Original query
            - refined_query: Refined query
            - expanded_query: Query with expansions
            - entities: Extracted entities
            - question_type: Detected question type
        """
        original_query = query.strip()
        refined_query = original_query.lower()
        
        # Extract entities
        entities = self._extract_entities(refined_query)
        
        # Expand abbreviations
        expanded_query = self._expand_abbreviations(refined_query)
        
        # Normalize location mentions
        if context and context.get("detected_location"):
            expanded_query = self._normalize_location(expanded_query, context["detected_location"])
        
        # Detect question type
        question_type = self._detect_question_type(refined_query)
        
        # Build final refined query (combine original with expansions)
        final_query = self._combine_queries(original_query, expanded_query)
        
        result = {
            "original_query": original_query,
            "refined_query": final_query,
            "expanded_query": expanded_query,
            "entities": entities,
            "question_type": question_type
        }
        
        self.logger.log_tool_execution(
            tool_name="query_refiner",
            question=original_query[:200],
            success=True,
            response_length=len(final_query)
        )
        
        return result
    
    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Extract entities from query.
        
        Args:
            query: Query string
            
        Returns:
            Dictionary of extracted entities
        """
        entities = {
            "zip_codes": [],
            "numbers": [],
            "locations": []
        }
        
        # Extract zip codes (5 digits)
        zip_pattern = r'\b\d{5}\b'
        zip_codes = re.findall(zip_pattern, query)
        entities["zip_codes"] = list(set(zip_codes))
        
        # Extract numbers (for quantities, rates, etc.)
        number_pattern = r'\b\d+(?:\.\d+)?\b'
        numbers = re.findall(number_pattern, query)
        entities["numbers"] = [float(n) if '.' in n else int(n) for n in numbers]
        
        # Extract location mentions (simple heuristic)
        location_indicators = ["in", "near", "at", "around"]
        words = query.split()
        for i, word in enumerate(words):
            if word.lower() in location_indicators and i + 1 < len(words):
                # Next word might be a location
                potential_location = words[i + 1]
                if len(potential_location) > 2:  # Filter out very short words
                    entities["locations"].append(potential_location)
        
        return entities
    
    def _expand_abbreviations(self, query: str) -> str:
        """
        Expand abbreviations in query.
        
        Args:
            query: Query string
            
        Returns:
            Query with abbreviations expanded
        """
        expanded = query
        
        # Sort by length (longest first) to avoid partial matches
        sorted_abbrevs = sorted(
            self.ABBREVIATIONS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )
        
        for abbrev, expansion in sorted_abbrevs:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(abbrev) + r'\b'
            expanded = re.sub(pattern, expansion, expanded, flags=re.IGNORECASE)
        
        return expanded
    
    def _normalize_location(self, query: str, location_info: Dict[str, Any]) -> str:
        """
        Normalize location mentions in query.
        
        Args:
            query: Query string
            location_info: Detected location information
            
        Returns:
            Query with normalized location mentions
        """
        # Add explicit location context if detected
        normalized = query
        
        zip_code = location_info.get("zip_code")
        city = location_info.get("city")
        state = location_info.get("state")
        
        # If location is detected but not mentioned in query, we could add it
        # But for now, we'll just normalize existing mentions
        if zip_code and f"zip {zip_code}" not in normalized.lower():
            # Don't modify query, just note it
            pass
        
        return normalized
    
    def _detect_question_type(self, query: str) -> Optional[str]:
        """
        Detect question type from query.
        
        Args:
            query: Query string
            
        Returns:
            Detected question type or None
        """
        query_lower = query.lower()
        
        for q_type, keywords in self.QUESTION_TYPES.items():
            if any(keyword in query_lower for keyword in keywords):
                return q_type
        
        return None
    
    def _combine_queries(self, original: str, expanded: str) -> str:
        """
        Combine original and expanded queries intelligently.
        
        Args:
            original: Original query
            expanded: Expanded query
            
        Returns:
            Combined query
        """
        # If expanded is same as original (lowercased), return original
        if expanded.lower() == original.lower():
            return original
        
        # Otherwise, prefer original but add key expansions if they add value
        # For now, return original to preserve user intent
        # In future, could do more sophisticated merging
        return original

