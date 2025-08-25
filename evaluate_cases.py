#!/usr/bin/env python3
"""
Script to evaluate legal research answers against gold standard cases.

This script:
1. Reads cases2021.csv (Fallbeschreibung and Rechtsprechung columns)
2. Sends each Fallbeschreibung to our legal research app
3. Compares the returned answer with the gold standard using OpenAI
4. Saves evaluation results to a new CSV file
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import traceback
import requests
import subprocess

# Add the client directory to the path so we can import agent_cli
sys.path.insert(0, str(Path(__file__).parent / "client"))

def get_legal_research_answer(question: str, model: str = None, provider: str = "nebius") -> str:
    """Get answer from our legal research app using agent_cli.py"""
    try:
        # Build command
        cmd = [sys.executable, "client/agent_cli.py", question]
        
        if model:
            cmd.extend(["--model", model])
        
        cmd.extend(["--provider", provider])
        
        # Run the legal research
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd=Path(__file__).parent,
            encoding='utf-8'
        )
#        print ("ORIGINAL RESULT: ", result)
        if result.returncode != 0:
            print(f"Error running legal research: {result.stderr}", file=sys.stderr)
            return f"ERROR: {result.stderr}"
        
        # Extract the final answer using the <final> tags
        raw_output = result.stdout.strip()
        
        # Look for the <final>...</final> tags
        start_tag = "<final>"
        end_tag = "</final>"
        
        start_pos = raw_output.find(start_tag)
        if start_pos != -1:
            # Found opening tag, look for closing tag
            start_pos += len(start_tag)
            end_pos = raw_output.find(end_tag, start_pos)
            
            if end_pos != -1:
                # Extract content between tags
                final_answer = raw_output[start_pos:end_pos].strip()
                if final_answer:
                    return final_answer
        
        # Fallback: if no <final> tags found, return error
        print ("ERROR IN LLM GENERATION")
        return f"ERROR: LLM generation"
        
    except subprocess.TimeoutExpired:
        return "ERROR: Timeout - research took longer than 5 minutes"
    except Exception as e:
        return f"ERROR: {str(e)}"

def get_openai_answer(
    question: str,
    api_key: str,
    model: str = "gpt-5-2025-08-07",
    timeout: int = 120,
    temperature: float = 0.2,
    system_prompt: str = "Du bist ein erfahrener juristischer Assistent. Antworte fundiert, präzise und auf Deutsch."
) -> str:
    """Get an answer directly from OpenAI (GPT-5) without using agent_cli."""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        user_prompt = (
            "Beantworte die folgende juristische Fallbeschreibung mit einer kurzen, präzisen rechtlichen Würdigung. "
            "Gib, falls möglich, maßgebliche Normen und Leitentscheidungen an.\n\n"
            f"Fallbeschreibung:\n{question}"
        )
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
#            "max_completion_tokens": 4000,
        }
#        print ("Data: ", data)
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
#            timeout=timeout,
        )
        if resp.status_code != 200:
            # Return a compact error message
            text = resp.text
            if isinstance(text, str) and len(text) > 500:
                text = text[:500] + "..."
            return f"ERROR: OpenAI answer API error {resp.status_code}: {text}"
#        js = resp.json()
        result = resp.json()
#        print ("Result: ", result)
        content = result["choices"][0]["message"]["content"]

#        content = js.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content.strip() or "ERROR: Empty response from OpenAI"
    except Exception as e:
        return f"ERROR: {str(e)}"

def evaluate_with_openai(
    question: str, 
    our_answer: str, 
    gold_answer: str, 
    api_key: str,
    model: str = "gpt-5"
) -> Dict[str, any]:
    """Evaluate our answer against gold standard using OpenAI"""
    
    # Truncate very long answers to avoid token limits
    max_answer_length = 8000  # chars
    if len(our_answer) > max_answer_length:
        our_answer = our_answer[:max_answer_length] + "\n\n[... Antwort wurde wegen Länge gekürzt ...]"
    if len(gold_answer) > max_answer_length:
        gold_answer = gold_answer[:max_answer_length] + "\n\n[... Gold-Antwort wurde wegen Länge gekürzt ...]"
    
    evaluation_prompt = f"""Du bist ein juristischer Experte und sollst die Antwort auf eine juristische Recherche-Arbeit bewerten und mit der Gold-Antwort vergleichen. Schätze die Korrektheit der Antwort auf einer Skala von 1 bis 10 ein und begründe. Bewerte nur die juristische Korrektheit und nicht die Form der Antwort.

