#!/usr/bin/env python3
import os
import sys
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests
import pandas as pd
from dotenv import load_dotenv
from opensearchpy import OpenSearch, OpenSearchException
from opensearchpy.helpers import bulk
from langchain_ollama import OllamaLLM
from langchain.agents import AgentType, initialize_agent
from langchain.tools import Tool, StructuredTool
from langchain.schema import Document
from pydantic import BaseModel, Field
from pathlib import Path

# Загружаем .env файл
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class OpenSearchElasticSearchRetriever:
    """Custom implementation of OpenSearch retriever"""
    def __init__(self, client, index_name: str, k: int = 10):
        self.client = client
        self.index_name = index_name
        self.k = k

    def get_relevant_documents(self, question: str) -> List[Document]:
        """Get relevant documents based on query"""
        try:
            # Add filters for strategic goods
            strategic_codes = [
                '8526920090',  # Radio control equipment
                '8807300090',  # UAV components
                '8501320090',  # Electric motors
                '8525890010',  # Transmitting equipment
                '8517620000'   # Communication equipment
            ]
            
            # Build query with filters
            query = {
                "bool": {
                    "should": [
                        {"terms": {"product_code": strategic_codes}},
                        {"match_phrase": {
                            "product_description": {
                                "query": "безпілотн"
                            }
                        }},
                        {"match_phrase": {
                            "product_description": {
                                "query": "дрон"
                            }
                        }}
                    ],
                    "minimum_should_match": 1
                }
            }
            
            response = self.client.search(
                index=self.index_name,
                body={"query": query},
                size=20
            )
            
            # Process results
            documents = []
            for hit in response["hits"]["hits"]:
                source = hit.get("_source", {})
                metadata = {
                    "score": hit.get("_score", 0),
                    "id": hit.get("_id", ""),
                }
                # Форматируем данные для лучшей читаемости
                content = (
                    f"Декларация №{source.get('declaration_number', 'N/A')}\n"
                    f"Товар: {source.get('product_description', 'N/A')}\n"
                    f"Таможня: {source.get('customs_office', 'N/A')}\n"
                    f"Стоимость: {source.get('invoice_value', 0)} USD\n"
                    f"Вес нетто: {source.get('net_weight', 0)} кг\n"
                    f"Дата: {source.get('processing_date', 'N/A')}\n"
                )
                documents.append(Document(page_content=content, metadata=metadata))
            
            return documents
        except Exception as e:
            logger.error(f"Error retrieving documents: {e}")
            return []

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
    base_url: str = Field(default=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'))
    model: str = Field(default=os.getenv('OLLAMA_MODEL', 'tulu3:latest'))  # Берем из .env
    timeout: int = Field(default=int(os.getenv('OLLAMA_TIMEOUT', 120)))

class CustomsSearchInput(BaseModel):
    query: str
    mitnica: Optional[str] = None
    year: Optional[int] = None

class CustomsQueryTool:
    PROMPT_TEMPLATE = """
    You are a professional customs declaration analyst. Your task is to provide accurate information based on Ukrainian customs declarations. Please provide answers in Ukrainian language only.

    Context:
    1. Data Analysis Parameters:
       * Product descriptions and codes
       * Values (USD)
       * Weight (kg)
       * Country of origin
       * Customs office
       * Sender and receiver
       * Delivery terms
       * Declaration numbers and dates

    2. Focus Areas:
       - Specific product categories
       - Codes according to Ukrainian Customs Code
       - Special import categories
       - Strategic goods and components

    3. Response Requirements:
       - Always provide in Ukrainian language
       - Group similar items together
       - List all relevant customs declaration numbers
       - Include values in USD
       - Specify customs offices and dates
       - Note any special permissions or conditions

    4. Data Details:
       - Main product characteristics
       - Unit and total costs in USD
       - Net/gross weight in kg
       - Origin country
       - Processing customs office
       - Additional important information

    5. Special Instructions:
       - Clearly indicate if data is missing
       - Provide available information for incomplete records
       - Give summarized statistics for large volumes
       - Focus on strategic/special goods categories

    Question: {question}

    Available Data:
    {context}
    """

    def __init__(
        self,
        opensearch_config: Optional[Dict[str, Any]] = None,
        ollama_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the Customs Query Tool"""
        load_dotenv()
        self.opensearch_config = OpenSearchConfig(**(opensearch_config or {}))
        self.ollama_config = OllamaConfig(**(ollama_config or {}))
        self.prompt_template = self.PROMPT_TEMPLATE
        self._init_connections()

    def _init_connections(self) -> None:
        """Initialize connections to OpenSearch and Ollama"""
        try:
            # Initialize OpenSearch client and retriever
            self.client = OpenSearch(
                hosts=self.opensearch_config.hosts,
                http_compress=self.opensearch_config.http_compress,
                use_ssl=self.opensearch_config.use_ssl,
                verify_certs=self.opensearch_config.verify_certs,
            )
            
            if not self.client.ping():
                raise ConnectionError("Could not connect to OpenSearch")
            
            self.llm = OllamaLLM(
                base_url=self.ollama_config.base_url,
                model=self.ollama_config.model,
                timeout=self.ollama_config.timeout
            )
            
            self._check_ollama_connection()
            
            self.retriever = OpenSearchElasticSearchRetriever(
                client=self.client,
                index_name=self.opensearch_config.index_name,
                k=10
            )
            
            # Create structured search tool
            self.search_tool = StructuredTool(
                name="CustomsSearch",
                description="Search customs declarations",
                func=self.search_customs,
                args_schema=CustomsSearchInput
            )
            
            # Initialize agent with structured tool
            self.agent_executor = initialize_agent(
                tools=[self.search_tool],
                llm=self.llm,
                agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                handle_parsing_errors=True,
                agent_kwargs={
                    "system_message": "Ти - асистент з аналізу митних декларацій. Відповідай українською мовою."
                }
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

    def search_customs(self, input: CustomsSearchInput) -> str:
        """
        Поиск в таможенных декларациях
        Args:
            input: Структурированный запрос
        Returns:
            str: Результат поиска
        """
        try:
            query = {
                "bool": {
                    "must": [
                        {"match": {"product_description": input.query}}
                    ]
                }
            }
            
            if input.mitnica:
                query["bool"]["must"].append(
                    {"match": {"customs_office": input.mitnica}}
                )
                
            if input.year:
                query["bool"]["must"].append(
                    {"match": {"processing_date": str(input.year)}}
                )
                
            return self._search_documents(query)
            
        except Exception as e:
            logger.error(f"Error searching customs data: {e}")
            return f"Error: {str(e)}"

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
            # Получаем документы и формируем контекст
            docs = self.retriever.get_relevant_documents(question)
            if not docs:
                return "Не знайдено відповідних даних за вашим запитом."
            
            context = "\n---\n".join([doc.page_content for doc in docs])
            
            # Форматируем промпт
            formatted_prompt = self.prompt_template.format(
                question=question,
                context=context
            )
            
            # Выполняем запрос
            result = self.agent_executor.invoke({
                "input": formatted_prompt,
                "context": context  # Добавляем контекст явно
            })
            
            return result.get("output", "Не вдалося згенерувати відповідь.")
            
        except Exception as e:
            logger.error(f"Error querying data: {str(e)}")
            return f"Помилка обробки запиту: {str(e)}"

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the customs declarations index"""
        try:
            return self.client.indices.stats(index=self.opensearch_config.index_name)
        except OpenSearchException as e:
            logger.error(f"Error getting index stats: {str(e)}")
            return {}

    def setup_index(self) -> None:
        """Проверка существования индекса"""
        try:
            if not self.client.indices.exists(index=self.opensearch_config.index_name):
                logger.error(f"Индекс {self.opensearch_config.index_name} не существует.")
                logger.error("Пожалуйста, сначала запустите select_input_files.py для создания и наполнения индекса.")
                sys.exit(1)
            
            # Проверяем маппинг
            mapping = self.client.indices.get_mapping(index=self.opensearch_config.index_name)
            if not mapping:
                logger.error("Маппинг индекса отсутствует")
                sys.exit(1)
                
            # Получаем статистику индекса
            stats = self.client.indices.stats(index=self.opensearch_config.index_name)
            doc_count = stats['indices'][self.opensearch_config.index_name]['total']['docs']['count']
            logger.info(f"Найдено {doc_count} документов в индексе {self.opensearch_config.index_name}")
            
        except Exception as e:
            logger.error(f"Ошибка при проверке индекса: {str(e)}")
            raise

column_mapping = {
    'date': 'processing_date',
    'product': 'product_description', 
    'quantity': 'quantity',
    'value': 'invoice_value',
    'country': 'origin_country',
    'customs': 'customs_office',
    'declaration_type': 'declaration_type',
    'sender': 'sender',
    'receiver': 'recipient',
    'receiver_code': 'recipient_code',
    'declaration_number': 'declaration_number',
    'trading_country': 'trading_country',
    'sending_country': 'shipping_country',
    'delivery_terms': 'delivery_terms', 
    'delivery_place': 'delivery_location',
    'unit': 'unit',
    'weight_gross': 'gross_weight',
    'weight_net': 'net_weight',
    'customs_weight': 'customs_weight',
    'special_mark': 'special_mark',
    'contract': 'contract_type',
    'trademark': 'trade_mark',
    'product_code': 'product_code',
    'calculated_invoice_value_usd_kg': 'calculated_invoice_value_usd_kg',
    'weight_unit': 'unit_weight',
    'weight_diff': 'weight_difference',
    'calculated_customs_value_net_usd_kg': 'calculated_customs_value_net_usd_kg',
    'calculated_customs_value_usd_add': 'calculated_customs_value_usd_add_unit',
    'calculated_customs_value_gross_usd_kg': 'calculated_customs_value_gross_usd_kg',
    'min_base_usd_kg': 'min_base_usd_kg',
    'min_base_diff': 'min_base_difference',
    'cz_net_usd_kg': 'customs_value_net_usd_kg',
    'cz_diff_usd_kg': 'customs_value_difference_usd_kg',
    'preferential': 'preferential_rate',
    'full': 'full_rate'
}

def main():
    """Main function to run the customs query tool"""
    try:
        # Initialize the query tool
        query_tool = CustomsQueryTool()
        
        # Проверяем индекс
        query_tool.setup_index()
        logger.info("Проверка индекса завершена")
        
        while True:
            # Интерактивный ввод вопроса
            question = input("\nВведите ваш вопрос (или 'exit' для выхода): ")
            
            if question.lower() == 'exit':
                break
                
            print("=" * 50)
            response = query_tool.query_data(question)
            print(f"Ответ: {response}\n")
            
    except Exception as e:
        logger.error(f"Ошибка выполнения: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()