import os
import threading
import logging

import pytest

from wiseagents import WiseAgentMessage, WiseAgentMetaData, WiseAgentRegistry
from wiseagents.agents import CoVeChallengerRAGWiseAgent, PassThroughClientAgent
from wiseagents.llm import OpenaiAPIWiseAgentLLM
from wiseagents.transports import StompWiseAgentTransport
from wiseagents.vectordb import Document, PGVectorLangChainWiseAgentVectorDB
from tests.wiseagents import assert_standard_variables_set

cond = threading.Condition()
assertError : AssertionError = None


@pytest.fixture(scope="session", autouse=True)
def run_after_all_tests():
    assert_standard_variables_set()
    # Vector DB set up
    pg_vector_db = PGVectorLangChainWiseAgentVectorDB(get_connection_string())
    pg_vector_db.delete_collection("wise-agents-collection")
    pg_vector_db.insert_documents([Document(content="The Olympics took place in Paris in 2024",
                                            metadata={"source": "abc.com"}),
                                   Document(content="The Olympics were held from July 26, 2024 to August 11, 2024",
                                            metadata={"source": "abc.com"}),
                                   Document(content="The US received the most medals at the 2024 Olympics.",
                                            metadata={"source": "abc.com"}),
                                   Document(content="Simone Biles, from the US, won 4 Olympic medals in 2024.",
                                            metadata={"source": "abc.com"})
                                   ],
                                  "wise-agents-collection")
    yield

    # Vector DB clean up
    pg_vector_db.delete_collection("wise-agents-collection")


def get_connection_string():
    return f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@localhost:6024/{os.environ['POSTGRES_DB']}"


def response_delivered(message: WiseAgentMessage):
    global assertError
    with cond:
        response = message.message
        try:
            assert "4 medals" not in response
        except AssertionError:
            assertError = AssertionError
        print(f"C Response delivered: {response}")
        cond.notify()


def test_cove_challenger():
    try:
        global assertError
        groq_api_key = os.getenv("GROQ_API_KEY")
        
        pg_vector_db = PGVectorLangChainWiseAgentVectorDB(get_connection_string())
        llm1 = OpenaiAPIWiseAgentLLM(system_message="You are a retrieval augmented chatbot. You answer users' questions based on the context provided by the user. If you can't answer the question using the given context, just say you don't know the answer.",
                                    model_name="llama-3.1-70b-versatile", remote_address="https://api.groq.com/openai/v1",
                                    api_key=groq_api_key)
        agent = CoVeChallengerRAGWiseAgent(name="ChallengerWiseAgent1", metadata=WiseAgentMetaData(description="This is a test agent"), llm=llm1, vector_db=pg_vector_db,
                                transport=StompWiseAgentTransport(host='localhost', port=61616, agent_name="ChallengerWiseAgent1"),
                                        k=2, num_verification_questions=2)

        with cond:
            client_agent1 = PassThroughClientAgent(name="PassThroughClientAgent1", metadata=WiseAgentMetaData(description="This is a test agent"),
                                                transport=StompWiseAgentTransport(host='localhost', port=61616, agent_name="PassThroughClientAgent1")
                                                )
            client_agent1.set_response_delivery(response_delivered)
            client_agent1.send_request(WiseAgentMessage(f"{{'question': 'How many medals did Biles win at the Winter Olympics in 2024?'\n"
                                                        f"  'response': 'Biles won 4 medals.'\n"
                                                        f"}}",
                                                        "PassThroughClientAgent1"),
                                    "ChallengerWiseAgent1")
            cond.wait()
            if assertError is not None:
                raise assertError
            logging.debug(f"registered agents= {WiseAgentRegistry.fetch_agents_metadata_dict()}")
            for message in WiseAgentRegistry.get_or_create_context('default').message_trace:
                logging.debug(f'{message}')
    finally:        
        #stopping the agents
        client_agent1.stop_agent()
        agent.stop_agent()
