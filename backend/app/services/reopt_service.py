from typing import Dict, Any, Optional, List, Literal
import httpx
import asyncio
import json
from pydantic_settings import BaseSettings
from app.services.cache_service import get_cache_service
from app.services.circuit_breaker import get_breaker_manager
from app.services.logger_service import get_logger
from app.services.nrel_client import NRELClient
from app.services.urdb_service import URDBService
from src.global_settings import get_global_settings


class REoptSettings(BaseSettings):
    """Settings for NREL REopt API."""
    nrel_api_key: str
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class REoptService:
    """
    Service for interacting with NREL REopt v3 API.
    REopt is an optimization tool for renewable energy systems.
    
    Documentation: https://developer.nrel.gov/docs/energy-optimization/reopt/v3/
    """
    
    BASE_URL = "https://developer.nrel.gov/api/reopt/v3"
    JOB_ENDPOINT = f"{BASE_URL}/job"
    RESULTS_ENDPOINT = f"{BASE_URL}/results"  # Legacy endpoint, not used in v3
    
    # Note: REopt API v3 documentation: https://developer.nrel.gov/docs/energy-optimization/reopt/v3/
    # The API expects a Scenario object with Site, ElectricLoad, and ElectricTariff
    # If you're getting "Missing required inputs" errors, check the API documentation
    # for the exact required fields and structure
    # 
    # Input/Output format schemas can be retrieved from:
    # - Inputs: https://developer.nrel.gov/api/reopt/v3/job/inputs?api_key=DEMO_KEY
    # - Outputs: https://developer.nrel.gov/api/reopt/v3/job/outputs?api_key=DEMO_KEY
    # Job results are retrieved from: /job/{run_uuid}/outputs
    
    # Polling configuration
    POLL_INTERVAL_SECONDS = 5  # Base wait time (legacy, kept for compatibility)
    MAX_POLL_ATTEMPTS = 120  # Maximum attempts
    MIN_POLL_INTERVAL = 3  # Minimum wait time (seconds)
    MAX_POLL_INTERVAL = 30  # Maximum wait time (seconds)
    INITIAL_POLL_INTERVAL = 3  # Initial wait time for first poll
    
    def _calculate_wait_time(
        self,
        attempt: int,
        status: str,
        response_size: int,
        previous_response_size: Optional[int],
        rate_remaining: Optional[int],
        unchanged_count: int
    ) -> float:
        """
        Calculate adaptive wait time using exponential backoff and response size changes.
        
        Args:
            attempt: Current poll attempt number (0-indexed)
            status: Current job status
            response_size: Current response size in bytes
            previous_response_size: Previous response size in bytes (None if first poll)
            rate_remaining: Remaining rate limit (None if not available)
            unchanged_count: Number of consecutive polls with unchanged response size
            
        Returns:
            Wait time in seconds
        """
        # Base exponential backoff: start at INITIAL_POLL_INTERVAL, double every few attempts
        # Cap at MAX_POLL_INTERVAL
        base_wait = self.INITIAL_POLL_INTERVAL * (2 ** min(attempt // 3, 4))  # Double every 3 attempts, max 4x
        base_wait = min(base_wait, self.MAX_POLL_INTERVAL)
        
        # Longer waits for optimization jobs (they take time)
        if status in ["Optimizing...", "optimizing"]:
            base_wait = max(base_wait, 8)  # At least 8 seconds for optimization
        
        # Adaptive: if response size hasn't changed, wait longer
        if previous_response_size is not None:
            if response_size == previous_response_size:
                # Response unchanged - increase wait time more aggressively
                unchanged_count += 1
                adaptive_multiplier = 1.0 + (unchanged_count * 0.5)  # Increase by 50% per unchanged poll
                base_wait = min(base_wait * adaptive_multiplier, self.MAX_POLL_INTERVAL)
            else:
                # Response changed - might be close to completion, use shorter wait
                unchanged_count = 0
                if response_size > previous_response_size * 2:
                    # Response size doubled - likely completing soon, reduce wait
                    base_wait = max(base_wait * 0.7, self.MIN_POLL_INTERVAL)
        
        # Rate limit awareness: if rate limit is low, wait longer
        if rate_remaining is not None:
            if rate_remaining < 5:
                # Very low rate limit - wait much longer
                base_wait = min(base_wait * 2, self.MAX_POLL_INTERVAL)
            elif rate_remaining < 20:
                # Low rate limit - wait longer
                base_wait = min(base_wait * 1.5, self.MAX_POLL_INTERVAL)
        
        return max(base_wait, self.MIN_POLL_INTERVAL)
    
    def __init__(self):
        settings = REoptSettings()
        self.api_key = settings.nrel_api_key
        if not self.api_key or self.api_key == "your_nrel_api_key_here":
            raise ValueError("NREL_API_KEY must be set in environment variables")
        
        # Initialize cache and circuit breakers
        self.cache = get_cache_service()
        self.breaker_manager = get_breaker_manager()
        self.reopt_breaker = self.breaker_manager.get_breaker(
            "reopt",
            failure_threshold=5,
            timeout_seconds=300,  # Longer timeout for optimization jobs
            success_threshold=2
        )
        self.logger = get_logger("reopt_service")
        self.nrel_client = NRELClient()  # For geocoding and utility rate lookup
        self.urdb_service = URDBService(llm_mode="local")  # For URDB label lookup
    
    def _build_payload(
        self,
        lat: float,
        lon: float,
        load_profile_type: str = "residential",
        urdb_label: Optional[str] = None,
        additional_load_kw: float = 0.0,
        property_type: Optional[Literal["residential", "commercial", "industrial"]] = None,
        ownership_type: Optional[Literal["purchase", "lease"]] = None,
        construction_start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build the REopt API payload.
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            load_profile_type: Load profile type - "residential", "commercial", or "industrial"
            urdb_label: URDB label for the electric tariff (from URDB API)
            additional_load_kw: Additional peak load in kW (e.g., EV chargers)
            
        Returns:
            Dictionary containing the REopt API payload
        """
        # Determine default load profile values based on type
        # These are typical values for each sector
        base_load_profile_kw = {
            "residential": 5.0,  # 5 kW peak for residential
            "commercial": 50.0,  # 50 kW peak for commercial
            "industrial": 200.0  # 200 kW peak for industrial
        }.get(load_profile_type.lower(), 5.0)
        
        # Add additional load (e.g., EV chargers)
        load_profile_kw = base_load_profile_kw + additional_load_kw
        
        base_annual_kwh = {
            "residential": 12000.0,  # 12,000 kWh/year for residential
            "commercial": 60000.0,  # 60,000 kWh/year for commercial
            "industrial": 500000.0  # 500,000 kWh/year for industrial
        }.get(load_profile_type.lower(), 12000.0)
        
        # Estimate annual kWh for additional load (assume 4 hours/day average usage)
        # This is conservative - EV chargers may be used more or less
        additional_annual_kwh = additional_load_kw * 4 * 365  # kW * hours/day * days/year
        annual_kwh = base_annual_kwh + additional_annual_kwh
        
        # Build payload with required fields
        # REopt v3 API expects Scenario object with Site, ElectricLoad, and ElectricTariff
        # Based on API documentation, all three are required with specific fields
        
        # ElectricTariff is required and MUST have urdb_label
        # REopt API v3 requires a valid urdb_label - it cannot auto-detect
        if not urdb_label or (isinstance(urdb_label, str) and not urdb_label.strip()):
            raise ValueError(
                "URDB label is required for REopt optimization. "
                "Please provide a urdb_label or ensure the location can be looked up in URDB. "
                f"Current urdb_label value: {urdb_label}"
            )
        
        # Policy-Aware Financial Strategy: Apply 2026 OBBBA Rules
        # Determine property_type from load_profile_type if not provided
        if property_type is None:
            property_type = load_profile_type.lower()  # Map load_profile_type to property_type
        
        # Apply 2026 OBBBA Rules for ITC
        # Rule 1: If ownership == 'purchase' and type == 'residential': fed_itc_fraction = 0.0
        # Rule 2: If ownership == 'lease' OR type == 'commercial': fed_itc_fraction = 0.30
        if property_type == "residential" and ownership_type == "purchase":
            fed_itc_fraction = 0.0
        elif ownership_type == "lease" or property_type in ["commercial", "industrial"]:
            fed_itc_fraction = 0.30
        else:
            # Default fallback (shouldn't happen with proper detection)
            fed_itc_fraction = 0.0
        
        # Get financial parameters from GlobalSettings with policy-aware overrides
        global_settings = get_global_settings()
        
        # Force analysis_years = 25 for all runs to allow ROI time to manifest
        financial_params = global_settings.get_financial_params(
            property_type=property_type,
            ownership_type=ownership_type,
            construction_start_date=construction_start_date
        )
        # Override analysis_years to 25 for all runs
        financial_params["analysis_years"] = 25
        # Override federal_tax_credit_rate with policy-aware value
        financial_params["federal_tax_credit_rate"] = fed_itc_fraction
        
        # REopt v3 API uses a FLAT structure
        # Reference: https://github.com/NREL/REopt-Analysis-Scripts/wiki/3.-V3-input-and-output-changes
        # In v3: Scenario, Site, ElectricLoad, ElectricTariff, PV, ElectricStorage are all at the same top level
        # Scenario contains high-level settings (timeout_seconds, etc.), not Site/PV/etc.
        
        payload = {
            "Scenario": {
                "timeout_seconds": 400
            },
            "Site": {
                "latitude": lat,
                "longitude": lon
            },
            "Financial": {
                "analysis_years": financial_params["analysis_years"],
                "offtaker_discount_rate_fraction": financial_params["offtaker_discount_rate_fraction"],
                "offtaker_tax_rate_fraction": financial_params["offtaker_tax_rate_fraction"],
                "om_cost_escalation_rate_fraction": financial_params["om_cost_escalation_rate_fraction"],
                "elec_cost_escalation_rate_fraction": financial_params["elec_cost_escalation_rate_fraction"],
                "owner_discount_rate_fraction": financial_params["owner_discount_rate_fraction"],
                "owner_tax_rate_fraction": financial_params["owner_tax_rate_fraction"],
                "third_party_ownership": True if ownership_type == "lease" else financial_params["third_party_ownership"],
                "federal_itc_fraction": fed_itc_fraction  # CRITICAL: Policy-aware ITC rate (0.0 for residential purchase, 0.30 for lease/commercial)
            },
            "ElectricLoad": {
                "load_profile_type": load_profile_type,
                "doe_reference_name": self._get_doe_reference_name(load_profile_type),
                "load_profile_kw": load_profile_kw,
                "annual_kwh": annual_kwh
            },
            "ElectricTariff": {
                "urdb_label": urdb_label
            },
            "PV": {
                "max_kw": 1000.0,
                "existing_kw": 0.0,
                "installed_cost_per_kw": global_settings.solar_installed_cost_per_kw,
                "om_cost_per_kw": global_settings.solar_om_cost_per_kw,
                # Note: REopt calculates ITC internally based on PV cost
                # The ITC rate is applied through the Financial section parameters
                # Policy-aware ITC (fed_itc_fraction) is set above and affects NPV calculation
            },
            "ElectricStorage": {
                "max_kw": global_settings.storage_max_kw,
                "max_kwh": global_settings.storage_max_kwh
            }
        }
        
        # Log financial parameters for lease scenarios
        if ownership_type == "lease":
            print(f"[REoptService] lease_scenario | itc={fed_itc_fraction} | third_party={payload['Financial']['third_party_ownership']} | property={property_type}")
        
        return payload
    
    def _get_doe_reference_name(self, load_profile_type: str) -> str:
        """
        Get DOE reference name for load profile type.
        
        Args:
            load_profile_type: Load profile type
            
        Returns:
            DOE reference name string
        """
        # Map load profile types to DOE reference names
        # These are standard load profiles from DOE
        mapping = {
            "residential": "MidriseApartment",
            "commercial": "RetailStore",
            "industrial": "Warehouse"
        }
        return mapping.get(load_profile_type.lower(), "MidriseApartment")
    
    async def _submit_job(self, payload: Dict[str, Any]) -> str:
        """
        Submit a job to the REopt API and return the run_uuid.
        
        Args:
            payload: REopt API payload
            
        Returns:
            run_uuid string
            
        Raises:
            ValueError: If job submission fails
        """
        async with httpx.AsyncClient() as client:
            params = {
                "api_key": self.api_key,
                "format": "json"
            }
            
            try:
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                
                response = await client.post(
                    self.JOB_ENDPOINT,
                    params=params,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                
                # Check rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining)
                rate_limit = response.headers.get("X-RateLimit-Limit")
                rate_remaining = response.headers.get("X-RateLimit-Remaining")
                if rate_limit and rate_remaining:
                    if int(rate_remaining) < 10:
                        print(f"[REoptService] WARNING rate_limit_low | remaining={rate_remaining}/{rate_limit}")
                
                # Handle rate limit errors (429)
                if response.status_code == 429:
                    try:
                        error_data = response.json()
                        error_obj = error_data.get("error", {})
                        error_msg = error_obj.get("message", "Rate limit exceeded")
                        
                        # Get rate limit info from headers if available
                        rate_limit_info = ""
                        if rate_limit and rate_remaining:
                            rate_limit_info = f" (Limit: {rate_limit}/hour, Remaining: {rate_remaining})"
                        
                        print(f"ERROR: REopt API rate limit exceeded: {error_msg}{rate_limit_info}")
                        print(f"INFO: Rate limits reset on a rolling hourly basis. Wait an hour or contact NREL support for higher limits.")
                        
                        raise ValueError(
                            f"REopt API rate limit exceeded (429). {error_msg} "
                            f"Rate limits reset on a rolling hourly basis. "
                            f"Please wait before trying again, or contact NREL support at https://developer.nrel.gov/contact/ for higher limits."
                        )
                    except Exception as e:
                        if isinstance(e, ValueError):
                            raise
                        raise ValueError(
                            f"REopt API rate limit exceeded (429). "
                            f"Rate limits reset on a rolling hourly basis. Please wait before trying again."
                        ) from e
                
                # Handle 400/422 errors (validation errors)
                if response.status_code in [400, 422]:
                    try:
                        error_data = response.json()
                        # Log full error for debugging
                        error_json = json.dumps(error_data, indent=2)
                        print(f"ERROR: REopt API error response: {error_json}")
                        self.logger.log_error(
                            error_type="REoptAPIError",
                            error_message=f"REopt API returned {response.status_code}",
                            context={"error_data": error_data}
                        )
                        
                        # Extract detailed error messages
                        messages = error_data.get("messages", {})
                        input_errors = messages.get("input_errors", {})
                        error_msg = messages.get("error", "Unknown error")
                        
                        # Build detailed error message
                        error_details = [f"REopt API returned {response.status_code}: {error_msg}"]
                        if input_errors:
                            error_details.append("Input errors:")
                            for key, value in input_errors.items():
                                error_details.append(f"  {key}: {value}")
                        
                        raise ValueError("\n".join(error_details))
                    except Exception as e:
                        # If we can't parse the error, include the raw response
                        if isinstance(e, ValueError):
                            raise
                        raise ValueError(
                            f"REopt API returned {response.status_code}. "
                            f"Response: {response.text[:1000]}"
                        ) from e
                
                response.raise_for_status()
                data = response.json()
                
                # Extract run_uuid from response
                run_uuid = data.get("run_uuid") or data.get("run_id")
                if not run_uuid:
                    raise ValueError(f"No run_uuid in REopt API response: {data}")
                
                print(f"INFO: REopt job submitted successfully: {run_uuid}")
                return run_uuid
                
            except httpx.TimeoutException as e:
                raise ValueError(
                    f"REopt API request timed out. Please try again later."
                ) from e
            except httpx.HTTPStatusError as e:
                raise ValueError(
                    f"REopt API returned error {e.response.status_code}: {e.response.text[:500]}"
                ) from e
            except Exception as e:
                raise ValueError(
                    f"Failed to submit REopt job: {str(e)}"
                ) from e
    
    async def _poll_results(self, run_uuid: str) -> Dict[str, Any]:
        """
        Poll the REopt API results endpoint until the job is complete.
        
        Args:
            run_uuid: Run UUID from job submission
            
        Returns:
            Dictionary containing the complete results
            
        Raises:
            ValueError: If polling fails or times out
        """
        import sys
        import time as time_module
        
        # Log entry point - use both stdout and stderr to ensure visibility
        # Create httpx client with default timeout for large responses
        # cURL tests show downloads take ~2s for 1.7MB, but we use 60s as safety margin
        # This timeout applies to all requests in this client
        default_timeout = httpx.Timeout(
            connect=30.0,  # 30s to establish connection
            read=60.0,     # 60s to read response (cURL shows ~2s for 1.7MB, so 60s is safe)
            write=30.0,    # 30s to write request
            pool=30.0      # 30s to get connection from pool
        )
        
        async with httpx.AsyncClient(timeout=default_timeout) as client:
            # REopt API v3 expects results at /job/{run_uuid}/results
            # The outputs format schema can be retrieved from /api/reopt/v3/job/outputs
            results_url = f"{self.JOB_ENDPOINT}/{run_uuid}/results"
            params = {
                "api_key": self.api_key,
                "format": "json"
            }
            
            import sys
            import time as time_module
            
            print(f"INFO: Starting to poll REopt job {run_uuid}", flush=True)
            sys.stdout.flush()
            
            # Track response size for adaptive polling
            previous_response_size = None
            unchanged_count = 0
            
            # Initial delay before first poll (optimization jobs need time to initialize)
            await asyncio.sleep(2)
            
            for attempt in range(self.MAX_POLL_ATTEMPTS):
                try:
                    poll_start_time = time_module.time()
                    
                    response = await client.get(
                        results_url,
                        params=params
                    )
                    
                    poll_elapsed = time_module.time() - poll_start_time
                    
                    # Check rate limit headers
                    rate_limit = response.headers.get("X-RateLimit-Limit")
                    rate_remaining_str = response.headers.get("X-RateLimit-Remaining")
                    rate_remaining = int(rate_remaining_str) if rate_remaining_str else None
                    if rate_limit and rate_remaining is not None:
                        if rate_remaining < 10:
                            print(f"WARNING: Low rate limit remaining: {rate_remaining}/{rate_limit}", flush=True)
                    
                    response_size = len(response.content)
                    
                    # Handle rate limit errors during polling
                    if response.status_code == 429:
                        try:
                            error_data = response.json()
                            error_obj = error_data.get("error", {})
                            error_msg = error_obj.get("message", "Rate limit exceeded")
                            rate_limit_info = ""
                            if rate_limit and rate_remaining:
                                rate_limit_info = f" (Limit: {rate_limit}/hour, Remaining: {rate_remaining})"
                            print(f"ERROR: Rate limit exceeded during polling: {error_msg}{rate_limit_info}")
                            raise ValueError(
                                f"REopt API rate limit exceeded during polling (429). {error_msg} "
                                f"Please wait before trying again."
                            )
                        except Exception as e:
                            if isinstance(e, ValueError):
                                raise
                            raise ValueError(
                                f"REopt API rate limit exceeded during polling (429). Please wait before trying again."
                            ) from e
                    
                    response.raise_for_status()
                    
                    # Parse JSON response
                    data = response.json()
                    
                    # Check status
                    status = data.get("status") or data.get("job_status")
                    if status == "complete" or status == "optimal":
                        print(f"INFO: REopt job {run_uuid} completed successfully (status: {status})", flush=True)
                        sys.stdout.flush()
                        return data
                    elif status == "failed" or status == "error":
                        error_msg = data.get("error", {}).get("message", "Unknown error")
                        error_details = data.get("messages", {})
                        print(f"ERROR: REopt job {run_uuid} failed: {error_msg}", flush=True)
                        if error_details:
                            print(f"ERROR: Error details: {error_details}", flush=True)
                        sys.stdout.flush()
                        raise ValueError(
                            f"REopt job {run_uuid} failed: {error_msg}"
                        )
                    elif status in ["queued", "running", "processing", "Optimizing...", "optimizing"]:
                        # Job still processing, calculate adaptive wait time
                        wait_time = self._calculate_wait_time(
                            attempt=attempt,
                            status=status,
                            response_size=response_size,
                            previous_response_size=previous_response_size,
                            rate_remaining=rate_remaining,
                            unchanged_count=unchanged_count
                        )
                        
                        # Update tracking variables
                        if previous_response_size == response_size:
                            unchanged_count += 1
                        else:
                            unchanged_count = 0
                        previous_response_size = response_size
                        
                        print(f"INFO: Job status is '{status}', waiting {wait_time:.1f} seconds before next poll...", flush=True)
                        sys.stdout.flush()
                        if attempt < self.MAX_POLL_ATTEMPTS - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            raise ValueError(
                                f"REopt job {run_uuid} timed out after {self.MAX_POLL_ATTEMPTS} attempts (status was '{status}')"
                            )
                    else:
                        # Unknown status, use conservative wait time
                        wait_time = self._calculate_wait_time(
                            attempt=attempt,
                            status=status,
                            response_size=response_size,
                            previous_response_size=previous_response_size,
                            rate_remaining=rate_remaining,
                            unchanged_count=unchanged_count
                        )
                        
                        # Update tracking variables
                        if previous_response_size == response_size:
                            unchanged_count += 1
                        else:
                            unchanged_count = 0
                        previous_response_size = response_size
                        
                        print(f"WARNING: Unknown status '{status}', waiting {wait_time:.1f} seconds before retry...", flush=True)
                        sys.stdout.flush()
                        if attempt < self.MAX_POLL_ATTEMPTS - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            raise ValueError(
                                f"REopt job {run_uuid} returned unknown status: {status}"
                            )
                            
                except httpx.TimeoutException as e:
                    poll_elapsed = time_module.time() - poll_start_time if 'poll_start_time' in locals() else 0
                    print(f"WARNING: Poll attempt {attempt + 1} timed out after {poll_elapsed:.2f} seconds", flush=True)
                    sys.stdout.flush()
                    if attempt < self.MAX_POLL_ATTEMPTS - 1:
                        # Use exponential backoff for timeout errors
                        wait_time = min(self.INITIAL_POLL_INTERVAL * (2 ** min(attempt // 3, 4)), self.MAX_POLL_INTERVAL)
                        wait_time = max(wait_time, self.MIN_POLL_INTERVAL)
                        print(f"INFO: Retrying after {wait_time:.1f} seconds (exponential backoff)...", flush=True)
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise ValueError(
                            f"REopt API polling timed out after {self.MAX_POLL_ATTEMPTS} attempts"
                        )
                except httpx.HTTPStatusError as e:
                    poll_elapsed = time_module.time() - poll_start_time if 'poll_start_time' in locals() else 0
                    print(f"[REoptService] ERROR http_status | code={e.response.status_code} | attempt={attempt + 1} | elapsed={poll_elapsed:.2f}s")
                    if e.response.status_code == 404:
                        # Job not found yet, use exponential backoff
                        wait_time = min(self.INITIAL_POLL_INTERVAL * (2 ** min(attempt // 3, 4)), self.MAX_POLL_INTERVAL)
                        wait_time = max(wait_time, self.MIN_POLL_INTERVAL)
                        print(f"INFO: Job not found (404), waiting {wait_time:.1f} seconds before retry (exponential backoff)...", flush=True)
                        if attempt < self.MAX_POLL_ATTEMPTS - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            raise ValueError(
                                f"REopt job {run_uuid} not found after {self.MAX_POLL_ATTEMPTS} attempts"
                            )
                    else:
                        raise ValueError(
                            f"REopt API returned error {e.response.status_code}: {e.response.text[:500]}"
                        )
                except Exception as e:
                    poll_elapsed = time_module.time() - poll_start_time if 'poll_start_time' in locals() else 0
                    error_type = type(e).__name__
                    print(f"[REoptService] ERROR poll_exception | type={error_type} | attempt={attempt + 1} | elapsed={poll_elapsed:.2f}s | error={str(e)[:100]}")
                    if attempt < self.MAX_POLL_ATTEMPTS - 1:
                        # Use exponential backoff for general errors
                        wait_time = min(self.INITIAL_POLL_INTERVAL * (2 ** min(attempt // 3, 4)), self.MAX_POLL_INTERVAL)
                        wait_time = max(wait_time, self.MIN_POLL_INTERVAL)
                        print(f"INFO: Retrying after {wait_time:.1f} seconds (exponential backoff)...", flush=True)
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise ValueError(
                            f"Failed to poll REopt results: {str(e)}"
                        )
            
            raise ValueError(
                f"REopt job {run_uuid} timed out after {self.MAX_POLL_ATTEMPTS} attempts"
            )
    
    def _extract_results(
        self, 
        results: Dict[str, Any],
        property_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract NPV, optimal system sizes, and recommended size from REopt results.
        
        Args:
            results: Complete results dictionary from REopt API
            property_type: Property type for policy_warning generation
            
        Returns:
            Dictionary containing npv, optimal_system_sizes, recommended_size_kw, and policy_warning
        """
        outputs = results.get("outputs", {})
        scenario = outputs.get("Scenario", {})
        site = scenario.get("Site", {})
        financial_outputs = outputs.get("Financial", {})
        
        
        # Extract NPV - REopt v3 API structure: outputs.Financial.npv
        # For third-party ownership, REopt may return NPV=0.0 when no system is optimal
        # We should still return 0.0 (not None) to indicate the optimization completed
        npv = None
        npv_value = financial_outputs.get("npv")
        
        # For third-party ownership, also check alternative NPV fields
        # But only if the main npv field is None (not if it's 0.0, as 0.0 is a valid result)
        if npv_value is None:
            npv_value = financial_outputs.get("offtaker_npv") or financial_outputs.get("offtaker_NPV")
        
        if npv_value is None:
            npv_value = financial_outputs.get("owner_npv") or financial_outputs.get("owner_NPV")
        
        # Convert to float - 0.0 is a valid NPV (means no system is optimal)
        if npv_value is not None:
            try:
                npv = float(npv_value)
            except (ValueError, TypeError) as e:
                print(f"[REoptService] ERROR npv_conversion | value={npv_value} | error={str(e)}")
                pass
        else:
            print(f"[REoptService] WARNING npv_not_found | checked_fields=npv,offtaker_npv,owner_npv")
        
        # Extract optimal system sizes
        optimal_system_sizes = {}
        recommended_size_kw = None
        
        # Extract PV size - REopt v3 API structure: outputs.Scenario.Site.PV.size_kw
        pv_obj = site.get("PV", {})
        pv_size = pv_obj.get("size_kw") or pv_obj.get("size_kW") or pv_obj.get("size")
        if pv_size is not None:
            try:
                pv_kw = float(pv_size)
                optimal_system_sizes["pv_kw"] = pv_kw
                recommended_size_kw = pv_kw  # Use PV size as recommended size
            except (ValueError, TypeError):
                pass
        
        # Extract storage size - REopt v3 API structure: outputs.Scenario.Site.Storage.size_kw and size_kwh
        storage_obj = site.get("Storage", {})
        if storage_obj:
            storage_kw = storage_obj.get("size_kw") or storage_obj.get("size_kW")
            storage_kwh = storage_obj.get("size_kwh") or storage_obj.get("size_kWh")
            if storage_kw is not None:
                try:
                    optimal_system_sizes["storage_kw"] = float(storage_kw)
                except (ValueError, TypeError):
                    pass
            if storage_kwh is not None:
                try:
                    optimal_system_sizes["storage_kwh"] = float(storage_kwh)
                except (ValueError, TypeError):
                    pass
        
        # Generate policy_warning for July 4th Safe Harbor (commercial projects)
        policy_warning = None
        if property_type in ["commercial", "industrial"]:
            from datetime import date
            current_date = date.today()
            cutoff_date = date(2026, 7, 4)
            if current_date < cutoff_date:
                policy_warning = (
                    "NOTE: You must commence construction by July 4, 2026, to lock in this 30% credit."
                )
        
        return {
            "npv": npv,
            "optimal_system_sizes": optimal_system_sizes,
            "recommended_size_kw": recommended_size_kw,
            "policy_warning": policy_warning
        }
    
    async def run_reopt_scenario_branching(
        self,
        lat: float,
        lon: float,
        load_profile_type: str = "residential",
        urdb_label: Optional[str] = None,
        zip_code: Optional[str] = None,
        additional_load_kw: float = 0.0,
        property_type: Optional[Literal["residential", "commercial", "industrial"]] = None
    ) -> Dict[str, Any]:
        """
        Run scenario branching for residential queries: Purchase vs Lease scenarios.
        
        For residential queries, runs two REopt simulations:
        - Scenario A (Purchase): fed_itc_fraction = 0.0, analysis_years = 25
        - Scenario B (Lease): fed_itc_fraction = 0.30, analysis_years = 25
        
        For commercial queries, runs single simulation with fed_itc_fraction = 0.30.
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            load_profile_type: Load profile type - "residential", "commercial", or "industrial"
            urdb_label: URDB label for the electric tariff
            zip_code: Zip code for URDB lookup
            additional_load_kw: Additional peak load in kW
            property_type: Property type - if None, inferred from load_profile_type
            
        Returns:
            Dictionary containing:
            - For residential: {"scenario_a": {...}, "scenario_b": {...}, "scenario_type": "residential"}
            - For commercial: {"scenario": {...}, "scenario_type": "commercial", "policy_flag": "..."}
        """
        if property_type is None:
            property_type = load_profile_type.lower()
        
        # For residential: Run both Purchase and Lease scenarios in parallel
        if property_type == "residential":
            # OPTIMIZATION: Run both scenarios concurrently using asyncio.gather()
            # This reduces total time from ~56s (sequential) to ~28-30s (parallel)
            # Both jobs run simultaneously on NREL's servers, reducing wait time
            scenario_a_task = self.run_reopt_optimization(
                lat=lat,
                lon=lon,
                load_profile_type=load_profile_type,
                urdb_label=urdb_label,
                zip_code=zip_code,
                additional_load_kw=additional_load_kw,
                property_type="residential",
                ownership_type="purchase"
            )
            
            scenario_b_task = self.run_reopt_optimization(
                lat=lat,
                lon=lon,
                load_profile_type=load_profile_type,
                urdb_label=urdb_label,
                zip_code=zip_code,
                additional_load_kw=additional_load_kw,
                property_type="residential",
                ownership_type="lease"
            )
            
            # Execute both scenarios in parallel
            scenario_a, scenario_b = await asyncio.gather(
                scenario_a_task,
                scenario_b_task,
                return_exceptions=True
            )
            
            # Handle exceptions if either scenario failed
            if isinstance(scenario_a, Exception):
                raise ValueError(f"Purchase scenario failed: {str(scenario_a)}") from scenario_a
            if isinstance(scenario_b, Exception):
                raise ValueError(f"Lease scenario failed: {str(scenario_b)}") from scenario_b
            
            return {
                "scenario_type": "residential",
                "scenario_a": {
                    "name": "Purchase",
                    "ownership_type": "purchase",
                    "fed_itc_fraction": 0.0,
                    "analysis_years": 25,
                    **scenario_a
                },
                "scenario_b": {
                    "name": "Lease",
                    "ownership_type": "lease",
                    "fed_itc_fraction": 0.30,
                    "analysis_years": 25,
                    **scenario_b
                }
            }
        
        # For commercial: Single scenario with 30% ITC and policy flag
        else:
            scenario_result = await self.run_reopt_optimization(
                lat=lat,
                lon=lon,
                load_profile_type=load_profile_type,
                urdb_label=urdb_label,
                zip_code=zip_code,
                additional_load_kw=additional_load_kw,
                property_type=property_type,
                ownership_type="purchase"  # Commercial purchase gets 30% ITC
            )
            
            # Add policy flag for July 4, 2026 construction deadline
            policy_flag = None
            if property_type in ["commercial", "industrial"]:
                from datetime import date
                current_date = date.today()
                cutoff_date = date(2026, 7, 4)
                if current_date < cutoff_date:
                    policy_flag = (
                        "NOTE: You must commence construction by July 4, 2026, "
                        "to lock in this 30% credit."
                    )
            
            return {
                "scenario_type": "commercial",
                "scenario": {
                    "name": "Commercial",
                    "property_type": property_type,
                    "fed_itc_fraction": 0.30,
                    "analysis_years": 25,
                    "policy_flag": policy_flag,
                    **scenario_result
                }
            }
    
    async def run_reopt_optimization(
        self,
        lat: float,
        lon: float,
        load_profile_type: str = "residential",
        urdb_label: Optional[str] = None,
        zip_code: Optional[str] = None,
        additional_load_kw: float = 0.0,
        property_type: Optional[Literal["residential", "commercial", "industrial"]] = None,
        ownership_type: Optional[Literal["purchase", "lease"]] = None,
        construction_start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run a REopt optimization analysis.
        
        This function:
        1. Builds the REopt API payload
        2. Submits the job to the /job endpoint
        3. Polls the /results endpoint until status is 'complete'
        4. Extracts and returns NPV and optimal system sizes
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            load_profile_type: Load profile type - "residential", "commercial", or "industrial"
            urdb_label: URDB label for the electric tariff (from URDB API)
                        If not provided, will attempt to look up from location
            zip_code: Zip code for URDB lookup
            additional_load_kw: Additional peak load in kW (e.g., EV chargers)
            property_type: Property type for tax credit policy rules ("residential", "commercial", "industrial")
                          If None, inferred from load_profile_type
            ownership_type: Ownership type for tax credit policy rules ("purchase", "lease")
                          If None, uses default from GlobalSettings
            construction_start_date: Construction start date in 'YYYY-MM-DD' format for commercial ITC calculation
                                     Required for commercial projects to determine 2026 OBBBA eligibility
            
        Returns:
            Dictionary containing:
            - npv: Net Present Value (float)
            - optimal_system_sizes: Dictionary with keys like "pv_kw", "storage_kw", "storage_kwh"
            
        Raises:
            ValueError: If optimization fails
        """
        import sys
        import time as time_module
        
        start_time = time_module.time()
        # If no URDB label provided, try to look one up from URDB API
        # REopt API requires a valid urdb_label in ElectricTariff
        if not urdb_label:
            try:
                # Fetch URDB rates using OpenEI API directly with coordinates
                # Try multiple sectors if the requested sector doesn't return results
                from app.services.urdb_service import OpenEISettings
                openei_settings = OpenEISettings()
                openei_api_key = openei_settings.openei_api_key
                
                # Try multiple approaches to find URDB label
                async with httpx.AsyncClient() as client:
                    # Approach 1: Try with zip code if available (more reliable)
                    if zip_code and zip_code.isdigit() and len(zip_code) == 5:
                        try:
                            params = {
                                "api_key": openei_api_key,
                                "version": "7",
                                "format": "json",
                                "zipcode": zip_code,
                                "limit": 10
                            }
                            
                            urdb_response = await client.get(
                                "https://api.openei.org/utility_rates",
                                params=params,
                                timeout=30.0
                            )
                            
                            if urdb_response.status_code == 200:
                                urdb_data = urdb_response.json()
                                items = urdb_data.get("items", [])
                                if items and len(items) > 0:
                                    first_rate = items[0]
                                    urdb_label = first_rate.get("label") or first_rate.get("urdb_label") or first_rate.get("id")
                                    if urdb_label:
                                        print(f"[REoptService] urdb_found | zip={zip_code} | label={urdb_label}")
                        except Exception as e:
                            print(f"[REoptService] ERROR urdb_fetch | method=zip | error={str(e)[:100]}")
                    
                    # Approach 2: Try sectors with lat/lon if zip code didn't work
                    if not urdb_label:
                        sectors_to_try = [load_profile_type]
                        if load_profile_type != "residential":
                            sectors_to_try.append("residential")
                        if load_profile_type != "commercial":
                            sectors_to_try.append("commercial")
                        if load_profile_type != "industrial":
                            sectors_to_try.append("industrial")
                        
                        for sector in sectors_to_try:
                            params = {
                                "api_key": openei_api_key,
                                "version": "7",
                                "format": "json",
                                "sector": sector,
                                "latitude": lat,
                                "longitude": lon,
                                "limit": 10
                            }
                            
                            try:
                                urdb_response = await client.get(
                                    "https://api.openei.org/utility_rates",
                                    params=params,
                                    timeout=30.0
                                )
                                
                                if urdb_response.status_code == 200:
                                    urdb_data = urdb_response.json()
                                    items = urdb_data.get("items", [])
                                    if items and len(items) > 0:
                                        first_rate = items[0]
                                        urdb_label = first_rate.get("label") or first_rate.get("urdb_label") or first_rate.get("id")
                                        if urdb_label:
                                            print(f"[REoptService] urdb_found | sector={sector} | label={urdb_label}")
                                            break
                            except Exception as sector_error:
                                print(f"[REoptService] ERROR urdb_fetch | sector={sector} | error={str(sector_error)[:100]}")
                                continue
                    
                    # Approach 3: Try without sector filter (get all sectors)
                    if not urdb_label:
                        try:
                            params = {
                                "api_key": openei_api_key,
                                "version": "7",
                                "format": "json",
                                "latitude": lat,
                                "longitude": lon,
                                "limit": 10
                            }
                            
                            urdb_response = await client.get(
                                "https://api.openei.org/utility_rates",
                                params=params,
                                timeout=30.0
                            )
                            
                            if urdb_response.status_code == 200:
                                urdb_data = urdb_response.json()
                                items = urdb_data.get("items", [])
                                if items and len(items) > 0:
                                    first_rate = items[0]
                                    urdb_label = first_rate.get("label") or first_rate.get("urdb_label") or first_rate.get("id")
                                    if urdb_label:
                                        print(f"[REoptService] urdb_found | method=no_sector | label={urdb_label}")
                        except Exception as e:
                            print(f"[REoptService] ERROR urdb_fetch | method=no_sector | error={str(e)[:100]}")
                    
                    if not urdb_label:
                        print(f"WARNING: Could not find URDB label for location (lat={lat}, lon={lon}, zip={zip_code})")
                        print(f"WARNING: This location may not have URDB data, or the URDB API may be unavailable")
            except Exception as e:
                print(f"WARNING: Could not look up URDB label: {str(e)}. REopt will fail without it.")
                import traceback
                traceback.print_exc()
        
        # Build payload
        payload = self._build_payload(
            lat=lat,
            lon=lon,
            load_profile_type=load_profile_type,
            urdb_label=urdb_label,
            additional_load_kw=additional_load_kw,
            property_type=property_type,
            ownership_type=ownership_type,
            construction_start_date=construction_start_date
        )
        
        # Submit job with circuit breaker
        async def _submit():
            return await self._submit_job(payload)
        
        run_uuid = await self.reopt_breaker.call(_submit)
        print(f"[REoptService] job_submitted | run_uuid={run_uuid}")
        
        # Poll results with circuit breaker
        async def _poll():
            import time as time_module
            poll_wrapper_start = time_module.time()
            try:
                result = await self._poll_results(run_uuid)
                poll_wrapper_elapsed = time_module.time() - poll_wrapper_start
                print(f"[REoptService] poll_complete | elapsed={poll_wrapper_elapsed:.2f}s")
                return result
            except Exception as e:
                poll_wrapper_elapsed = time_module.time() - poll_wrapper_start
                print(f"[REoptService] ERROR poll_failed | elapsed={poll_wrapper_elapsed:.2f}s | type={type(e).__name__} | error={str(e)[:100]}")
                raise
        
        try:
            results = await self.reopt_breaker.call(_poll)
            total_elapsed = time_module.time() - start_time
            print(f"[REoptService] optimization_complete | elapsed={total_elapsed:.2f}s")
        except Exception as e:
            total_elapsed = time_module.time() - start_time
            print(f"ERROR: Circuit breaker call failed after {total_elapsed:.2f}s: {type(e).__name__}: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            raise
        
        # Extract and return results with policy-aware extraction
        extracted = self._extract_results(
            results,
            property_type=property_type or load_profile_type.lower()
        )
        
        # Get policy notice from GlobalSettings
        global_settings = get_global_settings()
        financial_params = global_settings.get_financial_params(
            property_type=property_type or load_profile_type.lower(),
            ownership_type=ownership_type,
            construction_start_date=construction_start_date
        )
        
        # Add policy notice to extracted results
        extracted["policy_notice"] = financial_params.get("policy_notice", "")
        
        # Ensure policy_warning is included (may be None for non-commercial)
        # policy_warning is already set in _extract_results for commercial projects
        
        print(
            f"INFO: REopt optimization completed: NPV={extracted.get('npv')}, "
            f"Recommended size={extracted.get('recommended_size_kw')} kW, "
            f"System sizes={extracted.get('optimal_system_sizes')}"
        )
        
        return extracted

