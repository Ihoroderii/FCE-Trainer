"""Prompts used for chat-style answer explanations (why an answer is correct/wrong). Single source of truth for accuracy."""


def get_explanation_prompt_part1(passage: str, gaps_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. You will see a multiple-choice cloze passage and, for each gap, the four options (A–D), the correct answer, and what the student chose.

Use the PASSAGE as context so your explanations refer to the actual sentences (e.g. "In this sentence, X is needed because...").

PASSAGE (gaps are marked as (1)_____, (2)_____, etc.):
---
""" + passage + """

---
For each gap, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct answer is right in this context (grammar/meaning in the sentence above).
2) If the student's answer was wrong, briefly why that option is wrong or doesn't fit here.

Keep each explanation clear and educational. Return ONLY a JSON array of exactly 8 strings (one per gap, in order). No other text.

Gaps:
""" + gaps_lines


def get_explanation_prompt_part2(passage: str, gaps_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. You will see an open-cloze passage and, for each gap, the correct answer and what the student wrote.

Use the PASSAGE as context so your explanations refer to the actual sentences (e.g. "In this sentence, X is needed because...").

PASSAGE (gaps are marked as (1)_____, (2)_____, etc.):
---
""" + passage + """

---
For each gap, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct word is right in this context (grammar/meaning in the sentence above).
2) If the student's answer was wrong or blank, briefly why their word doesn't fit or what the gap requires here.

Keep each explanation clear and educational. Return ONLY a JSON array of exactly 8 strings (one per gap, in order). No other text.

Gaps:
""" + gaps_lines


def get_explanation_prompt_part3(passage: str, gaps_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. For a Part 3 (word formation) task, you will see the passage and for each gap: the stem word in CAPITALS, the correct answer, and what the student wrote.

PASSAGE (for context):
---
""" + passage[:4000] + """

---
For each gap, provide TWO things:

1) **Explanation** (1-2 sentences): Why the correct word fits in this context (grammar/meaning). If the student's answer was wrong or blank, explain briefly why their word doesn't fit or what form was needed.

2) **Word family** for the stem: Give the main forms that exist for this word, in this exact format (use — for forms that don't exist or aren't common):
  noun: ... ; adjective: ... ; adverb: ... ; verb: ...

Return ONLY a valid JSON array of exactly 8 objects. Each object has two keys: "explanation" (string) and "word_family" (string). No other text.

Gaps:
""" + gaps_lines


def get_explanation_prompt_part4(items_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. Below are key word transformation items with the correct answer and what the student wrote.

For each item, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct answer is right (same meaning, uses the key word correctly).
2) If the student's answer was wrong, briefly why it doesn't work or what the mistake is.

Keep each explanation clear and educational. Return ONLY a JSON array of strings (one per item). No other text.

Items:
""" + items_lines


def get_explanation_prompt_part5(text_snippet: str, questions_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. For a Part 5 (reading comprehension, multiple choice) task, you will see the passage and for each question: the question text, correct answer, and student's answer.

PASSAGE (for context):
---
""" + text_snippet + """

---
For each question, write ONE short explanation (1-2 sentences):
1) Why the correct answer is right, referring to specific parts of the text.
2) If the student was wrong, briefly why their choice doesn't fit.

Return ONLY a JSON array of exactly 6 strings (one per question). No other text.

Questions:
""" + questions_lines


def get_explanation_prompt_part6(paragraphs_text: str, gaps_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. For a Part 6 (gapped text) task, you will see the text and for each gap: which sentence correctly fills it and what the student chose.

TEXT (for context):
---
""" + paragraphs_text + """

---
For each gap, write ONE short explanation (1-2 sentences):
1) Why the correct sentence fits (coherence, linking words, pronouns, logical flow).
2) If the student was wrong, briefly why their sentence doesn't fit there.

Return ONLY a JSON array of exactly 6 strings. No other text.

Gaps:
""" + gaps_lines


def get_explanation_prompt_part7(sections_text: str, statements_lines: str) -> str:
    return """You are an FCE (B2 First) English teacher. For a Part 7 (multiple matching) task, you will see the sections and for each statement: the correct section and what the student chose.

Sections: """ + sections_text + """

For each statement, write ONE short explanation (1-2 sentences):
1) Why the correct section matches (what in that section corresponds to the statement).
2) If the student was wrong, briefly why their chosen section doesn't match.

Return ONLY a JSON array of exactly 10 strings. No other text.

Statements:
""" + statements_lines
