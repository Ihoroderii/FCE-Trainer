"""Writing section: essay prompts and Part 2 options."""
import random

from app.config import WRITING_MIN_WORDS, WRITING_MAX_WORDS, WRITING_TOTAL_MINUTES

WRITING_ESSAY_PROMPTS = [
    {
        "question": "In your English class you have been talking about different ways of travelling. Now your teacher has asked you to write an essay.",
        "points": [
            "Why people like to visit other countries",
            "Whether it is better to travel alone or with other people",
        ],
        "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view.",
    },
    {
        "question": "In your English class you have been talking about the environment. Now your teacher has asked you to write an essay.",
        "points": [
            "Why many people prefer to use their car instead of public transport",
            "How we can encourage people to use public transport more",
        ],
        "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view.",
    },
    {
        "question": "In your English class you have been talking about where people live. Now your teacher has asked you to write an essay.",
        "points": [
            "Why some people prefer to live in a city",
            "Why some people prefer to live in the countryside",
        ],
        "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view.",
    },
]

WRITING_PART2_OPTIONS = [
    {
        "id": "a",
        "type": "Article",
        "task": "You see this announcement in an international magazine.",
        "prompt": """TRAVEL STORIES WANTED

We want to hear about a journey you have made. It could be a short trip or a longer adventure.

Write an article about your journey. Describe where you went, what you did and why you enjoyed it.

Write your article in 140–190 words.""",
    },
    {
        "id": "b",
        "type": "Letter / email",
        "task": "You have received an email from your English-speaking friend, Sam, who is planning to stay in your country for a month.",
        "prompt": """From: Sam
Subject: Visit

I'm really excited about my trip. Can you tell me what the weather will be like when I'm there? And what should I pack? Also, I'd love to try some typical food – what do you recommend?

Thanks!
Sam

Write your email in 140–190 words. You must use the following words: recommend, weather, pack.""",
    },
    {
        "id": "c",
        "type": "Report",
        "task": "Your teacher has asked you to write a report on facilities for young people in your town or city.",
        "prompt": """The report should mention:
• what sports facilities exist
• what other leisure facilities exist
• how these could be improved

Write your report in 140–190 words.""",
    },
]


def get_writing_context():
    essay = random.choice(WRITING_ESSAY_PROMPTS)
    part2_options = list(WRITING_PART2_OPTIONS)
    random.shuffle(part2_options)
    return {
        "essay_prompt": essay,
        "part2_options": part2_options,
        "word_min": WRITING_MIN_WORDS,
        "word_max": WRITING_MAX_WORDS,
        "total_minutes": WRITING_TOTAL_MINUTES,
    }
