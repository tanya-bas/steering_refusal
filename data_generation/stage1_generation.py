import litellm
import os
import json
import re
from dotenv import load_dotenv
from datetime import datetime

from data_generation.prompts import STRAGE_1_SYSTEM_PROMPT, STAGE_1_USER_PROMPT

load_dotenv()

os.environ["ANTHROPIC_API_KEY"] = os.getenv("ANTHOPIC_API_KEY")
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY")

HAZARD_CATEGORIES = ["Violent Crimes", "Non-Violent Crimes", "Sex-Related Crimes", "Child Sexual Exploitation", "Defamation", "Specialized Advice", "Privacy", "Intellectual Property", "Indiscriminate Weapons", "Hate", "Suicide & Self-Harm", "Sexual Content", "Elections", "Code Interpreter Abuse"]
MODELS = ["anthropic/claude-haiku-4-5", "openai/gpt-5-nano-2025-08-07", "gemini/gemini-2.5-flash-lite"]


def call_model(model_name, system_prompt, user_prompt):
    response = litellm.completion(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        thinking={
            "type": "enabled",
            "budget_tokens": 1024
        },
        drop_params=True,  # LiteLLM will drop unsupported params instead of erroring
    )
    # NOTE: uncomment this to get chain of thought reasoning
    # thinking = response.choices[0].message.reasoning_content
    messages = response.choices[0].message.content
    return messages


def clean_json_response(response_text):
    """Remove markdown code blocks from JSON response if present."""
    if isinstance(response_text, str):
        # Remove markdown code blocks (```json ... ``` or ``` ... ```)
        response_text = re.sub(r'^```(?:json)?\s*\n', '', response_text, flags=re.MULTILINE)
        response_text = re.sub(r'\n```\s*$', '', response_text, flags=re.MULTILINE)
        # Strip any leading/trailing whitespace
        response_text = response_text.strip()
    return response_text


user_prompt = STAGE_1_USER_PROMPT.format(parent_category = HAZARD_CATEGORIES[0], n = "10")

# Collect responses from all models
responses = []
for model_name in MODELS:
    print(f"Calling model: {model_name}")
    model_response = call_model(
        model_name=model_name, 
        system_prompt=STRAGE_1_SYSTEM_PROMPT, 
        user_prompt=user_prompt
    )
    try:
        if isinstance(model_response, str):
            # Clean markdown code blocks (Anthropic models often wrap JSON in ```json blocks)
            cleaned_response = clean_json_response(model_response)
            parsed_response = json.loads(cleaned_response)
        else:
            parsed_response = model_response
    except json.JSONDecodeError as e:
        print(f'JSON parsing failed for {model_name}: {e}')
        parsed_response = model_response
    
    responses.append({
        "model": model_name,
        "response": parsed_response,
        "parent_category": HAZARD_CATEGORIES[0],
        "n": "10"
    })

# Save responses to JSON file
output_filename = f"stage1_responses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
output_path = os.path.join("data_generation", output_filename)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)