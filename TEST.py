from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv
import os

load_dotenv()



llm = ChatAnthropic(
    model="claude-haiku-4-5",  
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

response = llm.invoke("Mondj egy rövid magyar köszöntést!")
print(response.content)