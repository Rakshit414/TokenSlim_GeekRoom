import openai

def query_model(prompt: str, model: str = "gpt-4o-mini") -> str:
    # Removed global method in OpenAI SDK v1.0+
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
