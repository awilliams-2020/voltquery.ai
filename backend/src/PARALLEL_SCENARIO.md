# Parallel Scenario Approach Implementation

## Overview

Refactored orchestrator to use a "Parallel Scenario" approach for solar ROI questions in 2026. The orchestrator now automatically generates two separate sub-questions calling `optimization_tool` - one for purchase (0% ITC) and one for lease (30% ITC) - and compares the results.

## Key Features

### 1. Automatic Dual Tool Calls

For solar ROI questions in 2026, the orchestrator automatically generates two sub-questions:

**Call 1 (Purchase):**
- Sub-question: "What is optimal solar/storage size and NPV for [location] with purchase financing (0% ITC)?"
- Tool: `optimization_tool`
- Parameters: `ownership_type="purchase"`, `fed_itc_fraction=0.0`

**Call 2 (Lease):**
- Sub-question: "What is optimal solar/storage size and NPV for [location] with lease financing (30% ITC)?"
- Tool: `optimization_tool`
- Parameters: `ownership_type="lease"`, `fed_itc_fraction=0.30`

### 2. Enhanced Prompt Template

Updated prompt template in `orchestrator.py` includes:

```
CRITICAL RULE FOR 2026 SOLAR ROI QUESTIONS:
- If the question mentions "ROI", "return on investment", "financial analysis", "NPV", "payback", 
  or asks about buying/leasing solar in 2026, you MUST generate TWO separate sub-questions:
  1. One for purchase (0% ITC) - explicitly mention "purchase" and "0% ITC" in the sub-question
  2. One for lease (30% ITC) - explicitly mention "lease" and "30% ITC" in the sub-question
- Both sub-questions must call optimization_tool
- The final answer will compare both scenarios: "Under 2026 rules, buying with cash is non-viable 
  (NPV=$0), but a lease is viable (NPV=$X) because the developer keeps the 30% credit."
```

### 3. Custom Response Synthesis

Added custom response synthesizer that emphasizes comparison:

```
If multiple optimization results are provided (purchase vs lease scenarios), 
you MUST compare them explicitly:

1. State the NPV for purchase scenario (0% ITC)
2. State the NPV for lease scenario (30% ITC)
3. Explain: "Under 2026 OBBBA rules, buying with cash is non-viable (NPV=$X), 
   but a lease is viable (NPV=$Y) because the developer keeps the 30% credit."
4. Highlight the key difference: homeowners lose the purchase tax credit in 2026, 
   but lease/PPA providers can still claim 30% and pass savings through lower rates.
```

### 4. Optimization Bundle Detection

The optimization bundle detects explicit purchase/lease keywords from parallel scenario queries:

- Purchase keywords: "purchase", "buy", "buying", "purchasing", "0% itc", "zero itc"
- Lease keywords: "lease", "leasing", "leased", "ppa", "30% itc", "thirty percent itc"

## Example Flow

### User Query
"What's the ROI for solar in zip 80202 in 2026?"

### Orchestrator Generates Sub-Questions
```json
{
  "items": [
    {
      "sub_question": "What is optimal solar/storage size and NPV for zip 80202 with purchase financing (0% ITC)?",
      "tool_name": "optimization_tool"
    },
    {
      "sub_question": "What is optimal solar/storage size and NPV for zip 80202 with lease financing (30% ITC)?",
      "tool_name": "optimization_tool"
    }
  ]
}
```

### Tool Calls (Parallel Execution)
1. **Call 1**: `optimization_tool` with purchase parameters → Returns NPV=$0 (non-viable)
2. **Call 2**: `optimization_tool` with lease parameters → Returns NPV=$42,180 (viable)

### Final Response
```
Under 2026 OBBBA rules, buying with cash is non-viable (NPV=$0), but a lease is viable 
(NPV=$42,180) because the developer keeps the 30% credit.

Purchase Scenario (0% ITC):
- Net Present Value: $0
- The 30% Residential Tax Credit expired in 2025 for homeowner purchases

Lease Scenario (30% ITC):
- Net Present Value: $42,180
- The PPA provider receives the 30% federal tax credit and can pass savings through lower lease rates

Key Difference: While homeowners lose the purchase tax credit in 2026, lease/PPA providers 
can still claim 30% and pass savings through lower rates, making lease scenarios more viable.
```

## Implementation Details

### Orchestrator (`src/orchestrator.py`)

**Updated `get_custom_prompt_template()`:**
- Added CRITICAL RULE for 2026 solar ROI questions
- Examples show dual sub-question generation
- Explicit instructions to generate two separate calls

**Updated `create_sub_question_query_engine()`:**
- Added custom response synthesizer with comparison instructions
- Response prompt emphasizes comparing purchase vs lease scenarios
- Ensures final answer includes explicit comparison statement

### Optimization Bundle (`src/bundles/optimization/__init__.py`)

**Updated `_aquery()`:**
- Detects explicit purchase/lease keywords from parallel scenario queries
- Prioritizes keywords from orchestrator-generated sub-questions
- Falls back to scenario branching if keywords not detected

### RAG Service (`app/services/rag_service.py`)

**Updated Prompt Template:**
- Matches orchestrator prompt for consistency
- Includes CRITICAL RULE for dual sub-question generation

## Benefits

1. **Automatic Comparison**: No need for users to explicitly ask for comparison
2. **Parallel Execution**: Both scenarios run simultaneously (SubQuestionQueryEngine handles this)
3. **Clear Policy Context**: Final answer explicitly explains 2026 OBBBA rules
4. **User Education**: Explains why lease is more viable (provider gets credit)
5. **Consistent Format**: Standardized comparison format across all responses

## Testing Recommendations

1. Test query: "What's the ROI for solar in zip 80202 in 2026?"
   - Should generate two sub-questions
   - Should call optimization_tool twice
   - Should compare results in final answer

2. Test query: "Should I buy or lease solar panels for my home in 2026?"
   - Should generate two sub-questions
   - Should compare purchase vs lease scenarios

3. Test query: "Optimal solar size for zip 80202?"
   - Should generate single sub-question (not ROI-specific)

4. Verify final answer format:
   - Includes explicit comparison statement
   - States NPV for both scenarios
   - Explains 2026 OBBBA policy context

## Files Modified

1. `backend/src/orchestrator.py`
   - Updated prompt template with CRITICAL RULE
   - Added custom response synthesizer with comparison instructions
   - Examples show dual sub-question generation

2. `backend/src/bundles/optimization/__init__.py`
   - Enhanced keyword detection for parallel scenario queries
   - Prioritizes explicit purchase/lease keywords

3. `backend/app/services/rag_service.py`
   - Updated prompt template to match orchestrator
   - Includes CRITICAL RULE for consistency

## Notes

- SubQuestionQueryEngine automatically executes sub-questions in parallel
- Response synthesizer combines results and generates comparison
- Optimization bundle still supports scenario branching as fallback
- Both approaches (parallel scenarios and scenario branching) work together

