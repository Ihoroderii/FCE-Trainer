"""AI prompts for generating FCE Listening exam tasks (Parts 1–4)."""


def get_listening_prompt_part1(topic: str) -> str:
    """Part 1: 8 short unrelated extracts + 8 MCQ (A/B/C)."""
    return f"""You are an FCE (B2 First) Listening exam expert. Generate exactly ONE Part 1 listening task.

Topic/theme for variety: "{topic}" (use it loosely — each extract is independent).

Part 1 consists of 8 SHORT unrelated extracts. Each extract is a monologue or dialogue (2–4 sentences, ~30–50 words). Each has ONE multiple-choice question with 3 options (A, B, C).

Requirements:
- 8 extracts with diverse everyday situations (phone calls, announcements, conversations, radio excerpts, etc.)
- Each extract: 2–4 natural-sounding sentences at B2 level. Include realistic speech patterns.
- Each question tests comprehension of main idea, speaker attitude/opinion, or specific information.
- The correct answer should NOT use the exact same words as the extract — test understanding, not word matching.
- Distractors should be plausible but clearly wrong.

For each extract, assign a speaker voice:
- "male1" for male speaker
- "female1" for female speaker
- "male2" for second male (if dialogue)
- "female2" for second female (if dialogue)
- "narrator" for exam-style intro (e.g. "Extract one. You hear a woman talking about...")

Return ONLY a valid JSON object:
{{
  "extracts": [
    {{
      "intro": "You hear a man talking on the phone about a holiday.",
      "script": [
        {{"voice": "male1", "text": "The actual spoken text of the extract..."}},
        {{"voice": "female1", "text": "Another speaker's line if dialogue..."}}
      ],
      "question": "What is the man's main concern?",
      "options": ["The cost of the trip", "The weather forecast", "The hotel location"],
      "correct": 0
    }}
  ]
}}

- "extracts": array of exactly 8 objects
- Each "script": array of speech segments with "voice" and "text"
- "correct": integer 0, 1, or 2 (index of correct option)

No other text or markdown."""


def get_listening_prompt_part2(topic: str) -> str:
    """Part 2: monologue + 10 sentence completion gaps."""
    return f"""You are an FCE (B2 First) Listening exam expert. Generate exactly ONE Part 2 listening task.

The monologue MUST be about: "{topic}".

Part 2 is a monologue (talk, lecture, radio broadcast, etc.) lasting about 3 minutes (~350–450 words). The candidate completes 10 sentences with information heard in the recording. Each answer is 1–3 words.

Requirements:
- A natural monologue by ONE speaker at B2 level, ~350–450 words.
- The monologue should be informative and well-structured (introduction, body, conclusion).
- 10 gapped sentences that follow the order of the monologue.
- Each gap answer is 1–3 words, directly stated or closely paraphrased in the monologue.
- Sentences should test factual comprehension (names, numbers, reasons, descriptions).

Return ONLY a valid JSON object:
{{
  "title": "A talk about urban gardening",
  "script": [
    {{"voice": "narrator", "text": "You will hear a woman giving a talk about urban gardening. For questions 1 to 10, complete the sentences with a word or short phrase."}},
    {{"voice": "female1", "text": "The full monologue text... Several paragraphs of natural speech..."}}
  ],
  "sentences": [
    {{"text": "The speaker first became interested in gardening when she moved to a ____.", "answer": "new city"}},
    {{"text": "She describes the soil in urban areas as often being ____.", "answer": "contaminated"}}
  ]
}}

- "script": array of voice segments (narrator intro + speaker monologue, can split into 2–3 segments)
- "sentences": array of exactly 10 objects with "text" (gapped sentence, use ____ for the gap) and "answer" (1–3 words)

No other text or markdown."""


def get_listening_prompt_part3(topic: str) -> str:
    """Part 3: 5 short monologues, match speakers to statements."""
    return f"""You are an FCE (B2 First) Listening exam expert. Generate exactly ONE Part 3 listening task.

All 5 speakers talk about the general theme: "{topic}".

Part 3 has 5 short monologues (~30–50 words each) by different speakers on a THEME. The candidate matches each speaker (1–5) to one of 8 statements (A–H). Three statements are distractors (not matched).

Requirements:
- 5 monologues, each by a different speaker, each ~30–50 words at B2 level.
- Each monologue expresses a personal opinion, experience, or attitude related to the theme.
- 8 statements (A–H): 5 match one speaker each, 3 are distractors.
- Statements should paraphrase what speakers say — do NOT copy exact phrases.
- Each speaker must match exactly one statement. No speaker matches two.

Return ONLY a valid JSON object:
{{
  "theme": "{topic}",
  "intro": "You will hear five people talking about {topic}.",
  "speakers": [
    {{
      "voice": "female1",
      "text": "Speaker 1's monologue text..."
    }},
    {{
      "voice": "male1",
      "text": "Speaker 2's monologue text..."
    }},
    {{
      "voice": "female2",
      "text": "Speaker 3's monologue text..."
    }},
    {{
      "voice": "male2",
      "text": "Speaker 4's monologue text..."
    }},
    {{
      "voice": "male1",
      "text": "Speaker 5's monologue text..."
    }}
  ],
  "statements": [
    "A: found the experience unexpectedly rewarding",
    "B: regrets not starting sooner",
    ...
  ],
  "answers": [3, 0, 5, 1, 7]
}}

- "speakers": array of exactly 5 objects with "voice" and "text"
- "statements": array of exactly 8 strings (A through H)
- "answers": array of exactly 5 integers — answers[i] is the index (0–7) into "statements" for speaker i+1

No other text or markdown."""