Frage: {question}

Goldantwort:
{gold_answer}

Antwort:
{our_answer}

Antworte im JSON-Format:
{{
  "score": [1-10],
  "reasoning": "Detaillierte Begründung der Bewertung"
}}"""
#    print ("our answer: ", our_answer)
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
#        print ("###### Evaluation prompt: ", evaluation_prompt)
        data = {
            "model": model,
            "messages": [
#                {"role": "system", "content": "Du bist ein erfahrener juristischer Experte, der Rechtsrecherche-Antworten bewertet."},
                {"role": "user", "content": evaluation_prompt}
            ],
#            "temperature": 0.1,
            "max_completion_tokens": 8000
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        print ("RESPONSE: ", response.json())
        if response.status_code != 200:
            return {
                "score": -1,
                "reasoning": f"OpenAI API error: {response.status_code} - {response.text}",
                "raw_response": ""
            }
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
#        print ("Antwort: ",content)
        
        # Check if content is empty (due to length cutoff)
        if not content or content.strip() == "":
            return {
                "score": -1,
                "reasoning": f"OpenAI response was empty. Finish reason: {result['choices'][0].get('finish_reason', 'unknown')}. This often means the prompt was too long or hit token limits.",
                "raw_response": str(result)
            }
        
        # Try to extract JSON from response
        try:
            # Find JSON block in response
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
                evaluation = json.loads(json_str)
                return {
                    "score": evaluation.get("score", -1),
                    "reasoning": evaluation.get("reasoning", "No reasoning provided"),
                    "raw_response": content
                }
            else:
                # Fallback: try to parse entire content
                evaluation = json.loads(content)
                return {
                    "score": evaluation.get("score", -1),
                    "reasoning": evaluation.get("reasoning", "No reasoning provided"),
                    "raw_response": content
                }
        except json.JSONDecodeError:
            # Extract score from text if JSON parsing fails
            score = -1
            reasoning = content
            
            # Simple regex to find score
            import re
            score_match = re.search(r'"?score"?\s*:?\s*(\d+)', content)
            if score_match:
                score = int(score_match.group(1))
            
            return {
                "score": score,
                "reasoning": reasoning,
                "raw_response": content
            }
            
    except Exception as e:
        return {
            "score": -1,
            "reasoning": f"Error during evaluation: {str(e)}",
            "raw_response": ""
        }

def main():
    parser = argparse.ArgumentParser(description="Evaluate legal research answers against gold standard")
    parser.add_argument("--input", default="ludwig/cases2021.csv", help="Input CSV file path")
    parser.add_argument("--output", default="evaluation_results.csv", help="Output CSV file path")
    parser.add_argument("--start-row", type=int, default=0, help="Start from this row (0-based, excluding header)")
    parser.add_argument("--max-cases", type=int, default=None, help="Maximum number of cases to evaluate")
    parser.add_argument("--research-model", default=None, help="Model to use for legal research")
    parser.add_argument("--research-provider", default="nebius", choices=["nebius", "openrouter", "ollama"], help="Provider for legal research")
    parser.add_argument("--eval-model", default="gpt-5-2025-08-07", help="OpenAI model for evaluation")
    parser.add_argument("--openai-api-key", default=None, help="OpenAI API key (or set OPENAI_API_KEY env var)")
    parser.add_argument("--answer-source", default="agent", choices=["agent", "openai", "both"], help="Where to get answers from: internal agent_cli, direct OpenAI, or both")
    parser.add_argument("--openai-answer-model", default="gpt-5-2025-08-07", help="OpenAI model to use when --answer-source includes openai")
    
    args = parser.parse_args()
    
    # Setup OpenAI API key
    api_key = args.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OpenAI API key required. Set OPENAI_API_KEY env var or use --openai-api-key", file=sys.stderr)
        return 1
    
    # Check if input file exists
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file {input_path} not found", file=sys.stderr)
        return 1
    
    # Prepare output file
    output_path = Path(args.output)
    output_exists = output_path.exists()
    
    print(f"Reading cases from: {input_path}")
    print(f"Writing results to: {output_path}")
    print(f"Research provider: {args.research_provider}")
    if args.research_model:
        print(f"Research model: {args.research_model}")
    print(f"Evaluation model: {args.eval_model}")
    print()
    
    # Read input CSV and process cases
    try:
        with open(input_path, 'r', encoding='utf-8') as infile:
            csv_reader = csv.DictReader(infile, delimiter=';')
            
            # Skip to start row
            for _ in range(args.start_row):
                try:
                    next(csv_reader)
                except StopIteration:
                    print(f"Error: Start row {args.start_row} is beyond file length", file=sys.stderr)
                    return 1
            
            # Prepare output CSV
            fieldnames = [
                'fallnummer', 'fallbeschreibung', 'gold_answer',
                # Primary (legacy-compatible) columns
                'our_answer', 'evaluation_score', 'evaluation_reasoning', 'error', 'processing_time',
                # Agent-specific columns
                'our_answer_agent', 'evaluation_score_agent', 'evaluation_reasoning_agent', 'error_agent', 'processing_time_agent',
                # OpenAI-specific columns
                'our_answer_openai', 'evaluation_score_openai', 'evaluation_reasoning_openai', 'error_openai', 'processing_time_openai',
                'used_sources'
            ]
            
            with open(output_path, 'a' if output_exists else 'w', encoding='utf-8', newline='') as outfile:
                csv_writer = csv.DictWriter(outfile, fieldnames=fieldnames, delimiter=';')
                
                if not output_exists:
                    csv_writer.writeheader()
                
                processed = 0
                # Totals
                total_scores = {"agent": 0, "openai": 0}
                total_counts = {"agent": 0, "openai": 0}
                for i, row in enumerate(csv_reader, args.start_row + 1):
                    if args.max_cases and processed >= args.max_cases:
                        break
                    
                    fallnummer = row.get('Fallnummer', f'Case_{i}')
                    fallbeschreibung = row.get('Fallbeschreibung', '')
                    rechtsprechung = row.get('Rechtsprechung', '')
                    print ("Fallnummer: ", fallnummer)
#                    print ("Fallbeschreibung: ", fallbeschreibung)
#                    print ("Rechtsprechung: ", rechtsprechung)
                    if not fallbeschreibung.strip():
                        print(f"Skipping row {i}: empty Fallbeschreibung")
                        continue
                    
                    print(f"\n{'='*60}")
                    print(f"Processing case {processed + 1}: {fallnummer}")
                    print(f"Question: {fallbeschreibung[:20]}...{fallbeschreibung[-20:]}")
                    
                    used_sources = []
                    # Prepare per-source results
                    res_agent = {
                        "answer": "",
                        "score": -1,
                        "reason": "",
                        "error": "",
                        "time": 0.0,
                    }
                    res_openai = {
                        "answer": "",
                        "score": -1,
                        "reason": "",
                        "error": "",
                        "time": 0.0,
                    }

                    # Agent source
                    if args.answer_source in ("agent", "both"):
                        used_sources.append("agent")
                        start_time = time.time()
                        try:
                            print("Getting agent_cli answer...")
                            ans = get_legal_research_answer(
                                fallbeschreibung,
                                model=args.research_model,
                                provider=args.research_provider,
                            )
                            res_agent["answer"] = ans
                            if ans.startswith("ERROR:"):
                                print(f"Agent answer error: {ans}", file=sys.stderr)
                                res_agent["error"] = ans
                                res_agent["score"] = -1
                                res_agent["reason"] = "Could not get research answer"
                            else:
                                print(f"Agent answer length: {len(ans)} chars")
                                print("Evaluating agent answer with OpenAI...")
                                ev = evaluate_with_openai(
                                    fallbeschreibung,
                                    ans,
                                    rechtsprechung,
                                    api_key,
                                    model=args.eval_model,
                                )
                                res_agent["score"] = ev["score"]
                                res_agent["reason"] = ev["reasoning"]
                                if isinstance(res_agent["score"], int) and res_agent["score"] >= 0:
                                    total_scores["agent"] += res_agent["score"]
                                    total_counts["agent"] += 1
                                print(f"Agent evaluation score: {res_agent['score']}/10")
                        except Exception as e:
                            res_agent["error"] = f"Exception: {str(e)}"
                            res_agent["score"] = -1
                            res_agent["reason"] = f"Processing error: {str(e)}"
                            print(f"Agent processing error: {e}")
                            traceback.print_exc()
                        finally:
                            res_agent["time"] = time.time() - start_time

                    # OpenAI source
                    if args.answer_source in ("openai", "both"):
                        used_sources.append("openai")
                        start_time = time.time()
                        try:
                            print("Getting OpenAI direct answer...")
                            ans = get_openai_answer(
                                fallbeschreibung,
                                api_key=api_key,
                                model=args.openai_answer_model,
                            )
                            res_openai["answer"] = ans
                            if ans.startswith("ERROR:"):
                                print(f"OpenAI direct answer error: {ans}", file=sys.stderr)
                                res_openai["error"] = ans
                                res_openai["score"] = -1
                                res_openai["reason"] = "Could not get OpenAI answer"
                            else:
                                print(f"OpenAI answer length: {len(ans)} chars")
                                print("Evaluating OpenAI answer with OpenAI evaluator...")
                                ev = evaluate_with_openai(
                                    fallbeschreibung,
                                    ans,
                                    rechtsprechung,
                                    api_key,
                                    model=args.eval_model,
                                )
                                res_openai["score"] = ev["score"]
                                res_openai["reason"] = ev["reasoning"]
                                if isinstance(res_openai["score"], int) and res_openai["score"] >= 0:
                                    total_scores["openai"] += res_openai["score"]
                                    total_counts["openai"] += 1
                                print(f"OpenAI evaluation score: {res_openai['score']}/10")
                        except Exception as e:
                            res_openai["error"] = f"Exception: {str(e)}"
                            res_openai["score"] = -1
                            res_openai["reason"] = f"Processing error: {str(e)}"
                            print(f"OpenAI processing error: {e}")
                            traceback.print_exc()
                        finally:
                            res_openai["time"] = time.time() - start_time

                    # Compose legacy-primary columns (prefer agent, else openai)
                    primary_answer = res_agent["answer"] or res_openai["answer"]
                    primary_score = res_agent["score"] if res_agent["answer"] else res_openai["score"]
                    primary_reason = res_agent["reason"] if res_agent["answer"] else res_openai["reason"]
                    primary_error = res_agent["error"] if res_agent["answer"] else res_openai["error"]
                    primary_time = res_agent["time"] if res_agent["answer"] else res_openai["time"]

                    # Write result row
                    result_row = {
                        'fallnummer': fallnummer,
                        'fallbeschreibung': fallbeschreibung,
                        'gold_answer': rechtsprechung,
                        'our_answer': primary_answer,
                        'evaluation_score': primary_score,
                        'evaluation_reasoning': primary_reason,
                        'error': primary_error,
                        'processing_time': f"{primary_time:.1f}s",
                        'our_answer_agent': res_agent["answer"],
                        'evaluation_score_agent': res_agent["score"],
                        'evaluation_reasoning_agent': res_agent["reason"],
                        'error_agent': res_agent["error"],
                        'processing_time_agent': f"{res_agent['time']:.1f}s",
                        'our_answer_openai': res_openai["answer"],
                        'evaluation_score_openai': res_openai["score"],
                        'evaluation_reasoning_openai': res_openai["reason"],
                        'error_openai': res_openai["error"],
                        'processing_time_openai': f"{res_openai['time']:.1f}s",
                        'used_sources': ",".join(used_sources),
                    }

                    csv_writer.writerow(result_row)
                    outfile.flush()  # Ensure data is written immediately
                    
                    processed += 1
                    print(f"Processed {processed} cases so far...")
                    
                    # Small delay to avoid overwhelming services
                    time.sleep(1)
        
        print(f"\n{'='*60}")
        print(f"Completed! Processed {processed} cases.")
        # Print totals
        print("\nSummary of evaluation scores:")
        if 'agent' in locals():
            pass  # no-op
        # Agent totals
        print("- agent_cli:")
        if total_counts["agent"] > 0:
            avg_agent = total_scores["agent"] / total_counts["agent"]
            print(f"  sum={total_scores['agent']}, count={total_counts['agent']}, avg={avg_agent:.2f}")
        else:
            print("  no valid scores")
        # OpenAI totals
        print("- openai:")
        if total_counts["openai"] > 0:
            avg_openai = total_scores["openai"] / total_counts["openai"]
            print(f"  sum={total_scores['openai']}, count={total_counts['openai']}, avg={avg_openai:.2f}")
        else:
            print("  no valid scores")
        print(f"\nResults saved to: {output_path}")
        
        return 0
        
    except FileNotFoundError:
        print(f"Error: Could not find input file {input_path}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())