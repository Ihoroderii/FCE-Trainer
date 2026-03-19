"""Prompts used for generating new FCE tasks (Part 1–7). Single source of truth for accuracy."""


def get_task_prompt_part1(topic: str, level: str = "b2") -> str:
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    if level == "b2plus":
        level_instruction = (
            "The text must be at B2+ level: slightly more complex vocabulary and grammar "
            "(e.g. less common collocations, more formal linkers, or subtle meaning differences between options). "
            "Standard FCE Part 1 length (4-6 sentences, 8 gaps)."
        )
    else:
        level_instruction = (
            "The text must be at B2 level: clear vocabulary and grammar appropriate for FCE. "
            "Standard Part 1 length (4-6 sentences, 8 gaps)."
        )
    return f"""You are an FCE (B2 First) English exam expert. Generate exactly ONE "multiple-choice cloze" task.

The text MUST be clearly about this topic: "{topic}". Write a short, coherent paragraph that is obviously on this theme (not work or offices unless the topic says so). Use a specific angle or situation so the text feels fresh and varied.

{level_instruction}

The task must have:
- text: A short paragraph with exactly 8 gaps. Each gap must be written as (1)_____, (2)_____, ... (8)_____ in order. The gaps should test vocabulary/grammar in context.
- gaps: An array of exactly 8 objects. Each object has: "options" (array of exactly 4 words/phrases that could fit the gap), "correct" (integer 0, 1, 2, or 3 - the index of the correct option in "options").

Return ONLY a valid JSON object with keys "text" and "gaps". No other text. Example shape:
{{"text": "Some text with (1)_____ and (2)_____ ...", "gaps": [{{"options": ["a","b","c","d"], "correct": 0}}, ...]}}"""


def get_task_prompt_part2(topic: str, level: str = "b2") -> str:
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    if level == "b2plus":
        level_instruction = (
            "- The text must be at B2+ level: slightly more complex grammar and vocabulary than standard B2. "
            "Use a mix of sentence structures (e.g. participle clauses, inversion, or more formal linkers). "
            "Include at least one or two gaps that could require phrasal verbs, complex prepositions, or linking words "
            "(e.g. however, although, despite, whereas). Length about 180-220 words."
        )
    else:
        level_instruction = (
            "- A short text (about 150-200 words) at B2 level. Standard FCE open-cloze difficulty."
        )
    return f"""You are an FCE (B2 First) Use of English exam expert. Generate exactly ONE Part 2 (Open cloze) task.

The text must be about this topic: {topic}. Use a different angle or situation (e.g. a personal story, a news-style piece, advice, or a description). Do NOT write about working from home or remote work unless the chosen topic is "work and careers" and you pick that angle.

Part 2 consists of:
{level_instruction}
- The text must contain exactly 8 gaps marked (1)_____, (2)_____, (3)_____, (4)_____, (5)_____, (6)_____, (7)_____, (8)_____ in order. Each gap needs ONE word (articles, prepositions, auxiliaries, pronouns, conjunctions, phrasal verb particles, linkers, etc.).
- The 8 correct answers (one word per gap).

Return ONLY a valid JSON object with these exact keys:
- "text": the full text with the exact placeholders (1)_____, (2)_____, ... (8)_____ where the gaps are. No other placeholder format.
- "answers": an array of exactly 8 strings: the correct word for gap 1, then gap 2, ... gap 8. Use lowercase unless the word must be capitalised (e.g. start of sentence).

No other text or markdown."""


def get_task_prompt_part3(topic: str, level: str = "b2") -> str:
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    if level == "b2plus":
        level_instruction = (
            "Use B2+ vocabulary and grammar: slightly more complex word formation "
            "(e.g. less common suffixes, negative prefixes, or abstract nouns)."
        )
    else:
        level_instruction = (
            "Use B2-level vocabulary and grammar. Test common suffixes (-tion, -ness, -ly, -ful, -less, -able), "
            "prefixes (un-, in-, im-), and word class changes."
        )
    return f"""You are an FCE (B2 First) Use of English exam expert. Generate exactly ONE Part 3 (Word formation) task.

The text MUST be clearly about this topic: "{topic}". Write one continuous passage (150-200 words) that is obviously on this theme.

{level_instruction}

Requirements:
- One continuous text (150-200 words) with exactly 8 gaps.
- Each gap must be written as (1)_____, (2)_____, (3)_____, (4)_____, (5)_____, (6)_____, (7)_____, (8)_____ in order.
- At the end of the sentence or clause that contains each gap, put the STEM WORD in CAPITAL LETTERS (e.g. "...has been delayed. COMPLETE" or "...looked at him. SUSPECT"). So the reader sees the stem word in capitals after each gap.
- The stem word is the base form; the student must change it (prefix, suffix, plural, etc.) to fit the gap.
- IMPORTANT: In real FCE Part 3, the correct answer is almost always a DIFFERENT form from the stem (different word class or with prefix/suffix). Only very rarely (about 1 in 20 gaps) may the answer be the stem word unchanged (e.g. DANGER → danger). So for this task: at most ONE gap in the entire 8-gap passage may have the correct answer identical to the stem word (no transformation). All other gaps MUST require a clear word formation change (e.g. COMPLETE → completion, SUSPECT → suspiciously). Prefer having all 8 gaps require a transformation.

Return ONLY a valid JSON object with these exact keys:
- "text": the full passage (150-200 words) with (1)_____ through (8)_____ and each stem word in CAPITALS at the end of its sentence/clause. Example fragment: "The (1)_____ of the centre has been delayed. COMPLETE She looked at him (2)_____ when he told the joke. SUSPECT"
- "stems": array of exactly 8 strings — the stem words in order (e.g. ["COMPLETE", "SUSPECT", ...])
- "answers": array of exactly 8 strings — the correct formed word for each gap, lowercase unless capitalised (e.g. ["completion", "suspiciously", ...])

No other text or markdown."""