def get_listening_prompt_part4(topic: str) -> str:
    """Part 4: interview/discussion + 7 MCQ (A/B/C)."""
    return f"""You are an FCE (B2 First) Listening exam expert. Generate exactly ONE Part 4 listening task.

The interview/discussion MUST be about: "{topic}".

Part 4 is an interview or discussion between 2–3 speakers lasting about 3–4 minutes (~400–500 words). The candidate answers 7 multiple-choice questions (A, B, C).

Requirements:
- A natural conversation/interview at B2 level, ~400–500 words total.
- 2–3 speakers with distinct viewpoints and natural turn-taking.
- Include an interviewer/host plus 1–2 guests, OR a conversational discussion.
- 7 MCQ questions testing opinions, attitudes, agreement/disagreement, and specific information.
- Questions follow the order of the conversation.
- Distractors should be plausible but clearly not what the speakers actually express.

Return ONLY a valid JSON object:
{{
  "title": "An interview about sustainable fashion",
  "script": [
    {{"voice": "narrator", "text": "You will hear an interview about sustainable fashion. For questions 1 to 7, choose the best answer A, B or C."}},
    {{"voice": "female1", "text": "Welcome to our show. Today we're talking about..."}},
    {{"voice": "male1", "text": "Thanks for having me. I think..."}},
    {{"voice": "female1", "text": "That's interesting. But what about..."}},
    {{"voice": "male1", "text": "Well, in my experience..."}}
  ],
  "questions": [
    {{
      "text": "What does the guest think about fast fashion?",
      "options": ["It should be banned completely.", "It needs significant reform.", "It has some positive aspects."],
      "correct": 1
    }}
  ]
}}

- "script": array of voice segments (narrator intro + alternating speakers). Split the conversation into 8–15 segments for natural turn-taking.
- "questions": array of exactly 7 objects with "text", "options" (exactly 3), "correct" (0, 1, or 2)

No other text or markdown."""


# ── Topic lists ──────────────────────────────────────────────────────────────

LISTENING_PART1_TOPICS = [
    "travel and holidays", "work and careers", "food and cooking",
    "health and fitness", "technology and gadgets", "education and learning",
    "entertainment and media", "shopping and money", "sports and hobbies",
    "weather and seasons", "transport and commuting", "friends and relationships",
    "housing and home life", "fashion and appearance", "environment and nature",
    "music and concerts", "books and reading", "films and cinema",
    "art and creativity", "volunteering and charity", "animals and pets",
    "celebrations and events", "city life vs country life", "childhood memories",
    "plans and ambitions", "cultural differences", "social media",
    "museums and exhibitions", "outdoor activities", "daily routines",
]

LISTENING_PART2_TOPICS = [
    "the history of chocolate", "life as a marine biologist",
    "how airports handle luggage", "the psychology of colour",
    "setting up a community garden", "training for a marathon",
    "the science of sleep", "working in Antarctica",
    "how podcasts are produced", "traditional crafts in modern times",
    "the future of electric cars", "organising a music festival",
    "life as a lighthouse keeper", "how bridges are designed",
    "the story of street art", "becoming a professional chef",
    "the impact of tourism on small villages", "how memory works",
    "the art of beekeeping", "building sustainable homes",
    "the history of board games", "working as a firefighter",
    "underwater archaeology", "how weather forecasts are made",
    "the world of competitive puzzle-solving", "life on a houseboat",
    "the business of second-hand clothing", "how guide dogs are trained",
    "the science behind optical illusions", "running a bookshop",
]

LISTENING_PART3_TOPICS = [
    "learning a musical instrument", "experiences of moving to a new city",
    "memorable travel experiences", "learning to cook",
    "benefits of outdoor exercise", "changing careers",
    "experiences with public speaking", "dealing with difficult neighbours",
    "memorable school teachers", "experiences of working from home",
    "learning a new language", "taking up a new hobby later in life",
    "experiences of volunteering", "what makes a good friend",
    "memorable birthday celebrations", "experiences of living abroad",
    "tips for saving money", "experiences of extreme weather",
    "favourite childhood games", "opinions on social media",
    "experiences with online shopping", "advice for new university students",
    "dealing with stress", "experiences of team sports",
    "opinions on modern architecture", "experiences of learning to drive",
    "favourite places to relax", "opinions on reality TV shows",
    "experiences of job interviews", "advice for staying healthy",
]

LISTENING_PART4_TOPICS = [
    "the future of education", "sustainable living in cities",
    "the impact of artificial intelligence on jobs",
    "the benefits and drawbacks of remote work",
    "the role of arts in education", "youth unemployment solutions",
    "the ethics of animal testing", "space exploration priorities",
    "social media's effect on mental health", "preserving endangered languages",
    "the gig economy", "the importance of sleep for students",
    "fast fashion and the environment", "genetic engineering in agriculture",
    "the future of public transport", "digital privacy and data protection",
    "the value of gap years", "renewable energy adoption",
    "the impact of tourism on heritage sites", "screen time and children",
    "the future of libraries", "microplastics in the oceans",
    "the rise of plant-based diets", "automation in healthcare",
    "the importance of financial literacy", "urban green spaces",
    "the psychology of decision-making", "online learning versus classroom learning",
    "the future of newspapers", "cultural identity in a globalised world",
]
