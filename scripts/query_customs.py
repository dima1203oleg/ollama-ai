#!/usr/bin/env python3
import os
import sys
import logging
import time
from typing import Optional, Dict, List, Any
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestError, ConnectionError
from langchain_ollama import OllamaLLM
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.schema import Document
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Configure logging with rotation
from logging.handlers import RotatingFileHandler
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "customs_query.log"

handler = RotatingFileHandler(
    log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
)
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[handler, logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class CustomsState(BaseModel):
    """Enhanced state model with validation"""
    question: str
    context: Optional[str] = None
    documents: List[Document] = Field(default_factory=list)
    response: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    from pydantic import field_validator

    @field_validator('question')
    @classmethod
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("Question cannot be empty")
        return v.strip()

    def update_error(self, error_msg: str) -> None:
        self.error = error_msg

    def update_response(self, response_msg: str) -> None:
        self.response = response_msg

class OpenSearchRetriever:
    """Enhanced OpenSearch retriever with advanced querying capabilities"""
    def __init__(
        self, 
        client: OpenSearch, 
        index_name: str, 
        k: int = 10,
        timeout: int = 30
    ):
        self.client = client
        self.index_name = index_name
        self.k = k
        self.timeout = timeout
        
        # Проверяем существование индекса при инициализации
        if not self.client.indices.exists(index=self.index_name):
            logger.error(f"Index {self.index_name} does not exist!")
            raise ValueError(f"Index {self.index_name} not found")
        
        # Получаем количество документов в индексе
        count = self.client.count(index=self.index_name)
        logger.info(f"Connected to index {self.index_name}, containing {count['count']} documents")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def get_relevant_documents(self, question: str) -> List[Document]:
        """Enhanced search with advanced query and error handling"""
        try:
            search_query = {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "multi_match": {
                                    "query": question,
                                    "fields": [
                                        "product_description^3",
                                        "product_code^2",
                                        "customs_office",
                                        "declaration_type",
                                        "origin_country",
                                        "trade_mark"
                                    ],
                                    "type": "best_fields",
                                    "operator": "or",
                                    "minimum_should_match": "30%",
                                    "fuzziness": "AUTO"
                                }
                            },
                            {
                                "match_phrase_prefix": {
                                    "product_description": {
                                        "query": question,
                                        "boost": 2
                                    }
                                }
                            }
                        ],
                        "minimum_should_match": 1
                    }
                },
                "sort": [
                    {"_score": {"order": "desc"}},
                    {"processing_date": {"order": "desc"}}
                ],
                "timeout": f"{self.timeout}s"
            }

            # Логируем детали запроса
            logger.debug(f"Search query: {search_query}")

            response = self.client.search(
                index=self.index_name,
                body=search_query,
                size=self.k
            )

            hits = response.get("hits", {})
            total = hits.get("total", {}).get("value", 0)
            max_score = hits.get("max_score", 0)
            
            logger.info(f"Found {total} documents, max score: {max_score}")

            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                logger.warning("No results found in OpenSearch.")
                return []

            documents = []
            for hit in hits:
                source = hit["_source"]
                
                metadata = {
                    "declaration_number": source.get("declaration_number", "N/A"),
                    "processing_date": source.get("processing_date", "N/A"),
                    "customs_office": source.get("customs_office", "N/A"),
                    "product_code": source.get("product_code", "N/A"),
                    "net_weight": source.get("net_weight", 0),
                    "gross_weight": source.get("gross_weight", 0),
                    "invoice_value": source.get("invoice_value", 0),
                    "unit": source.get("unit", "шт"),
                    "quantity": source.get("quantity", 0),
                    "origin_country": source.get("origin_country", "N/A"),
                    "trade_mark": source.get("trade_mark", "N/A"),
                    "score": hit.get("_score", 0)
                }

                documents.append(
                    Document(
                        page_content=source.get("product_description", ""),
                        metadata=metadata
                    )
                )

            return documents

        except ConnectionError as e:
            logger.error(f"OpenSearch connection error: {e}")
            raise
        except RequestError as e:
            logger.error(f"OpenSearch request error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during document retrieval: {e}")
            raise

class CustomsAnalyzer:
    """Enhanced analyzer with improved prompting and response handling"""
    def __init__(self, llm: OllamaLLM):
        self.llm = llm

    def analyze_documents(self, state: CustomsState) -> CustomsState:
        if state.error:
            return state

        if not state.context or len(state.context) < 10:
            state.error = "Недостатньо даних для аналізу"
            return state

        try:
            # Enhanced system prompt for better context
            system_prompt = """Ви професійний аналітик митних декларацій з глибоким знанням українських митних правил та міжнародної торгівлі.
Ваше завдання - аналізувати ТІЛЬКИ надані митні декларації та відповідати ВИКЛЮЧНО на основі інформації з них.

При аналізі враховуйте:
1. Точні дані з декларацій (дати, номери, суми)
2. Фактичні коди УКТЗЕД та їх опис з документів
3. Конкретні значення мита та податків
4. Реальну вагу та характеристики товару
5. Наявні обмеження та вимоги

НЕ ДОДАВАЙТЕ інформацію, якої немає в наданих деклараціях.
НЕ РОБІТЬ припущень про тарифи чи обмеження.

Базуйтесь тільки на наданих документах та надавайте конкретні дані з них.
Відповідайте українською мовою, чітко структуруючи відповідь."""

            # Enhanced user prompt with specific guidance
            user_prompt = f"""Проаналізуйте наступні митні декларації та надайте детальну відповідь:

Контекст документів:
{state.context}

Запитання користувача:
{state.question}

Вкажіть у відповіді:
- Точні дати та номери декларацій
- Конкретні суми та вартість з документів
- Фактичні коди УКТЗЕД та їх опис
- Застосовані ставки мита та податків
- Вагу та інші фізичні характеристики товару
"""

            # Send both system and user messages
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]

            response = self.llm.invoke(messages)
            
            if isinstance(response, HumanMessage):
                state.update_response(response.content)
            elif hasattr(response, "content"):
                state.update_response(response.content)
            else:
                logger.error(f"Unexpected LLM response format: {response}")
                state.update_error("Неочікуваний формат відповіді від моделі")

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            state.set_error(str(e))

        return state

