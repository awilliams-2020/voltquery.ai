"""
Pytest configuration and fixtures for RAG service tests.
"""

import pytest
import os
from unittest.mock import Mock, AsyncMock
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@pytest.fixture(scope="session")
def test_env():
    """Ensure test environment variables are set."""
    # Set test defaults if not already set
    if not os.getenv("LLM_MODE"):
        os.environ["LLM_MODE"] = "local"
    
    return {
        "LLM_MODE": os.getenv("LLM_MODE", "local"),
        "NREL_API_KEY": os.getenv("NREL_API_KEY", "test_key"),
    }


@pytest.fixture
def mock_nrel_client():
    """Create a mock NREL client."""
    mock_client = Mock()
    mock_client.get_utility_rates = AsyncMock(return_value={
        "utility_name": "Test Utility",
        "residential": 0.1179,
        "commercial": 0.0483,
        "industrial": 0.0196
    })
    mock_client.get_solar_estimate = AsyncMock(return_value={
        "ac_annual": 5342.28,
        "ac_monthly": [300.6, 317.3, 427.0, 507.0, 569.2, 584.7, 584.6, 567.9, 510.4, 414.3, 316.6, 242.7]
    })
    return mock_client


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store service."""
    mock_service = Mock()
    mock_index = Mock()
    mock_service.get_index.return_value = mock_index
    return mock_service


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service."""
    mock_service = Mock()
    mock_llm = Mock()
    mock_service.get_llm.return_value = mock_llm
    return mock_service

