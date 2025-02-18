#!/usr/bin/env python3
import os
import sys
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests
from dotenv import load_dotenv
from opensearchpy import OpenSearch, OpenSearchException
from langchain_ollama import OllamaLLM
from langchain.agents import AgentType, initialize_agent
from langchain.tools import Tool
from langchain.schema import Document
from pydantic import BaseModel, Field

class OpenSearchElasticSearchRetriever:
    """Custom implementation of OpenSearch retriever"""
    def __init__(self, client, index_name: str, k: int = 10):
        self.client = client
        self.index_name = index_name
        self.k = k

    def get_relevant_documents(self, query: str) -> List[Document]:
        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["*"]
                }
            },
            "size": self.k
        }
        result = self.client.search(index=self.index_name, body=body)
        hits = result.get("hits", {}).get("hits", [])
        documents = []
        for hit in hits:
            source = hit.get("_source", {})
            page_content = source.get("content", str(source))
            documents.append(Document(page_content=page_content))
        return documents

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
    model: str = Field(default="tulu3")  # Заменено llama2 на tulu3
    timeout: int = Field(default=120)

class CustomsQueryTool:
    def __init__(
        self,
        opensearch_config: Optional[Dict[str, Any]] = None,
        ollama_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the Customs Query Tool"""
        load_dotenv()
        self.opensearch_config = OpenSearchConfig(**(opensearch_config or {}))
        self.ollama_config = OllamaConfig(**(ollama_config or {}))
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
            
            if not self.client.ping():
                raise ConnectionError("Could not connect to OpenSearch")
            
            # Initialize Ollama с новым классом
            self.llm = OllamaLLM(
                base_url=self.ollama_config.base_url,
                model=self.ollama_config.model,
                timeout=self.ollama_config.timeout
            )
            
            self._check_ollama_connection()
            
            # Create OpenSearch retriever с новой реализацией
            self.retriever = OpenSearchElasticSearchRetriever(
                client=self.client,
                index_name=self.opensearch_config.index_name,
                k=10
            )
            
            # Create search tool
            search_tool = Tool(
                name="OpenSearch",
                func=self._search_documents,
                description="Searches customs declaration data. Input should be a search query string."
            )
            
            # Заменяем создание агента на initialize_agent
            self.agent_executor = initialize_agent(
                tools=[search_tool],
                llm=self.llm,
                agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                handle_parsing_errors=True
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

    def _search_documents(self, query: str) -> str:
        """Helper function to search documents in OpenSearch"""
        try:
            docs = self.retriever.get_relevant_documents(query)
            return "\n".join(doc.page_content for doc in docs)
        except Exception as e:
            return f"Error searching documents: {str(e)}"

    def query_data(self, question: str) -> str:
        """Query the customs data using natural language"""
        try:
            # Используем invoke вместо run
            result = self.agent_executor.invoke({"input": question})
            return result["output"]
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
        # Проверяем наличие файла с данными
        data_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data/customs_data.csv')
        if not os.path.exists(data_file):
            print("Файл с данными не найден. Сначала запустите select_input_files.py")
            sys.exit(1)
            
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