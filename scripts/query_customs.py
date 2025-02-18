from langchain.llms import Ollama
from langchain.agents import create_sql_agent
from langchain.agents.agent_toolkits import OpenSearchToolkit
from langchain.tools import OpenSearchQueryRun
from opensearchpy import OpenSearch

# Configure OpenSearch client
client = OpenSearch(
    hosts=[{'host': 'localhost', 'port': 9200}],
    http_compress=True,
    use_ssl=False,
    verify_certs=False,
)

# Initialize Ollama
llm = Ollama(base_url='http://localhost:11434', model="llama2")

# Create OpenSearch toolkit
toolkit = OpenSearchToolkit(client=client, index_name="customs_declarations")

# Create the agent
agent = create_sql_agent(
    llm=llm,
    toolkit=toolkit,
    verbose=True
)

def query_data(question: str):
    """
    Query the customs data using natural language
    """
    response = agent.run(question)
    return response

# Example usage
if __name__ == "__main__":
    questions = [
        "What is the total gross weight of all declarations?",
        "Show me all declarations with invoice value greater than 5000",
        "What are the most common trading countries?"
    ]
    
    for question in questions:
        print(f"\nQuestion: {question}")
        print("Answer:", query_data(question))