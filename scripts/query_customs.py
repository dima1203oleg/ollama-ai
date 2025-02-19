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

# Завантажуємо .env файл
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OpenSearchElasticSearchRetriever:
    """Custom implementation of OpenSearch retriever"""
    def __init__(self, client, index_name: str, k: int = 10):
        self.client = client
        self.index_name = index_name
        self.k = k

    def get_relevant_documents(self, question: str) -> List[Document]:
        """Get relevant documents based on query"""
        try:
            query = {
                "bool": {
                    "must": [
                        {"match": {"product_description": question}}
                    ]
                }
            }

            response = self.client.search(
                index=self.index_name,
                body={"query": query},
                size=20
            )
            
            documents = []
            for hit in response["hits"]["hits"]:
                source = hit.get("_source", {})
                metadata = source
                metadata.update({
                    "score": hit.get("_score", 0),
                    "id": hit.get("_id", ""),
                })
                
                content = (
                    f"Декларація №{source.get('declaration_number', 'N/A')}\n"
                    f"Товар: {source.get('product_description', 'N/A')}\n"
                    f"Митниця: {source.get('customs_office', 'N/A')}\n"
                    f"Вартість: {source.get('invoice_value', 0)} USD\n"
                    f"Дата: {source.get('processing_date', 'N/A')}\n"
                    f"Країна: {source.get('origin_country', 'N/A')}\n"
                )
                documents.append(Document(page_content=content, metadata=metadata))
            
            return documents
        except Exception as e:
            logger.error(f"Error retrieving documents: {e}")
            return []

class CustomsQueryTool:
    PROMPT_TEMPLATE = """
    Ти є професійним аналітиком митних декларацій. Відповідай українською мовою.
    
    Проаналізуй наступні декларації та надай структурований звіт:
    {context}
    
    Питання користувача:
    {question}
    
    Надай чітку структуровану відповідь на основі наданих даних. Якщо інформації недостатньо, вкажи це.
    Зверни особливу увагу на:
    - Загальну кількість знайдених декларацій
    - Діапазон цін та середню вартість
    - Основні митниці оформлення
    - Країни відправлення
    """

    def __init__(self, retriever: OpenSearchElasticSearchRetriever, agent_executor):
        self.retriever = retriever
        self.agent_executor = agent_executor

    def query_data(self, question: str) -> str:
        """Query the customs data using natural language"""
        try:
            docs = self.retriever.get_relevant_documents(question)
            logger.info(f"Знайдено {len(docs)} документів для запиту: {question}")

            if not docs:
                return "Не знайдено відповідних даних."

            context = ""
            for doc in docs:
                source = doc.metadata
                context += f"""
                **Декларація №{source.get('declaration_number', 'Немає')}:**
                - **Товар:** {source.get('product_description', 'Невідомо')}
                - **Митниця:** {source.get('customs_office', 'Невідомо')}
                - **Вартість:** {source.get('invoice_value', '0')} USD
                - **Дата:** {source.get('processing_date', 'Невідомо')}
                - **Країна відправлення:** {source.get('origin_country', 'Невідомо')}
                ---
                """

            formatted_prompt = self.PROMPT_TEMPLATE.format(
                question=question,
                context=context
            )

            logger.info("Передаю запит у Ollama")
            result = self.agent_executor.invoke({
                "input": formatted_prompt,
                "context": context
            })

            return result.get("output", "Не вдалося згенерувати відповідь.")

        except Exception as e:
            logger.error(f"Error querying data: {str(e)}")
            return f"Помилка обробки запиту: {str(e)}"

def initialize_opensearch():
    """Initialize OpenSearch client with configuration from environment"""
    return OpenSearch(
        hosts=[{
            "host": os.getenv("OPENSEARCH_HOST", "localhost"),
            "port": int(os.getenv("OPENSEARCH_PORT", 9200))
        }],
        use_ssl=os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true",
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
    )

def initialize_ollama():
    """Initialize Ollama LLM with configuration from environment"""
    return OllamaLLM(
        model=os.getenv("OLLAMA_MODEL", "mistral"),
        temperature=0.7,
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        timeout=int(os.getenv("OLLAMA_TIMEOUT", 120))
    )

if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    if debug_mode:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled")

    try:
        # Initialize OpenSearch
        opensearch_client = initialize_opensearch()
        retriever = OpenSearchElasticSearchRetriever(
            client=opensearch_client,
            index_name=os.getenv("OPENSEARCH_INDEX_NAME", "customs_declarations")
        )

        # Initialize Ollama
        llm = initialize_ollama()

        # Create tools list
        tools = [
            Tool(
                name="Customs Data Query",
                func=lambda x: "This is a placeholder for customs data query result",
                description="Query customs declaration data"
            )
        ]

        # Initialize the agent
        agent_executor = initialize_agent(
            tools,
            llm,
            agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            verbose=debug_mode
        )

        # Initialize the query tool
        query_tool = CustomsQueryTool(retriever, agent_executor)

        # Interactive loop
        logger.info("Система готова до роботи. Введіть ваш запит або 'exit' для виходу.")
        while True:
            try:
                question = input("\nВведіть ваш запит (або 'exit' для виходу): ")
                if question.lower() == 'exit':
                    break
                print("=" * 50)
                response = query_tool.query_data(question)
                print(f"Відповідь: {response}\n")
            except KeyboardInterrupt:
                print("\nПрограму завершено користувачем")
                break
            except Exception as e:
                logger.error(f"Помилка при обробці запиту: {e}")
                if debug_mode:
                    raise
                print(f"Виникла помилка при обробці запиту. Спробуйте ще раз.")

    except Exception as e:
        logger.error(f"Критична помилка при ініціалізації системи: {e}")
        if debug_mode:
            raise
        sys.exit(1)