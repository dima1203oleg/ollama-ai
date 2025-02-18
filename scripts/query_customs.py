#!/usr/bin/env python3
"""
Customs Data Query Tool using LangChain and Ollama
Requires Python 3.9+
"""

import os
import sys
import logging
from typing import Optional, Dict, Any
from datetime import datetime

import requests
from dotenv import load_dotenv
from opensearchpy import OpenSearch, OpenSearchException
from langchain.llms import Ollama
from langchain.agents import create_sql_agent
from langchain.agents.agent_toolkits import OpenSearchToolkit
from langchain.tools import OpenSearchQueryRun
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OpenSearchConfig(BaseModel):
    """OpenSearch connection configuration"""
    hosts: list = Field(default=[{'host': 'localhost', 'port': 9200}])
    index_name: str = Field(default="customs_declarations")
    use_ssl: bool = Field(default=False)
    verify_certs: bool = Field(default=False)
    http_compress: bool = Field(default=True)

class OllamaConfig(BaseModel):
    """Ollama configuration"""
    base_url: str = Field(default="http://localhost:11434")
    model: str = Field(default="llama2")
    timeout: int = Field(default=120)

class CustomsQueryTool:
    def __init__(
        self,
        opensearch_config: Optional[Dict[str, Any]] = None,
        ollama_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the Customs Query Tool"""
        # Load environment variables
        load_dotenv()
        
        # Initialize configurations
        self.opensearch_config = OpenSearchConfig(**(opensearch_config or {}))
        self.ollama_config = OllamaConfig(**(ollama_config or {}))
        
        # Initialize connections
        self._init_connections()

    def _init_connections(self) -> None:
        """Initialize connections to OpenSearch and Ollama"""
        try:
            # Initialize OpenSearch client
            self.client = OpenSearch(
                hosts=self.opensearch_config.hosts,
                http_compress=self.opensearch_config.http_compress,
                use_ssl=self.opensearch_config.use_ssl,
                verify_certs=self.opensearch_config.verify_certs,
            )
            
            # Check OpenSearch connection
            if not self.client.ping():
                raise ConnectionError("Could not connect to OpenSearch")
            
            # Initialize Ollama
            self.llm = Ollama(
                base_url=self.ollama_config.base_url,
                model=self.ollama_config.model,
                timeout=self.ollama_config.timeout
            )
            
            # Check Ollama connection
            self._check_ollama_connection()
            
            # Create OpenSearch toolkit
            self.toolkit = OpenSearchToolkit(
                client=self.client,
                index_name=self.opensearch_config.index_name
            )
            
            # Create the agent
            self.agent = create_sql_agent(
                llm=self.llm,
                toolkit=self.toolkit,
                verbose=True
            )
            
            logger.info("Successfully initialized all connections")
            
        except Exception as e:
            logger.error(f"Error initializing connections: {str(e)}")
            raise

    def _check_ollama_connection(self) -> None:
        """Check if Ollama is accessible"""
        try:
            response = requests.get(f"{self.ollama_config.base_url}/api/tags")
            if response.status_code != 200:
                raise ConnectionError(f"Ollama returned status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Could not connect to Ollama: {str(e)}")

    def query_data(self, question: str) -> str:
        """
        Query the customs data using natural language
        
        Args:
            question (str): Natural language question about the customs data
            
        Returns:
            str: Response from the agent
        """
        try:
            return self.agent.run(question)
        except Exception as e:
            logger.error(f"Error querying data: {str(e)}")
            return f"Error processing query: {str(e)}"

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the customs declarations index"""
        try:
            return self.client.indices.stats(index=self.opensearch_config.index_name)
        except OpenSearchException as e:
            logger.error(f"Error getting index stats: {str(e)}")
            return {}

def main():
    """Main function to run the customs query tool"""
    try:
        # Initialize the query tool
        query_tool = CustomsQueryTool()
        
        # Example questions
        example_questions = [
            "What is the total gross weight of all declarations?",
            "Show me the top 5 trading countries by invoice value",
            "What are the average customs values per product code?",
            "List all declarations with special mark 'ZZ'",
            "Show me the distribution of delivery terms"
        ]
        
        # Process each question
        for question in example_questions:
            print(f"\nQuestion: {question}")
            print("=" * 50)
            response = query_tool.query_data(question)
            print(f"Answer: {response}\n")
            
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()