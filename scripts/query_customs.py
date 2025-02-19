#!/usr/bin/env python3
import os
import sys
import logging
from typing import Optional, Dict, List
from pathlib import Path
from dotenv import load_dotenv
from opensearchpy import OpenSearch
from langchain_ollama import OllamaLLM
from langgraph.graph import StateGraph
from langchain_core.messages import HumanMessage
from langchain.schema import Document
from pydantic import BaseModel, Field

# Завантажуємо .env файл
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Налаштування логування
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class CustomsState(BaseModel):
    question: str
    context: Optional[str] = None
    documents: List[Document] = Field(default_factory=list)
    response: Optional[str] = None
    error: Optional[str] = None

class OpenSearchRetriever:
    def __init__(self, client: OpenSearch, index_name: str, k: int = 10):
        self.client = client
        self.index_name = index_name
        self.k = k

    def get_relevant_documents(self, question: str) -> List[Document]:
        try:
            response = self.client.search(
                index=self.index_name,
                body={"query": {"match": {"product_description": question}}},
                size=self.k
            )
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                logger.warning("OpenSearch не повернув жодних результатів.")
            
            return [
                Document(
                    page_content=f"Декларація №{hit['_source'].get('declaration_number', 'N/A')}",
                    metadata={**hit["_source"], "score": hit.get("_score", 0)}
                ) for hit in hits
            ]
        except Exception as e:
            logger.error(f"Помилка під час отримання документів: {e}")
            return []

class CustomsAnalyzer:
    def __init__(self, llm: OllamaLLM):
        self.llm = llm

    def analyze_documents(self, state: CustomsState) -> CustomsState:
        if state.error:
            return state
        try:
            prompt = f"""
            Ти є професійним аналітиком митних декларацій.
            Проаналізуй наступні декларації:
            {state.context}
            Питання користувача:
            {state.question}
            """
            response = self.llm.invoke([HumanMessage(content=prompt)])
            if hasattr(response, "content"):
                state.response = response.content
            else:
                logger.error(f"Несподіваний формат відповіді від LLM: {response}")
                state.error = "Несподіваний формат відповіді від LLM"
        except Exception as e:
            state.error = str(e)
        return state

def check_opensearch_connection(client: OpenSearch) -> bool:
    try:
        return client.ping()
    except Exception as e:
        logger.error(f"OpenSearch недоступен: {e}")
        return False

def check_index_exists(client: OpenSearch, index_name: str) -> bool:
    try:
        return client.indices.exists(index=index_name)
    except Exception as e:
        logger.error(f"Помилка перевірки індексу {index_name}: {e}")
        return False

def retrieve_documents(state: CustomsState, retriever: OpenSearchRetriever) -> CustomsState:
    try:
        # Проверяем подключение к OpenSearch
        if not check_opensearch_connection(retriever.client):
            state.error = "OpenSearch сервер недоступний"
            return state
            
        # Проверяем существование индекса
        if not check_index_exists(retriever.client, retriever.index_name):
            state.error = f"Індекс {retriever.index_name} не існує"
            return state

        # Получаем документы
        state.documents = retriever.get_relevant_documents(state.question)
        if not state.documents:
            state.error = "Не знайдено відповідних документів"
            return state
        
        # Преобразуем документы в контекст
        context_parts = []
        for i, doc in enumerate(state.documents, 1):
            metadata_str = "\n".join(f"{k}: {v}" for k, v in doc.metadata.items() 
                                   if k not in ['score'] and v is not None)
            context_parts.append(
                f"Документ {i}:\n"
                f"{doc.page_content}\n"
                f"Додаткова інформація:\n{metadata_str}\n"
            )
        state.context = "\n".join(context_parts)
        logger.debug(f"Створено контекст із {len(state.documents)} документів")
        
    except Exception as e:
        logger.error(f"Помилка при пошуку документів: {e}")
        state.error = f"Помилка при пошуку документів: {str(e)}"
    return state

def create_customs_graph(analyzer: CustomsAnalyzer, retriever: OpenSearchRetriever) -> StateGraph:
    workflow = StateGraph(CustomsState)
    workflow.add_node("retrieve", lambda state: retrieve_documents(state, retriever))
    workflow.add_node("analyze", analyzer.analyze_documents)
    workflow.add_edge("retrieve", "analyze")
    workflow.set_entry_point("retrieve")
    return workflow.compile()

def initialize_opensearch() -> OpenSearch:
    return OpenSearch(hosts=[{"host": os.getenv("OPENSEARCH_HOST", "localhost"), "port": int(os.getenv("OPENSEARCH_PORT", 9200))}],
                      use_ssl=os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true",
                      verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true")

def initialize_ollama() -> OllamaLLM:
    return OllamaLLM(model=os.getenv("OLLAMA_MODEL", "mistral"),
                     temperature=0.7,
                     base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                     timeout=int(os.getenv("OLLAMA_TIMEOUT", 120)))

if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    if debug_mode:
        logger.setLevel(logging.DEBUG)
    
    try:
        opensearch_client = initialize_opensearch()
        if not check_opensearch_connection(opensearch_client):
            sys.exit(1)

        index_name = os.getenv("OPENSEARCH_INDEX_NAME", "customs_declarations")
        if not check_index_exists(opensearch_client, index_name):
            sys.exit(1)

        retriever = OpenSearchRetriever(opensearch_client, index_name)
        llm = initialize_ollama()
        analyzer = CustomsAnalyzer(llm)
        workflow = create_customs_graph(analyzer, retriever)
        
        logger.info("Система готова до роботи. Введіть ваш запит або 'exit' для виходу.")
        while True:
            try:
                question = input("\nВведіть ваш запит (або 'exit' для виходу): ").strip()
                if not question:
                    print("Запит не може бути порожнім")
                    continue
                if question.lower() == "exit":
                    break
                
                state = CustomsState(question=question)
                result = workflow.invoke(state)
                
                if result.error:
                    print(f"Помилка: {result.error}")
                elif result.response:
                    print(f"Відповідь: {result.response}")
                else:
                    print("Не вдалося отримати відповідь")
                    
            except KeyboardInterrupt:
                print("\nПерервано користувачем")
                break
            except Exception as e:
                logger.error(f"Помилка при обробці запиту: {e}")
                print(f"Виникла помилка: {e}")
                
    except KeyboardInterrupt:
        print("\nПрограму завершено користувачем")
    except Exception as e:
        logger.error(f"Критична помилка: {e}")
        sys.exit(1)
