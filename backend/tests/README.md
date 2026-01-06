# RAG Service Tests

Tests for RAG service prompt behavior to prevent regressions when modifying prompts.

## Running Tests

```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```

Run specific test file:
```bash
pytest tests/test_rag_prompts.py -v
pytest tests/test_query_routing.py -v  # Test query routing logic
```

Run with coverage:
```bash
pytest tests/ --cov=app.services.rag_service --cov-report=html
```

## Test Categories

### 1. Sub-Question Generation (`TestSubQuestionGeneration`)
- Tests that sub-questions route to correct tools
- Verifies "charging at [time]" maps to utility_tool, not transportation_tool
- Ensures solar questions map to solar_production_tool

### 2. Prompt Behavior (`TestPromptBehavior`)
- Tests that cost/savings questions don't generate transportation sub-questions
- Verifies tool descriptions include/exclude correct keywords
- Ensures prompts guide LLM correctly

### 3. Utility Tool Response (`TestUtilityToolResponse`)
- Tests that utility tool doesn't refuse to answer
- Verifies response synthesizer prompt encourages data provision
- Checks for absence of refusal phrases

### 4. Sub-Question Deduplication (`TestSubQuestionDeduplication`)
- Tests detection of duplicate utility tool questions
- Identifies opportunities for optimization

### 5. Expected Sub-Questions (`TestExpectedSubQuestions`)
- Tests that common queries generate expected sub-questions
- Verifies question structure matches expectations

### 6. Query Routing Tests (`TestQueryRouting`)
- Tests query keyword detection (transportation, utility, building efficiency)
- Verifies tool routing logic without requiring full application stack
- Tests location extraction from queries
- Fast unit tests that can run without containers

### 7. Integration Tests (`TestRAGServiceIntegration`)
- Tests RAG service with mocked dependencies
- Verifies metadata structure for indexed documents

## Regression Testing

For regression testing with varying queries, see:
- **Unit Tests**: `pytest tests/test_query_routing.py` - Fast, no containers needed
- **Manual Testing**: See `docs/MANUAL_REGRESSION_TESTING.md` for testing against running containers
- **Test Queries**: See `docs/TEST_QUERIES.json` for a list of test queries

## Adding New Tests

When modifying prompts, add tests to verify:
1. Correct tool routing
2. No regressions in existing behavior
3. New behavior works as expected

Example:
```python
def test_new_prompt_behavior(self):
    """Test that new prompt feature works correctly."""
    # Test implementation
    assert expected_behavior
```

## Continuous Integration

These tests should be run:
- Before committing prompt changes
- In CI/CD pipeline
- When updating dependencies

