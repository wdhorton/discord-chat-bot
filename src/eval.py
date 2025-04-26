from openai import OpenAI
import asyncio
from vector_emb import answer_question, llm_answer_question

client_openai = OpenAI()

async def main(message_content):
    # Get context for the question
    context = answer_question(message_content)
        
    # Ensure context is a string to avoid NoneType errors
    if context is None:
        context = "No specific context found."

    response = llm_answer_question(context, message_content)
    return response

if __name__ == "__main__":
    questions = open("data/eval/questions.txt", "r").readlines()
    responses = []
    for question in questions:
        print(f"Question: {question.strip()}")
        response = asyncio.run(main(question.strip()))
        responses.append(response)

    print("\n\nResponses:\n\n")
    for response in responses:
        print(response)

    # use pandas to save question and response as a tsv
    import pandas as pd
    df = pd.DataFrame({"Question": questions, "Response": responses})
    # add a uuid to the filename
    import uuid
    df.to_csv(f"data/eval/responses_{uuid.uuid4()}.tsv", sep="\t", index=False)