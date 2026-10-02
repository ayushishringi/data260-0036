from functools import lru_cache

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

GEN_MODEL = "google/flan-t5-base"
REFUSAL_TEXT = "I cannot answer this question from the provided documents"


@lru_cache(maxsize=1)
def _load_model():
    tokenizer = AutoTokenizer.from_pretrained(GEN_MODEL)
    model = AutoModelForSeq2SeqLM.from_pretrained(GEN_MODEL)
    model.eval()
    return tokenizer, model


def generate(prompt: str, max_new_tokens: int = 128) -> str:
    tokenizer, model = _load_model()
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    )
    output_ids = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    return tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()


def answer_no_rag(question: str) -> str:
    prompt = f"Answer the question.\nQuestion: {question}\nAnswer:"
    return generate(prompt)


def is_refusal(answer: str) -> bool:
    return REFUSAL_TEXT.lower() in answer.lower()