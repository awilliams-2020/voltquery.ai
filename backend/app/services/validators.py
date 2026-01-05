"""
Input validation utilities for RAG service.

Validates user inputs before processing to prevent errors.
"""

import re
from typing import Optional, Tuple, Dict, Any


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class InputValidator:
    """Validates inputs for RAG service."""
    
    @staticmethod
    def validate_zip_code(zip_code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate US zip code format.
        
        Args:
            zip_code: Zip code to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not zip_code:
            return False, "Zip code cannot be empty"
        
        if not isinstance(zip_code, str):
            return False, "Zip code must be a string"
        
        if not re.match(r'^\d{5}$', zip_code):
            return False, f"Invalid zip code format: '{zip_code}'. Must be 5 digits."
        
        return True, None
    
    @staticmethod
    def validate_location(location: str) -> Tuple[bool, Optional[str]]:
        """
        Validate location format (zip code, city/state, or coordinates).
        
        Args:
            location: Location string to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not location:
            return False, "Location cannot be empty"
        
        if not isinstance(location, str):
            return False, "Location must be a string"
        
        location = location.strip()
        
        # Check zip code format
        if re.match(r'^\d{5}$', location):
            return True, None
        
        # Check city, state format (e.g., "Denver, CO")
        if re.match(r'^[A-Za-z\s]+,\s*[A-Z]{2}$', location):
            return True, None
        
        # Check coordinates format (e.g., "39.7392,-104.9903")
        coord_match = re.match(r'^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$', location)
        if coord_match:
            try:
                lat = float(coord_match.group(1))
                lon = float(coord_match.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return True, None
                else:
                    return False, (
                        f"Invalid coordinates: lat={lat}, lon={lon}. "
                        f"Latitude must be -90 to 90, longitude -180 to 180."
                    )
            except ValueError:
                return False, f"Invalid coordinate format: '{location}'"
        
        return False, (
            f"Invalid location format: '{location}'. "
            f"Must be zip code (5 digits), city/state (e.g., 'Denver, CO'), "
            f"or coordinates (e.g., '39.7392,-104.9903')"
        )
    
    @staticmethod
    def validate_system_capacity(capacity: float) -> Tuple[bool, Optional[str]]:
        """
        Validate solar system capacity.
        
        Args:
            capacity: System capacity in kW
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(capacity, (int, float)):
            return False, "System capacity must be a number"
        
        if capacity <= 0:
            return False, f"System capacity must be positive, got {capacity}"
        
        if capacity < 0.1:
            return False, f"System capacity too small: {capacity} kW. Minimum is 0.1 kW."
        
        if capacity > 1000.0:
            return False, f"System capacity too large: {capacity} kW. Maximum is 1000 kW."
        
        return True, None
    
    @staticmethod
    def validate_question(question: str) -> Tuple[bool, Optional[str]]:
        """
        Validate user question.
        
        Args:
            question: User question string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not question:
            return False, "Question cannot be empty"
        
        if not isinstance(question, str):
            return False, "Question must be a string"
        
        question = question.strip()
        
        if len(question) < 3:
            return False, "Question too short. Please provide more details."
        
        if len(question) > 2000:
            return False, "Question too long. Maximum length is 2000 characters."
        
        return True, None
    
    @staticmethod
    def validate_top_k(top_k: int) -> Tuple[bool, Optional[str]]:
        """
        Validate top_k parameter.
        
        Args:
            top_k: Number of results to return
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(top_k, int):
            return False, "top_k must be an integer"
        
        if top_k <= 0:
            return False, f"top_k must be positive, got {top_k}"
        
        if top_k > 100:
            return False, f"top_k too large: {top_k}. Maximum is 100."
        
        return True, None
    
    @staticmethod
    def validate_state_code(state: str) -> Tuple[bool, Optional[str]]:
        """
        Validate US state code.
        
        Args:
            state: 2-letter state code
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not state:
            return False, "State code cannot be empty"
        
        if not isinstance(state, str):
            return False, "State code must be a string"
        
        state = state.strip().upper()
        
        if not re.match(r'^[A-Z]{2}$', state):
            return False, f"Invalid state code format: '{state}'. Must be 2 letters."
        
        # Valid US state codes
        valid_states = {
            'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
            'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
            'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
            'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
            'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
            'DC'  # District of Columbia
        }
        
        if state not in valid_states:
            return False, f"Invalid state code: '{state}'. Must be a valid US state code."
        
        return True, None


def validate_query_inputs(
    question: str,
    zip_code: Optional[str] = None,
    top_k: int = 5
) -> Tuple[bool, Optional[str]]:
    """
    Validate all query inputs.
    
    Args:
        question: User question
        zip_code: Optional zip code
        top_k: Number of results
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    validator = InputValidator()
    
    # Validate question
    is_valid, error = validator.validate_question(question)
    if not is_valid:
        return False, error
    
    # Validate zip code if provided
    if zip_code:
        is_valid, error = validator.validate_zip_code(zip_code)
        if not is_valid:
            return False, error
    
    # Validate top_k
    is_valid, error = validator.validate_top_k(top_k)
    if not is_valid:
        return False, error
    
    return True, None