def initialize_opensearch() -> OpenSearch:
    """Enhanced OpenSearch initialization with connection pooling"""
    return OpenSearch(
        hosts=[{
            "host": os.getenv("OPENSEARCH_HOST", "localhost"),
            "port": int(os.getenv("OPENSEARCH_PORT", 9200))
        }],
        use_ssl=os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true",
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true",
        timeout=30,
        max_retries=3,
        retry_on_timeout=True,
        maxsize=25  # connection pool size
    )

def initialize_ollama() -> OllamaLLM:
    """Enhanced Ollama initialization with better error handling"""
    return OllamaLLM(
        model=os.getenv("OLLAMA_MODEL", "mistral"),
        temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        timeout=int(os.getenv("OLLAMA_TIMEOUT", "120")),
        retry_on_failure=True,
        num_retries=3
    )

def create_customs_graph(analyzer: CustomsAnalyzer, retriever: OpenSearchRetriever) -> StateGraph:
    """Enhanced workflow graph with error handling"""
    workflow = StateGraph(CustomsState)
    
    # Add nodes with error handling
    workflow.add_node("retrieve", lambda state: retrieve_documents(state, retriever))
    workflow.add_node("analyze", analyzer.analyze_documents)
    
    # Simplified edge configuration
    workflow.add_edge("retrieve", "analyze")
    workflow.add_edge("analyze", END)
    workflow.set_entry_point("retrieve")
    
    return workflow.compile()

def retrieve_documents(state: CustomsState, retriever: OpenSearchRetriever) -> CustomsState:
    """Enhanced document retrieval with better error handling and validation"""
    try:
        state.documents = retriever.get_relevant_documents(state.question)
        
        if not state.documents:
            state.error = "Не знайдено відповідних документів"
            return state
        
        # Enhanced context building with better formatting
        context_parts = []
        for i, doc in enumerate(state.documents, 1):
            metadata = doc.metadata
            context_parts.append(
                f"Декларація №{metadata.get('declaration_number')}\n"
                f"Дата оформлення: {metadata.get('processing_date')}\n"
                f"Код товару: {metadata.get('product_code')}\n"
                f"Опис: {doc.page_content}\n"
                f"Вага нетто: {metadata.get('net_weight')} кг\n"
                f"Кількість: {metadata.get('quantity')} {metadata.get('unit')}\n"
                f"Вартість: {metadata.get('invoice_value')} USD\n"
                f"Країна походження: {metadata.get('origin_country')}\n"
                f"Торгова марка: {metadata.get('trade_mark')}\n"
                f"Митний орган: {metadata.get('customs_office')}\n"
                "---\n"
            )
        
        state.context = "\n".join(context_parts)
        
    except Exception as e:
        logger.error(f"Error during document retrieval: {e}")
        state.error = f"Помилка при пошуку документів: {str(e)}"
    
    return state

def main():
    """Enhanced main function with better error handling and user interaction"""
    try:
        # Initialize components
        opensearch_client = initialize_opensearch()
        index_name = os.getenv("OPENSEARCH_INDEX_NAME", "customs_declarations")
        
        try:
            retriever = OpenSearchRetriever(opensearch_client, index_name)
        except ValueError as e:
            logger.error(f"Failed to initialize retriever: {e}")
            print(f"Помилка: {e}")
            sys.exit(1)
            
        llm = initialize_ollama()
        analyzer = CustomsAnalyzer(llm)
        workflow = create_customs_graph(analyzer, retriever)
        
        logger.info("Система готова до роботи. Введіть ваш запит або 'exit' для виходу.")
        
        while True:
            try:
                question = input("\nВведіть ваш запит (або 'exit' для виходу): ").strip()
                
                if question.lower() == "exit":
                    break
                    
                if not question:
                    print("Запит не може бути порожнім")
                    continue
                
                # Process query with timeout
                start_time = time.time()
                state = CustomsState(question=question)
                result = workflow.invoke(state)
                
                # Log processing time
                processing_time = time.time() - start_time
                logger.info(f"Query processed in {processing_time:.2f} seconds")
                
                if isinstance(result, dict):
                    if result.get('error'):
                        print(f"Помилка: {result['error']}")
                    elif result.get('response'):
                        print(f"Відповідь:\n{result['response']}")
                    else:
                        print("Не вдалося отримати відповідь")
                elif isinstance(result, CustomsState):
                    if result.error:
                        print(f"Помилка: {result.error}")
                    elif result.response:
                        print(f"Відповідь:\n{result.response}")
                    else:
                        print("Не вдалося отримати відповідь")
                else:
                    print("Неочікуваний формат відповіді")
                
            except KeyboardInterrupt:
                print("\nПерервано користувачем")
                break
            except Exception as e:
                logger.error(f"Error processing query: {e}")
                print(f"Виникла помилка: {e}")
                
    except KeyboardInterrupt:
        print("\nПрограму завершено користувачем")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()