from typing import List, Dict, Any
from llama_index.core import Document
from llama_index.core.schema import TextNode


class DocumentService:
    """
    Service for converting NREL station data into LlamaIndex Document objects.
    """
    
    @staticmethod
    def stations_to_documents(stations: List[Dict[str, Any]]) -> List[Document]:
        """
        Convert NREL station data into LlamaIndex Document objects.
        
        Args:
            stations: List of station dictionaries from NREL API
            
        Returns:
            List of LlamaIndex Document objects
        """
        documents = []
        
        for station in stations:
            # Create a structured text representation of the station
            station_text = DocumentService._format_station_text(station)
            
            # Create metadata for the document
            metadata = DocumentService._extract_metadata(station)
            
            # Create Document with text and metadata
            doc = Document(
                text=station_text,
                metadata=metadata,
                id_=f"station_{station.get('id', len(documents))}"
            )
            
            documents.append(doc)
        
        return documents
    
    @staticmethod
    def _format_station_text(station: Dict[str, Any]) -> str:
        """
        Format station data into a natural language text representation.
        """
        parts = []
        
        # Station name
        if station.get("station_name"):
            parts.append(f"Station Name: {station['station_name']}")
        
        # Address
        address_parts = []
        if station.get("street_address"):
            address_parts.append(station["street_address"])
        if station.get("city"):
            address_parts.append(station["city"])
        if station.get("state"):
            address_parts.append(station["state"])
        if station.get("zip"):
            address_parts.append(station["zip"])
        
        if address_parts:
            parts.append(f"Address: {', '.join(address_parts)}")
        
        # Network
        if station.get("ev_network"):
            parts.append(f"Network: {station['ev_network']}")
        
        # Connector types
        if station.get("ev_connector_types"):
            connectors = ", ".join(station["ev_connector_types"])
            parts.append(f"Connector Types: {connectors}")
        
        # Charging ports
        charging_info = []
        if station.get("ev_dc_fast_num") and station["ev_dc_fast_num"] > 0:
            charging_info.append(f"{station['ev_dc_fast_num']} DC Fast Charging port(s)")
        if station.get("ev_level2_evse_num") and station["ev_level2_evse_num"] > 0:
            charging_info.append(f"{station['ev_level2_evse_num']} Level 2 Charging port(s)")
        
        if charging_info:
            parts.append(f"Charging Ports: {'; '.join(charging_info)}")
        
        # Access information
        if station.get("access_days_time"):
            parts.append(f"Access Hours: {station['access_days_time']}")
        
        # Location coordinates
        if station.get("latitude") and station.get("longitude"):
            parts.append(f"Location: {station['latitude']}, {station['longitude']}")
        
        return ". ".join(parts) + "."
    
    @staticmethod
    def _extract_metadata(station: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract relevant metadata from station data.
        """
        # Helper function to safely convert to int, handling None and string 'None'
        def safe_int(value, default=0):
            if value is None or value == "None" or str(value).lower() == "none":
                return default
            try:
                return int(value)
            except (ValueError, TypeError):
                return default
        
        # Helper function to safely convert to float, handling None and string 'None'
        def safe_float(value, default=None):
            if value is None or value == "None" or str(value).lower() == "none":
                return default
            try:
                return float(value)
            except (ValueError, TypeError):
                return default
        
        metadata = {
            "domain": "transportation",  # Domain tag for routing
            "station_id": station.get("id"),
            "station_name": station.get("station_name", ""),
            "city": station.get("city", ""),
            "state": station.get("state", ""),
            "zip": station.get("zip", ""),
            "network": station.get("ev_network", ""),
            "connector_types": ",".join(station.get("ev_connector_types", [])),
            "dc_fast_count": safe_int(station.get("ev_dc_fast_num"), 0),
            "level2_count": safe_int(station.get("ev_level2_evse_num"), 0),
            "latitude": safe_float(station.get("latitude")),
            "longitude": safe_float(station.get("longitude")),
        }
        
        # Remove None values
        return {k: v for k, v in metadata.items() if v is not None}
    
    @staticmethod
    def utility_rates_to_documents(utility_rates: Dict[str, Any], location: str = "") -> List[Document]:
        """
        Convert utility rates data into LlamaIndex Document objects.
        
        Args:
            utility_rates: Utility rates dictionary from NREL API
            location: Location string (zip code, city, etc.)
            
        Returns:
            List of LlamaIndex Document objects
        """
        documents = []
        
        # Handle different API response formats
        # NREL API may return data in various formats, so we need to be flexible
        if not utility_rates or (isinstance(utility_rates, dict) and not utility_rates):
            return documents
        
        # Format utility rates as text
        parts = []
        
        # Extract utility name (try multiple possible field names)
        utility_name = (
            utility_rates.get("utility_name") or 
            utility_rates.get("utility") or 
            utility_rates.get("name") or
            utility_rates.get("company_name") or
            ""
        )
        if utility_name:
            parts.append(f"Utility Company: {utility_name}")
        
        if location:
            parts.append(f"Location: {location}")
        
        # Extract rates (try multiple possible field names and formats)
        # NREL API might return rates in different formats, including nested structures
        residential_rate = None
        commercial_rate = None
        industrial_rate = None
        
        # Try direct field access first
        residential_rate = (
            utility_rates.get("residential_rate") or
            utility_rates.get("res_rate") or
            utility_rates.get("avg_residential_rate")
        )
        
        # Try nested structure: utility_rates["residential"]["rate"]
        if not residential_rate:
            residential_obj = utility_rates.get("residential")
            if isinstance(residential_obj, dict):
                residential_rate = (
                    residential_obj.get("rate") or
                    residential_obj.get("residential_rate") or
                    residential_obj.get("avg_rate")
                )
            elif isinstance(residential_obj, (int, float)):
                residential_rate = residential_obj
        
        # Try direct field access for commercial
        commercial_rate = (
            utility_rates.get("commercial_rate") or
            utility_rates.get("com_rate") or
            utility_rates.get("avg_commercial_rate")
        )
        
        # Try nested structure: utility_rates["commercial"]["rate"]
        if not commercial_rate:
            commercial_obj = utility_rates.get("commercial")
            if isinstance(commercial_obj, dict):
                commercial_rate = (
                    commercial_obj.get("rate") or
                    commercial_obj.get("commercial_rate") or
                    commercial_obj.get("avg_rate")
                )
            elif isinstance(commercial_obj, (int, float)):
                commercial_rate = commercial_obj
        
        # Try direct field access for industrial
        industrial_rate = (
            utility_rates.get("industrial_rate") or
            utility_rates.get("ind_rate") or
            utility_rates.get("avg_industrial_rate")
        )
        
        # Try nested structure: utility_rates["industrial"]["rate"]
        if not industrial_rate:
            industrial_obj = utility_rates.get("industrial")
            if isinstance(industrial_obj, dict):
                industrial_rate = (
                    industrial_obj.get("rate") or
                    industrial_obj.get("industrial_rate") or
                    industrial_obj.get("avg_rate")
                )
            elif isinstance(industrial_obj, (int, float)):
                industrial_rate = industrial_obj
        
        # Format rates for document text
        if residential_rate and residential_rate != "None" and str(residential_rate).lower() != "none":
            # Handle both numeric and string formats
            try:
                rate_val = float(residential_rate)
                parts.append(f"Residential Rate: ${rate_val:.4f}/kWh")
            except (ValueError, TypeError):
                parts.append(f"Residential Rate: {residential_rate}/kWh")
        
        if commercial_rate and commercial_rate != "None" and str(commercial_rate).lower() != "none":
            try:
                rate_val = float(commercial_rate)
                parts.append(f"Commercial Rate: ${rate_val:.4f}/kWh")
            except (ValueError, TypeError):
                parts.append(f"Commercial Rate: {commercial_rate}/kWh")
        
        if industrial_rate and industrial_rate != "None" and str(industrial_rate).lower() != "none":
            try:
                rate_val = float(industrial_rate)
                parts.append(f"Industrial Rate: ${rate_val:.4f}/kWh")
            except (ValueError, TypeError):
                parts.append(f"Industrial Rate: {industrial_rate}/kWh")
        
        # Extract EIA ID
        eiaid = (
            utility_rates.get("eiaid") or
            utility_rates.get("eia_id") or
            utility_rates.get("utility_id")
        )
        if eiaid:
            parts.append(f"EIA Utility ID: {eiaid}")
        
        # If we have any useful data, create a document
        # Even if we don't have rates, if we have utility name or location, create a document
        if parts or utility_name or location:
            # Create metadata
            metadata = {
                "domain": "utility",  # Domain tag for routing
                "utility_name": utility_name,
                "location": location,
                "residential_rate": residential_rate,
                "commercial_rate": commercial_rate,
                "industrial_rate": industrial_rate,
                "eiaid": str(eiaid) if eiaid else None,
            }
            
            # If location is a zip code (5 digits), also set it as "zip" metadata
            # This allows the retriever to filter by zip code
            if location and location.isdigit() and len(location) == 5:
                metadata["zip"] = location
            
            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            # Create document text - include all available data
            doc_text = ". ".join(parts) + "." if parts else f"Utility information for {location or 'unknown location'}."
            
            # Create document with unique ID
            doc_id = f"utility_{location}_{eiaid or utility_name or 'unknown'}"
            doc_id = doc_id.replace(" ", "_").replace(",", "_").lower()
            
            doc = Document(
                text=doc_text,
                metadata=metadata,
                id_=doc_id
            )
            
            documents.append(doc)
        
        return documents