def get_task_prompt_part4(count: int, level: str = "b2plus", recent_avoid: str = "") -> str:
    level_instruction = (
        "Level: B2+ (slightly more difficult than B2). Use vocabulary and grammar that is upper-intermediate to advanced: "
        "less common collocations, more complex structures, idiomatic expressions. Avoid items that are too easy (A2/B1)."
        if (level or "").strip().lower() == "b2plus"
        else "Level: B2 (Cambridge B2 First). Use vocabulary and grammar appropriate for upper-intermediate learners. "
        "Standard FCE difficulty. Avoid items that are too easy (A2/B1) or too hard (C1)."
    )
    return f"""You are an FCE (B2 First) English exam expert. Generate exactly {count} "key word transformation" items.

{level_instruction}

Each item: sentence1 (first sentence), keyword (ONE word in CAPITALS that MUST appear in the answer), sentence2 (second sentence with the SAME meaning, with exactly one gap "_____"), answer (EXACTLY 3 to 5 words to fill the gap—never 1 or 2 words; the answer MUST contain the key word. E.g. for CHANCE use "chance of winning" or "no chance of succeeding", not just "chance". The gap must require a phrase of 3-5 words.), grammar_topic (ONE short label for the main grammar/construction tested, e.g. "passive voice", "third conditional", "reported speech", "comparatives", "past perfect", "modal verbs", "causative have", "wish/if only", "phrasal verbs", "linking words").

CRITICAL: The second sentence (sentence2) must be a REAL REPHRASING: different wording, different grammar or structure where possible. It must NOT be the first sentence with one phrase simply replaced by "_____".

Use a DIFFERENT grammar_topic for each item—vary the grammar (passive, conditionals, reported speech, modals, etc.). Do not repeat the same grammar focus in the set.
{recent_avoid}
Return ONLY a valid JSON array of objects with keys: sentence1, keyword, sentence2, answer, grammar_topic. No other text."""


def get_task_prompt_part5(topic: str, level: str = "b2") -> str:
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    if level == "b2plus":
        level_instruction = (
            "1. A single continuous text. Length: between 550 and 650 words. B2+ level: use more sophisticated "
            "vocabulary, complex sentence structures (e.g. participle clauses, inversion, subjunctive), "
            "nuanced arguments, and subtle tone shifts. The text should challenge advanced upper-intermediate readers."
        )
    else:
        level_instruction = (
            "1. A single continuous text. Length: between 550 and 650 words. Upper-Intermediate (B2) level. "
            "The text should test understanding of the writer's opinion, attitude, purpose, tone, and implied meaning—not just surface facts."
        )
    return f"""You are an FCE (B2 First) Reading and Use of English exam expert. Generate exactly ONE Part 5 task.

The text MUST be clearly about this topic: "{topic}". Write a single continuous text (e.g. magazine article, report, or extract from a modern novel) that is obviously on this theme. Use a specific angle or situation so the text feels fresh and varied.

Part 5 consists of:
{level_instruction}
2. Exactly 6 multiple-choice questions. Each question has four options (A, B, C, D). Questions must follow the chronological order of the text: question 1 relates to the beginning, question 6 may relate to the end or the text as a whole. Each correct answer is worth 2 marks.

QUESTION QUALITY REQUIREMENTS:
- Mix question types: include at least one of each: (a) detail/fact comprehension, (b) writer's opinion/attitude, (c) implied meaning/inference, (d) purpose of a phrase or paragraph.
- Distractors must be plausible: each wrong option should seem reasonable at first glance but be clearly wrong when the relevant passage is read carefully. Avoid obviously absurd options.
- Vary the position of the correct answer: do NOT always put it in the same slot. Distribute correct answers across A, B, C, D roughly evenly.
- Questions should use paraphrase, not copy text verbatim.

Return ONLY a valid JSON object with these exact keys:
- "title": a short title for the text (e.g. "The benefits of learning music")
- "text": the full text. Use <p>...</p> for paragraphs. No other HTML. The text must be 550-650 words.
- "questions": an array of exactly 6 objects. Each object has: "q" (the question text), "options" (array of exactly 4 strings, in order A then B then C then D), "correct" (integer 0, 1, 2, or 3—the index of the correct option).

Example shape:
{{"title": "...", "text": "<p>...</p><p>...</p>", "questions": [{{"q": "...", "options": ["A text", "B text", "C text", "D text"], "correct": 1}}, ...]}}

No other text or markdown."""


