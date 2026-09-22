import os
import re
import json
import numpy as np
from openai import OpenAI
from typing import List, Dict, Tuple

# Initialize the OpenAI Client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ProductionHallucinationAuditorV2:
    def __init__(self, reference_context: str, weights: Dict[str, float] = None):
        self.reference = reference_context
        self.weights = weights or {
            "semantic": 0.4,
            "entity": 0.4,
            "negation_penalty": 0.2
        }
        self.clean_ref, _ = self._isolate_structure(self.reference)
        # Pre-calculate reference embeddings and entity tokens to save latency
        self.ref_sentences = self._segment_sentences(self.clean_ref)
        self.ref_embeddings = [self._get_embedding(s) for s in self.ref_sentences]
        self.ref_tokens = set(re.findall(r'\b[A-Z0-9][a-z0-9]*\b', self.clean_ref))

    def _isolate_structure(self, text: str) -> Tuple[str, List[str]]:
        structure_pattern = r"(\|.*\||\`\`\`[\s\S]*?\`\`\`)"
        structures = re.findall(structure_pattern, text)
        cleaned_text = re.sub(structure_pattern, " [STRUCTURE_BLOCK] ", text)
        return cleaned_text, structures

    def _segment_sentences(self, text: str) -> List[str]:
        sentence_end = r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s'
        return [s.strip() for s in re.split(sentence_end, text) if s.strip()]

    def _get_embedding(self, text: str) -> List[float]:
        """Calculates vector embedding locally via OpenAI API."""
        if not text.strip():
            return [0.0] * 1536
        response = client.embeddings.create(
            input=[text],
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def _calculate_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        dot_product = np.dot(vec1, vec2)
        norm_a = np.linalg.norm(vec1)
        norm_b = np.linalg.norm(vec2)
        return float(dot_product / (norm_a * norm_b)) if norm_a and norm_b else 0.0

    def _calculate_entity_adherence(self, draft_sentence: str) -> float:
        draft_entities = set(re.findall(r'\b[A-Z0-9][a-z0-9]*\b', draft_sentence))
        if not draft_entities:
            return 1.0
        matched_entities = draft_entities.intersection(self.ref_tokens)
        return len(matched_entities) / len(draft_entities)

    def evaluate(self, generated_draft: str) -> Dict:
        clean_draft, structures = self._isolate_structure(generated_draft)
        draft_sentences = self._segment_sentences(clean_draft)
        
        failed_segments = []
        cumulative_penalty = 0.0
        
        for idx, sentence in enumerate(draft_sentences):
            sentence_embedding = self._get_embedding(sentence)
            
            # Formula Part 1: Embedding Vector Semantic Overlap (Max similarity match against source sentences)
            semantic_score = max([self._calculate_cosine_similarity(sentence_embedding, ref_vec) for ref_vec in self.ref_embeddings]) if self.ref_embeddings else 0.0
            
            # Formula Part 2: Entity Adherence Gate
            entity_score = self._calculate_entity_adherence(sentence)
            
            # Formula Part 3: Negation Match
            sentence_tokens = set(sentence.lower().split())
            negation_words = {"not", "never", "no", "won't", "cannot", "denies", "none"}
            has_negation = 1.0 if not sentence_tokens.intersection(negation_words) else 0.0
            
            # Combine via Matrix Formula
            weighted_score = (self.weights["semantic"] * semantic_score) + (self.weights["entity"] * entity_score)
            if has_negation == 0.0 and any(w in self.clean_ref.lower() for w in negation_words):
                weighted_score -= self.weights["negation_penalty"]
                
            final_sentence_score = max(0.0, min(1.0, weighted_score))
            
            if final_sentence_score < 0.82:  # Calibrated boundary
                penalty = round(1.0 - final_sentence_score, 2)
                failed_segments.append({
                    "sentence_index": idx,
                    "text": sentence,
                    "score": round(final_sentence_score, 2),
                    "penalty": penalty
                })
                cumulative_penalty += penalty

        global_score = max(0.0, round(1.0 - (cumulative_penalty / max(1, len(draft_sentences))), 2))
        return {
            "global_score": global_score,
            "status": "PASS" if global_score >= 0.85 else "FAIL",
            "failed_segments": failed_segments,
            "isolated_structures_count": len(structures)
        }

class ProductionTribunalPipeline:
    def __init__(self):
        pass

    def consult_tribunal(self, draft: str, reference: str, audit_report: dict) -> dict:
        tribunal_prompt = f"""
        You are a highly disciplined Three-Agent Tribunal reviewing an LLM generated document for factual hallucinations.
        
        REFERENCE TEXT (GROUND TRUTH):
        \"\"\"{reference}\"\"\"
        
        GENERATED DRAFT TO AUDIT:
        \"\"\"{draft}\"\"\"
        
        MATHEMATICAL ENGINE AUDIT LOG:
        {json.dumps(audit_report, indent=2)}
        
        Analyze the flagged segments from three professional vectors:
        1. Literal Fact-Checker: Is there a strict mismatch of numbers, dates, or proper nouns?
        2. Context Synthesizer: Did the draft invert logic, infer unprovable facts, or warp meaning?
        3. Nuance Guardian: Are these mathematical drops caused by benign vocabulary choices, or true hallucinations?
        
        If 2 out of 3 agents vote to PASS, your global tribunal_verdict is PASS. Otherwise it is FAIL.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": tribunal_prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "tribunal_verdict_schema",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "literal_fact_checker_vote": {"type": "string", "enum": ["PASS", "FAIL"]},
                            "context_synthesizer_vote": {"type": "string", "enum": ["PASS", "FAIL"]},
                            "nuance_guardian_vote": {"type": "string", "enum": ["PASS", "FAIL"]},
                            "tribunal_verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
                            "targeted_feedback_for_rewrite": {"type": "string"}
                        },
                        "required": ["literal_fact_checker_vote", "context_synthesizer_vote", "nuance_guardian_vote", "tribunal_verdict", "targeted_feedback_for_rewrite"],
                        "additionalProperties": False
                    }
                }
            }
        )
        return json.loads(response.choices[0].message.content)

    def execute(self, reference_context: str, user_query: str) -> str:
        # Step 1: Draft initial generation
        print("[Pipeline] Requesting initial generation layout...")
        gen_prompt = f"Using ONLY this context: '{reference_context}', answer the following query: '{user_query}'"
        initial_draft = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": gen_prompt}]
        ).choices[0].message.content
        
        # Step 2: Initialize Math V2 Engine Gate
        print("[Pipeline] Executing HallucinationAuditorV2 Math Matrix Evaluation...")
        auditor = ProductionHallucinationAuditorV2(reference_context=reference_context)
        audit_report = auditor.evaluate(initial_draft)
        
        if audit_report["status"] == "PASS":
            print("[Pipeline] Clean Pass! Output bypasses tribunal to save tokens.")
            return initial_draft
            
        # Step 3: Convene the Tribunal if scores drop
        print(f"[Pipeline] Engine Warning (Global Score: {audit_report['global_score']}). Summoning Tribunal...")
        verdict = self.consult_tribunal(initial_draft, reference_context, audit_report)
        print(f"[Tribunal Verdict Log]: {json.dumps(verdict, indent=2)}")
        
        if verdict["tribunal_verdict"] == "PASS":
            print("[Pipeline] Tribunal overruled math discrepancies as stylistic variance. Output Passed.")
            return initial_draft
            
        # Step 4: Self-Corrective targeted loop
        print("[Pipeline] High Hallucination Risk Certified. Routing to Self-Correction Gate...")
        correction_prompt = f"""
        Fix your previous response. It contained verified factual hallucinations.
        GROUND TRUTH REFERENCE: {reference_context}
        YOUR PREVIOUS DRAFT: {initial_draft}
        TRIBUNAL REWRITE INSTRUCTIONS: {verdict['targeted_feedback_for_rewrite']}
        """
        corrected_output = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": correction_prompt}]
        ).choices[0].message.content
        
        print("[Pipeline] Self-Correction Complete.")
        return corrected_output
