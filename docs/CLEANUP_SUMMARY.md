# Code Cleanup Summary After Refactoring

## Overview

After refactoring to the modular tool-bundle architecture and GlobalSettings, several pieces of orphaned/duplicate code were identified and marked for future migration.

## Changes Made

### 1. Removed Duplicate Class Definitions

**Removed from `rag_service.py`:**
- `RobustSubQuestionOutputParser` class (moved to `src/orchestrator.py`)
- `ToolNameMappingParser` class definition (moved to `src/orchestrator.py`)

**Action Taken:**
- Replaced with imports from `src.orchestrator`
- Added TODO comments indicating these should be removed once RAGService is fully migrated

### 2. Added Migration TODOs

**Added TODO comments for:**
- `FunctionToolQueryEngine` - Should be replaced by bundle QueryEngines
- `_get_solar_estimate_for_location()` - Duplicated in `src/bundles/solar/query_engine.py`
- `_run_reopt_optimization_for_location()` - Similar functionality in `src/bundles/optimization/__init__.py`
- Direct tool creation code - Should use `RAGOrchestrator.create_tools()`

### 3. Verified GlobalSettings Integration

**Confirmed:**
- ✅ `reopt_service.py` no longer has hardcoded financial values
- ✅ All financial parameters pulled from `GlobalSettings.get_financial_params()`
- ✅ Optimization bundle uses GlobalSettings for policy rules

## Remaining Work

### High Priority
1. **Migrate RAGService.query()** to use `RAGOrchestrator`
   - Replace tool creation code (lines ~1113-1196) with `orchestrator.create_tools()`
   - Replace SubQuestionQueryEngine creation with `orchestrator.create_sub_question_query_engine()`
   - This will eliminate `FunctionToolQueryEngine` and helper methods

### Medium Priority
2. **Refactor optimization bypass logic** (line ~1756)
   - Currently calls `_run_reopt_optimization_for_location()` directly
   - Consider using optimization bundle's QueryEngine instead
   - Or extract to a shared utility function

### Low Priority
3. **Remove unused imports** after migration
   - `FunctionToolQueryEngine` imports
   - Helper method imports that are no longer needed

## Files Modified

1. `backend/app/services/rag_service.py`
   - Removed duplicate class definitions
   - Added TODO comments for migration
   - Updated imports to use orchestrator classes

## Files Not Modified (Still Using Old Code)

- `backend/app/services/rag_service.py` - Still contains old tool creation logic
  - This is intentional - RAGService hasn't been migrated yet
  - Code is marked with TODOs for future migration

## Testing Recommendations

After migrating RAGService to use RAGOrchestrator:
1. Verify all tools are created correctly
2. Test SubQuestionQueryEngine routing
3. Verify optimization bypass logic still works
4. Remove orphaned code and unused imports
5. Run full test suite

## Notes

- The old code is still functional and being used
- TODOs mark code for future cleanup after migration
- No breaking changes - all existing functionality preserved
- Cleanup can be done incrementally as RAGService is migrated

