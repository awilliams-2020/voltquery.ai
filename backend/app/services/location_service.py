from typing import Optional, Dict, Any
from app.services.llm_service import LLMService
import json
import re
import httpx


class LocationService:
    """
    Service for extracting location information from user queries.
    Uses LLM to intelligently parse city names, state names, zipcodes, etc.
    """
    
    def __init__(self):
        self.llm_service = LLMService()
    
    async def extract_location_from_question(
        self, 
        question: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract location information from a user's question using LLM.
        
        Args:
            question: User's question (e.g., "Where can I charge in Denver?")
            
        Returns:
            Dictionary with location info:
            - zip_code: 5-digit zip code (if found)
            - city: City name (if found)
            - state: 2-letter state code (if found)
            - location_type: "zip_code", "city_state", "state", or None
            Or None if no location found
        """
        llm = self.llm_service.get_llm()
        
        # Create prompt for location extraction
        extraction_prompt = f"""Extract location information from this question about EV charging stations.

Question: "{question}"

Extract any location information mentioned. Look for:
- Zip codes (5 digits)
- City names (e.g., "Denver", "Los Angeles", "New York")
- State names or abbreviations (e.g., "Colorado", "CA", "Ohio", "OH")
- Geographic references (e.g., "near me", "in my area")

Respond with ONLY a JSON object in this exact format:
{{
    "zip_code": "12345" or null,
    "city": "CityName" or null,
    "state": "XX" or null,
    "location_type": "zip_code" or "city_state" or "state" or null
}}

If no location is found, return: {{"zip_code": null, "city": null, "state": null, "location_type": null}}

Only return the JSON object, nothing else."""

        try:
            response = await llm.acomplete(extraction_prompt)
            response_text = response.text if hasattr(response, "text") else str(response)
            
            # Clean the response - remove markdown code blocks if present
            response_text = response_text.strip()
            if response_text.startswith("```"):
                # Remove markdown code blocks
                response_text = re.sub(r'^```(?:json)?\s*', '', response_text)
                response_text = re.sub(r'\s*```$', '', response_text)
            
            # Parse JSON response
            location_data = json.loads(response_text.strip())
            
            # Validate and return - ensure location_data is a dict
            if isinstance(location_data, dict) and location_data.get("location_type"):
                zip_code = location_data.get("zip_code")
                city = location_data.get("city")
                state = location_data.get("state")
                location_type = location_data.get("location_type")
                
                # If we have city/state but no zip code, try to geocode it
                if not zip_code and city and state and location_type == "city_state":
                    zip_code = await self.geocode_city_state_to_zip(city, state)
                    if zip_code:
                        # Update location_type to zip_code if we successfully geocoded
                        location_type = "zip_code"
                
                return {
                    "zip_code": zip_code,
                    "city": city,
                    "state": state,
                    "location_type": location_type
                }
            
            return None
            
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, IndexError, Exception) as e:
            # Fallback: try simple regex patterns
            return self._fallback_location_extraction(question)
    
    def _fallback_location_extraction(
        self, 
        question: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback method using regex patterns to extract location info.
        Less accurate than LLM but more reliable.
        """
        question_lower = question.lower()
        
        # Try to find zip code (5 digits)
        zip_match = re.search(r'\b(\d{5})\b', question)
        if zip_match:
            return {
                "zip_code": zip_match.group(1),
                "city": None,
                "state": None,
                "location_type": "zip_code"
            }
        
        # Common US state abbreviations
        state_abbrevs = {
            'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga',
            'hi', 'id', 'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md',
            'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 'nh', 'nj',
            'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc',
            'sd', 'tn', 'tx', 'ut', 'vt', 'va', 'wa', 'wv', 'wi', 'wy'
        }
        
        # Try to find state abbreviation (2 letters, possibly standalone)
        words = re.findall(r'\b([a-z]{2})\b', question_lower)
        for word in words:
            if word in state_abbrevs:
                return {
                    "zip_code": None,
                    "city": None,
                    "state": word.upper(),
                    "location_type": "state"
                }
        
        # Common city names (this is a limited fallback)
        # In production, you might want a more comprehensive city database
        major_cities = {
            'denver', 'los angeles', 'san francisco', 'new york', 'chicago',
            'houston', 'phoenix', 'philadelphia', 'san antonio', 'san diego',
            'dallas', 'san jose', 'austin', 'jacksonville', 'fort worth',
            'columbus', 'charlotte', 'san francisco', 'indianapolis', 'seattle'
        }
        
        for city in major_cities:
            if city in question_lower:
                return {
                    "zip_code": None,
                    "city": city.title(),
                    "state": None,
                    "location_type": "city_state"
                }
        
        return None
    
    def get_zipcode_from_location(
        self, 
        location_info: Dict[str, Any]
    ) -> Optional[str]:
        """
        Get zipcode from location info if available.
        If only city/state is provided, returns None (caller should handle differently).
        """
        if location_info and location_info.get("zip_code"):
            return location_info["zip_code"]
        return None
    
    def get_state_from_location(
        self, 
        location_info: Dict[str, Any]
    ) -> Optional[str]:
        """
        Get state code from location info if available.
        """
        if location_info and location_info.get("state"):
            return location_info["state"]
        return None
    
    async def geocode_city_state_to_zip(
        self,
        city: str,
        state: str
    ) -> Optional[str]:
        """
        Geocode a city/state combination to get a zip code.
        
        Args:
            city: City name
            state: State code (2 letters)
            
        Returns:
            Zip code string or None if geocoding fails
        """
        if not city or not state:
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                # Use Nominatim to geocode city/state
                query = f"{city}, {state}, USA"
                params = {
                    "q": query,
                    "country": "US",
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 1  # Get detailed address including postal code
                }
                
                headers = {
                    "User-Agent": "NREL-RAG-SaaS/1.0"
                }
                
                response = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params=params,
                    headers=headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Ensure data is a list and has at least one element
                    if data and isinstance(data, list) and len(data) > 0:
                        # Ensure first element is a dict
                        first_result = data[0]
                        if isinstance(first_result, dict):
                            # Try to extract postal code from address details
                            address = first_result.get("address", {})
                            postal_code = address.get("postcode")
                            if postal_code:
                                # Extract first 5 digits if postal code is longer
                                zip_match = re.search(r'\b(\d{5})\b', str(postal_code))
                                if zip_match:
                                    return zip_match.group(1)
                
                return None
        except Exception as e:
            print(f"Warning: Failed to geocode {city}, {state} to zip code: {str(e)}")
            return None

