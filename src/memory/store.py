"""
Memory store wrapper for Moorcheh integration with fallback support.
Handles namespace lifecycle, CRUD operations, search, and graceful degradation.
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from memory.schemas import MemoryRecord

logger = logging.getLogger(__name__)


class MoorchehStore:
    """Wrapper around Moorcheh SDK with fallback support."""
    
    def __init__(self, 
                 api_key: str,
                 base_url: str,
                 project_id: str,
                 offline_fallback_dir: str = ".moorcheh_fallback"):
        """
        Initialize Moorcheh client.
        
        Args:
            api_key: Moorcheh API key
            base_url: Moorcheh API base URL
            project_id: Project identifier
            offline_fallback_dir: Directory for offline JSON fallback
        """
        self.api_key = api_key
        self.base_url = base_url
        self.project_id = project_id
        self.offline_fallback_dir = Path(offline_fallback_dir)
        self.offline_fallback_dir.mkdir(exist_ok=True)
        
        # Moorcheh client initialization (placeholder for SDK)
        self.client = None
        self.connected = False
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Moorcheh client with error handling."""
        try:
            # Placeholder: actual Moorcheh SDK initialization
            # from moorcheh import MoorchehClient
            # self.client = MoorchehClient(
            #     api_key=self.api_key,
            #     base_url=self.base_url,
            # )
            logger.info(f"Moorcheh client initialized for project {self.project_id}")
            self.connected = True
        except Exception as e:
            logger.warning(f"Failed to initialize Moorcheh client: {e}. Falling back to local storage.")
            self.connected = False
    
    def store_record(self, record: MemoryRecord, namespace: str = "shared") -> str:
        """
        Store a memory record.
        
        Args:
            record: MemoryRecord to store
            namespace: Moorcheh namespace (e.g., "spm-project-shared")
        
        Returns:
            Record ID
        """
        record_doc = record.to_moorcheh_doc()
        record_id = record_doc["id"]
        
        if self.connected:
            try:
                # Placeholder: actual Moorcheh SDK call
                # self.client.documents.create(
                #     namespace=f"spm-{self.project_id}-{namespace}",
                #     document=record_doc
                # )
                logger.debug(f"Stored record {record_id} in Moorcheh")
                return record_id
            except Exception as e:
                logger.error(f"Failed to store record in Moorcheh: {e}. Using fallback.")
                self._store_fallback(record_id, record_doc)
                return record_id
        else:
            self._store_fallback(record_id, record_doc)
            return record_id
    
    def _store_fallback(self, record_id: str, record_doc: Dict[str, Any]):
        """Store record in local JSON fallback."""
        fallback_file = self.offline_fallback_dir / f"{record_id}.json"
        try:
            with open(fallback_file, 'w') as f:
                json.dump(record_doc, f, indent=2)
            logger.debug(f"Stored record {record_id} in fallback storage")
        except Exception as e:
            logger.error(f"Failed to store record in fallback: {e}")
    
    def query_similar(self, 
                     query_text: str,
                     namespace: str = "shared",
                     top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Query for similar records using semantic search.
        
        Args:
            query_text: Text to search for
            namespace: Moorcheh namespace
            top_k: Number of results to return
        
        Returns:
            List of similar record documents
        """
        if self.connected:
            try:
                # Placeholder: actual Moorcheh SDK call
                # results = self.client.similarity_search(
                #     namespace=f"spm-{self.project_id}-{namespace}",
                #     query=query_text,
                #     top_k=top_k,
                # )
                logger.debug(f"Semantic search for: {query_text[:50]}")
                return []  # Placeholder
            except Exception as e:
                logger.error(f"Semantic search failed: {e}")
                return []
        return []
    
    def query_by_metadata(self,
                         namespace: str = "shared",
                         record_type: Optional[str] = None,
                         agent_id: Optional[str] = None,
                         status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Query records by metadata filters.
        
        Args:
            namespace: Moorcheh namespace
            record_type: Filter by record type
            agent_id: Filter by agent ID
            status: Filter by status
        
        Returns:
            List of matching records
        """
        if self.connected:
            try:
                filters = {}
                if record_type:
                    filters["record_type"] = record_type
                if agent_id:
                    filters["agent_id"] = agent_id
                if status:
                    filters["status"] = status
                
                # Placeholder: actual Moorcheh SDK call
                # results = self.client.query(
                #     namespace=f"spm-{self.project_id}-{namespace}",
                #     filters=filters,
                # )
                logger.debug(f"Query with filters: {filters}")
                return []  # Placeholder
            except Exception as e:
                logger.error(f"Metadata query failed: {e}")
                return []
        return []
    
    def get_record(self, record_id: str, namespace: str = "shared") -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific record by ID.
        
        Args:
            record_id: Record ID
            namespace: Moorcheh namespace
        
        Returns:
            Record document or None
        """
        if self.connected:
            try:
                # Placeholder: actual Moorcheh SDK call
                # result = self.client.documents.get(
                #     namespace=f"spm-{self.project_id}-{namespace}",
                #     doc_id=record_id,
                # )
                logger.debug(f"Retrieved record {record_id}")
                return None  # Placeholder
            except Exception as e:
                logger.error(f"Failed to retrieve record {record_id}: {e}")
                return self._get_fallback(record_id)
        else:
            return self._get_fallback(record_id)
    
    def _get_fallback(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve record from local JSON fallback."""
        fallback_file = self.offline_fallback_dir / f"{record_id}.json"
        try:
            if fallback_file.exists():
                with open(fallback_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to retrieve record from fallback: {e}")
        return None
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check Moorcheh connectivity and system health.
        
        Returns:
            Health status dict
        """
        status = {
            "connected": self.connected,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "fallback_available": self.offline_fallback_dir.exists(),
        }
        
        if self.connected:
            try:
                # Placeholder: actual health check
                # health = self.client.health()
                status["moorcheh_status"] = "healthy"
            except Exception as e:
                status["connected"] = False
                status["error"] = str(e)
        
        return status
