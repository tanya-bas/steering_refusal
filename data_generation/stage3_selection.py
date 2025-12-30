import litellm
import os
import json
import re
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict


from data_generation.prompts import STAGE_3_SYSTEM_PROMPT, STAGE_3_USER_PROMPT
from data_generation.stage1_generation import call_model, clean_json_response

load_dotenv()

os.environ["ANTHROPIC_API_KEY"] = os.getenv("ANTHOPIC_API_KEY")
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY")

# Stage 3 uses Claude Haiku for selection
SELECTION_MODEL = "anthropic/claude-haiku-4-5"


def load_stage2_evaluations(filepath):
    """Load stage 2 evaluations from JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def prepare_subcategories_for_selection(evaluations):
    """
    Prepare all subcategories with their evaluation summaries for selection.
    Groups evaluations by unique subcategory and returns a list of subcategory summaries.
    """
    # Group evaluations by unique subcategory (parent_category, subcategory_name, model_generated) -> used as a key
    grouped = defaultdict(list)
    for evaluation in evaluations:
        key = (
            evaluation["parent_category"],
            evaluation["subcategory_name"],
            evaluation["model_generated"]
        )
        grouped[key].append(evaluation)
    
    subcategories_data = []
    
    for (parent_category, subcategory_name, model_generated), eval_list in grouped.items():
        # Get the subcategory content (should be the same across all evaluations)
        subcategory_data = eval_list[0]["content_evaluated"]
        
        # Calculate average score
        scores = [e["score"] for e in eval_list if e.get("score") is not None]
        avg_score = sum(scores) / len(scores) if scores else None
        
        # Prepare evaluation summaries
        evaluations_summary = []
        for eval_record in eval_list:
            eval_summary = {
                "model_evaluated": eval_record["model_evaluated"],
                "score": eval_record["score"],
                "reasoning": eval_record.get("reasoning", ""),
                "strengths": eval_record.get("strengths", []),
                "weaknesses": eval_record.get("weaknesses", [])
            }
            evaluations_summary.append(eval_summary)
        
        subcategory_summary = {
            "name": subcategory_name,
            "subcategory": subcategory_data,
            "model_generated": model_generated,
            "average_score": avg_score,
            "evaluations": evaluations_summary,
            "num_evaluations": len(eval_list)
        }
        
        subcategories_data.append(subcategory_summary)
    
    return subcategories_data


def select_subcategories(selection_model, parent_category, subcategories_data, num_models, min_select, max_select):
    """Have the selection model review all subcategories and select n-2n of them."""
    # format it as json -> better for model to use as an input 
    all_subcategories_json = json.dumps(subcategories_data, indent=2, ensure_ascii=False)
    
    user_prompt = STAGE_3_USER_PROMPT.format(
        parent_category=parent_category,
        num_models=num_models,
        total_subcategories=len(subcategories_data),
        min_select=min_select,
        max_select=max_select,
        all_subcategories_json=all_subcategories_json
    )
    
    selection_response = call_model(
        model_name=selection_model,
        system_prompt=STAGE_3_SYSTEM_PROMPT,
        user_prompt=user_prompt
    )
    # parse json (NOTE: there are some times problems with Claude json)
    try:
        if isinstance(selection_response, str):
            cleaned_response = clean_json_response(selection_response)
            parsed_selection = json.loads(cleaned_response)
        else:
            parsed_selection = selection_response
    except json.JSONDecodeError as e:
        print(f'    JSON parsing failed for {selection_model}: {e}')
        parsed_selection = {"error": str(e), "raw_response": selection_response}
    
    return parsed_selection


def main():
    # TODO: modify this to auto-detect the latest
    stage2_file = "data_generation/stage2_evaluations_20251230_134301.json"
    
    if not os.path.exists(stage2_file):
        print(f"Error: file not found: {stage2_file}")
        return
    
    evaluations = load_stage2_evaluations(stage2_file)
    
    parent_category = evaluations[0]["parent_category"] if evaluations else "Unknown"

    subcategories_data = prepare_subcategories_for_selection(evaluations)
    num_models = len(set(subcat["model_generated"] for subcat in subcategories_data)_
    
    min_select = 5
    max_select = 10
    
    selection_result = select_subcategories(
        selection_model=SELECTION_MODEL,
        parent_category=parent_category,
        subcategories_data=subcategories_data,
        num_models=num_models,
        min_select=min_select,
        max_select=max_select
    )
    
    selected_names = selection_result.get("selected_subcategory_names", [])
    
    # Create a mapping of subcategory names to their data for quick lookup
    subcategory_map = {subcat["name"]: subcat for subcat in subcategories_data}
    selected_scores = []
    selected_subcategories_details = []
    
    for name in selected_names:
        if name in subcategory_map:
            subcat_data = subcategory_map[name]
            avg_score = subcat_data.get("average_score")
            if avg_score is not None:
                selected_scores.append(avg_score)
            
            # Extract full subcategory details
            # NOTE: not sure if this is the most optimal way to do this
            subcategory_content = subcat_data.get("subcategory", {})
            selected_subcategories_details.append({
                "name": name,
                "description": subcategory_content.get("description", ""),
                "rationale": subcategory_content.get("rationale", ""),
                "dimensions": {
                    "abstractness": {
                        "score": subcategory_content.get("dimensions", {}).get("abstractness", {}).get("score"),
                        "justification": subcategory_content.get("dimensions", {}).get("abstractness", {}).get("justification", "")
                    },
                    "severity": {
                        "score": subcategory_content.get("dimensions", {}).get("severity", {}).get("score"),
                        "justification": subcategory_content.get("dimensions", {}).get("severity", {}).get("justification", "")
                    },
                    "morality": {
                        "score": subcategory_content.get("dimensions", {}).get("morality", {}).get("score"),
                        "justification": subcategory_content.get("dimensions", {}).get("morality", {}).get("justification", "")
                    },
                    "legality": {
                        "score": subcategory_content.get("dimensions", {}).get("legality", {}).get("score"),
                        "justification": subcategory_content.get("dimensions", {}).get("legality", {}).get("justification", "")
                    }
                },
                "model_generated": subcat_data.get("model_generated", ""),
                "average_evaluation_score": avg_score
            })
    
    average_score = sum(selected_scores) / len(selected_scores) if selected_scores else None
    llm_selection_summary = selection_result.get("selection_summary", {})
    
    # Create output with selected subcategory names and details
    output_data = {
        "parent_category": parent_category,
        "num_models": num_models,
        "total_candidates": len(subcategories_data),
        "selection_range": f"{min_select}-{max_select}",
        "num_selected": len(selected_names),
        "selected_subcategory_names": selected_names,
        "selected_subcategories": selected_subcategories_details,  # Full details with name, description, rationale, and dimension scores
        "reasoning": selection_result.get("reasoning", ""),
        "selection_summary": {
            "total_selected": len(selected_names),  
            "average_score": round(average_score, 2) if average_score is not None else None,  
            "quality_notes": llm_selection_summary.get("quality_notes", ""),
            "diversity_notes": llm_selection_summary.get("diversity_notes", "")
        },
        "model_selected": SELECTION_MODEL
    }
    
    # Save selection to JSON file
    output_filename = f"stage3_selections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path = os.path.join("data_generation", output_filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"Selected {len(selected_names)} subcategories:")
    for name in selected_names:
        print(f"  - {name}")


if __name__ == "__main__":
    main()