def get_task_prompt_part6(topic: str, level: str = "b2") -> str:
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    if level == "b2plus":
        level_instruction = (
            "- A single continuous text of 500-600 words (B2+ level): use more sophisticated vocabulary, "
            "complex sentence structures, and nuanced argumentation. The removed sentences should require "
            "careful analysis of cohesion devices, reference words, and logical flow to place correctly. "
            "The text must contain exactly 6 numbered gaps where a sentence has been removed. "
            "Use the exact placeholders GAP1, GAP2, GAP3, GAP4, GAP5, GAP6 in order where each gap appears."
        )
    else:
        level_instruction = (
            "- A single continuous text of 500-600 words (B2 level). The text must contain exactly 6 numbered gaps "
            "where a sentence has been removed. Use the exact placeholders GAP1, GAP2, GAP3, GAP4, GAP5, GAP6 "
            "in order where each gap appears."
        )
    return f"""You are an FCE (B2 First) Reading and Use of English exam expert. Generate exactly ONE Part 6 (gapped text) task.

The text MUST be about this topic: "{topic}". Use a specific angle to make the text engaging and varied.

Part 6 consists of:
{level_instruction}
- 7 sentences labeled A-G. Exactly 6 of these fit into the gaps (one per gap); one sentence is a distractor.

Return ONLY a valid JSON object with these exact keys:
- "paragraphs": an array of strings. Each string is either a paragraph or exactly "GAP1", "GAP2", "GAP3", "GAP4", "GAP5", "GAP6" where that gap appears.
- "sentences": an array of exactly 7 strings: the sentence for A, then B, then C, D, E, F, G. Give only the sentence text (no "A)" prefix).
- "answers": an array of exactly 6 integers (0-6). answers[i] is the index into "sentences" (0=A, 1=B, ... 6=G) that correctly fills gap i+1.

No other text or markdown."""


def get_task_prompt_part7(topic: str) -> str:
    return f"""You are an FCE (B2 First) Reading exam expert. Generate exactly ONE Part 7 (Multiple matching) task.

The text MUST be about this topic: "{topic}". Use a specific angle to make the text engaging and varied.

Part 7 consists of:
- Either ONE long text divided into 4-6 sections (labeled A, B, C, D, and optionally E, F) OR 4-5 short separate texts. Total length 600-700 words (B2 level).
- 10 statements that the candidate must match to the correct section. Each correct match = 1 mark.

QUALITY REQUIREMENTS:
- Use paraphrasing throughout: do NOT copy phrases from the text into statements. Rephrase ideas.
- Each section should be matched by at least one question. Distribute matches across sections.
- Vary difficulty: include some straightforward matches and some that require careful inference.
- Each statement must unambiguously match exactly one section.

Return ONLY a valid JSON object with these exact keys:
- "sections": an array of 4 to 6 objects. Each object has "id" (letter "A", "B", "C", "D", "E", or "F"), "title" (short section title), "text" (the section body text). The combined word count of all section "text" must be between 600 and 700 words.
- "questions": an array of exactly 10 objects. Each has "text" (the statement to match, one sentence) and "correct" (the section id, e.g. "A", "B").

No other text or markdown."""


def get_task_prompt_get_phrases(level: str = "b2") -> str:
    """Generate one cloze text with 8 gaps; each gap = correct collocation with GET (e.g. get over, get rid of)."""
    return """You are an English (B2) exam expert. Generate exactly ONE "get phrases" practice task.

The task is a short continuous text (150–200 words) with exactly 8 gaps. Each gap must be filled with a correct collocation or phrasal verb using GET (e.g. get over, get rid of, get along with, get through, get away with, get on with, get round to, get out of, get by, get at, get across, get back to, get down to, get on, get off, get together, get ahead, get behind, get in, get into). Use a variety of common "get" phrases appropriate for B2 level.

Requirements:
- One continuous text (150–200 words) with exactly 8 gaps.
- Each gap must be written as (1)_____, (2)_____, (3)_____, (4)_____, (5)_____, (6)_____, (7)_____, (8)_____ in order.
- Each answer is the full phrase with "get" (e.g. "get over", "get rid of", "get along with"). Use lowercase. The student will type the missing phrase in each gap.

Return ONLY a valid JSON object with these exact keys:
- "text": the full passage with (1)_____ through (8)_____ where the gaps are.
- "answers": an array of exactly 8 strings — the correct "get" phrase for each gap (e.g. ["get over", "get rid of", "get along with", "get through", "get away with", "get on with", "get round to", "get out of"]).

No other text or markdown."""
