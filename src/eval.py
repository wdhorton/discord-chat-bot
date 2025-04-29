from openai import OpenAI
import asyncio
from vector_emb import answer_question, COMPLETION_MODEL
import os

COMPLETION_MODEL = "gpt-3.5-turbo-16k"

SYSTEM_PROMPT = """You are a helpful workshop assistant.
Answer questions based only on the workshop transcript sections provided.
If you don't know the answer or can't find it in the provided sections, say so."""

model_name = COMPLETION_MODEL

def llm_answer_question(context, question):
    client_openai = OpenAI()
    try:
        # Make the API call
        response = client_openai.chat.completions.create(
            model=COMPLETION_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Workshop Transcript Sections:\n{context}\n\nQuestion: {question}"}
            ],
            temperature=0
        )
        
        answer = response.choices[0].message.content
        return answer

    except Exception as e:
        error_message = f"Sorry, an error occurred: {str(e)}"
        return error_message


def llm_gemini_answer_question(context, question):
    import google.generativeai as genai

    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    # Use the Google Gemini model to generate a response
    # Select the model
    # Use 'gemini-1.5-flash' or 'gemini-pro' based on availability and preference
    model = genai.GenerativeModel('gemini-1.5-flash') 

    # Construct the prompt
    prompt = f"Answer the question: {question}\n\nUse the following context:\n{context}"

    # Generate content using the Gemini model
    response = model.generate_content(prompt)

    # Extract the generated text from the response
    # Add error handling in case the response doesn't contain text
    try:
        generated_text = response.text
    except Exception as e:
        print(f"Error extracting text from Gemini response: {e}")
        generated_text = "Sorry, I couldn't generate a response."


    return generated_text

async def main(message_content):
    # Get context for the question
    context = answer_question(message_content)
        
    # Ensure context is a string to avoid NoneType errors
    if context is None:
        context = "No specific context found."

    response = llm_answer_question(context, message_content)
    
    
    return response, model_name

if __name__ == "__main__":
    questions = open("data/eval/questions.txt", "r").readlines()
    responses = []
    for question in questions:
        print(f"Question: {question.strip()}")
        response, model_name = asyncio.run(main(question.strip()))
        responses.append(response)

    print("\n\nResponses:\n\n")
    for response in responses:
        print(response)

    # use pandas to save question and response as a tsv
    import pandas as pd
    df = pd.DataFrame({"Model": model_name,"Question": questions, "Response": responses})
    # add a uuid to the filename
    import uuid
    df.to_csv(f"data/eval/responses_{uuid.uuid4()}.tsv", sep="\t", index=False)