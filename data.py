# FCE Exam Trainer - Paper structure (Parts 1–7)
# Part 4 Use of English (key word transformation) comes from server (database + OpenAI)

# --- Part 1: Multiple-choice cloze — 8 gaps, A/B/C/D, 1 mark each ---
PART_1_DATA = [
    {
        "text": "The success of the new shopping centre has surprised many people. When it first opened, there were fears that it would (1)_____ empty. However, the (2)_____ of the centre has been enormous. Shoppers are (3)_____ by the variety of goods on offer and the number of (4)_____ has increased every month. The centre has become a (5)_____ part of the town and has (6)_____ many new jobs. Local people say it has (7)_____ their lives and they cannot (8)_____ how they managed without it.",
        "gaps": [
            {"options": ["stay", "remain", "keep", "hold"], "correct": 1},
            {"options": ["popularity", "fame", "reputation", "approval"], "correct": 0},
            {"options": ["impressed", "affected", "interested", "attracted"], "correct": 0},
            {"options": ["visitors", "attendees", "customers", "guests"], "correct": 0},
            {"options": ["necessary", "essential", "important", "vital"], "correct": 3},
            {"options": ["created", "made", "given", "put"], "correct": 0},
            {"options": ["changed", "improved", "developed", "grown"], "correct": 1},
            {"options": ["imagine", "suppose", "wonder", "consider"], "correct": 0},
        ],
    },
    {
        "text": "My brother has always been (1)_____ on music. He started playing the piano when he was six and it soon became (2)_____ that he had a special talent. By the time he was a teenager, he had already given several (3)_____ and had won a number of competitions. He decided to (4)_____ a career in music and went to study at a famous (5)_____ in the capital. He now works as a concert pianist and his (6)_____ has taken him all over the world. He says he cannot (7)_____ a life without music and practises for several hours every (8)_____.",
        "gaps": [
            {"options": ["keen", "eager", "fond", "interested"], "correct": 0},
            {"options": ["sure", "clear", "obvious", "evident"], "correct": 1},
            {"options": ["performances", "shows", "plays", "acts"], "correct": 0},
            {"options": ["follow", "pursue", "chase", "run"], "correct": 1},
            {"options": ["college", "academy", "school", "institute"], "correct": 1},
            {"options": ["job", "work", "profession", "career"], "correct": 3},
            {"options": ["think", "see", "imagine", "believe"], "correct": 2},
            {"options": ["day", "time", "moment", "hour"], "correct": 0},
        ],
    },
]

# --- Part 2: Open cloze — 8 gaps, one word each, 1 mark each ---
PART_2_DATA = [
    {
        "text": "I have always been interested (1)_____ how machines work. When I was a child, I used (2)_____ take my toys apart to see what was inside. My parents were not very pleased (3)_____ me when I could not put them back together again. I studied engineering at university and now I work (4)_____ a large company that designs car engines. I have been there (5)_____ five years and I still find my job fascinating. (6)_____ I could change one thing, it would be the amount of paperwork I have to do. Last year I was asked (7)_____ give a presentation at a conference, which was a great experience. I am sure that my interest in machines will last (8)_____ the rest of my life.",
        "answers": ["in", "to", "with", "for", "for", "If", "to", "for"],
    },
    {
        "text": "The weather in this part of the country can change very quickly. (1)_____ the morning it may be sunny, but by lunchtime it could be raining heavily. Many people (2)_____ live here always carry an umbrella, (3)_____ they know they might need it at any moment. The best time to visit is probably (4)_____ spring or early summer, when the days are longer and the temperature is pleasant. (5)_____ you are planning to go walking in the hills, make sure you take warm clothing. It can get cold (6)_____ high up, even when it is warm in the valleys. The local tourist office will give you (7)_____ information about the best routes to take. I have been living here (8)_____ ten years and I still find new places to explore.",
        "answers": ["In", "who", "as", "in", "If", "when", "you", "for"],
    },
]

# --- Part 3: Word formation — 8 gaps, change given word, 1 mark each ---
PART_3_DATA = [
    [
        {"sentence": "The _____ of the new shopping centre has been delayed. COMPLETE", "key": "COMPLETE", "answer": "completion", "gapNum": 1},
        {"sentence": "She looked at him _____ when he told the joke. SUSPECT", "key": "SUSPECT", "answer": "suspiciously", "gapNum": 2},
        {"sentence": "It was _____ of you to leave the door unlocked. RESPONSIBLE", "key": "RESPONSIBLE", "answer": "irresponsible", "gapNum": 3},
        {"sentence": "We need to make a _____ soon. DECIDE", "key": "DECIDE", "answer": "decision", "gapNum": 4},
        {"sentence": "The _____ of the product has improved. RELIABLE", "key": "RELIABLE", "answer": "reliability", "gapNum": 5},
        {"sentence": "She accepted the criticism _____. GRACIOUS", "key": "GRACIOUS", "answer": "graciously", "gapNum": 6},
        {"sentence": "We need to reduce our _____ on fossil fuels. DEPEND", "key": "DEPEND", "answer": "dependence", "gapNum": 7},
        {"sentence": "The _____ of the building took three years. CONSTRUCT", "key": "CONSTRUCT", "answer": "construction", "gapNum": 8},
    ],
    [
        {"sentence": "He's a very _____ person — he never gets angry. PATIENCE", "key": "PATIENCE", "answer": "patient", "gapNum": 1},
        {"sentence": "There was a _____ change in the weather. SUDDEN", "key": "SUDDEN", "answer": "sudden", "gapNum": 2},
        {"sentence": "I find it _____ to believe he said that. POSSIBLE", "key": "POSSIBLE", "answer": "impossible", "gapNum": 3},
        {"sentence": "She spoke so _____ that I couldn't hear her. QUIET", "key": "QUIET", "answer": "quietly", "gapNum": 4},
        {"sentence": "We had an _____ discussion about the project. PRODUCE", "key": "PRODUCE", "answer": "productive", "gapNum": 5},
        {"sentence": "His _____ to help was very kind. WILLING", "key": "WILLING", "answer": "willingness", "gapNum": 6},
        {"sentence": "The situation is becoming increasingly _____. DANGER", "key": "DANGER", "answer": "dangerous", "gapNum": 7},
        {"sentence": "The _____ of the product has improved. RELIABLE", "key": "RELIABLE", "answer": "reliability", "gapNum": 8},
    ],
]

# Backward compatibility: WORD_TRANSFORMATION_DATA = PART_3_DATA (first set only as list of sets)
WORD_TRANSFORMATION_DATA = [
    [
        {"sentence": "The _____ of the new shopping centre has been delayed. COMPLETE", "key": "COMPLETE", "answer": "completion", "gapNum": 1},
        {"sentence": "She looked at him _____ when he told the joke. SUSPECT", "key": "SUSPECT", "answer": "suspiciously", "gapNum": 2},
        {"sentence": "It was _____ of you to leave the door unlocked. RESPONSIBLE", "key": "RESPONSIBLE", "answer": "irresponsible", "gapNum": 3},
        {"sentence": "We need to make a _____ soon. DECIDE", "key": "DECIDE", "answer": "decision", "gapNum": 4},
        {"sentence": "The _____ of the product has improved. RELIABLE", "key": "RELIABLE", "answer": "reliability", "gapNum": 5},
    ],
    [
        {"sentence": "He's a very _____ person — he never gets angry. PATIENCE", "key": "PATIENCE", "answer": "patient", "gapNum": 1},
        {"sentence": "There was a _____ change in the weather. SUDDEN", "key": "SUDDEN", "answer": "sudden", "gapNum": 2},
        {"sentence": "I find it _____ to believe he said that. POSSIBLE", "key": "POSSIBLE", "answer": "impossible", "gapNum": 3},
        {"sentence": "She spoke so _____ that I couldn't hear her. QUIET", "key": "QUIET", "answer": "quietly", "gapNum": 4},
        {"sentence": "The _____ of the building took three years. CONSTRUCT", "key": "CONSTRUCT", "answer": "construction", "gapNum": 5},
    ],
    [
        {"sentence": "We had an _____ discussion about the project. PRODUCE", "key": "PRODUCE", "answer": "productive", "gapNum": 1},
        {"sentence": "His _____ to help was very kind. WILLING", "key": "WILLING", "answer": "willingness", "gapNum": 2},
        {"sentence": "The situation is becoming increasingly _____. DANGER", "key": "DANGER", "answer": "dangerous", "gapNum": 3},
        {"sentence": "She accepted the criticism _____. GRACIOUS", "key": "GRACIOUS", "answer": "graciously", "gapNum": 4},
        {"sentence": "We need to reduce our _____ on fossil fuels. DEPEND", "key": "DEPEND", "answer": "dependence", "gapNum": 5},
    ],
]
# --- Part 5: Multiple choice — long text, 6 questions, 2 marks each ---
PART_5_DATA = [
    {
        "title": "The benefits of learning a musical instrument",
        "text": """<p>Learning to play a musical instrument is one of the most rewarding activities a person can take up. Whether you choose the piano, guitar, or violin, the benefits extend far beyond simply being able to play music.</p>
<p>Research has shown that learning an instrument improves memory and concentration. When you read music and coordinate your hands, you are exercising your brain in ways that few other activities can match. Many students who learn music also perform better in subjects like maths and languages.</p>
<p>Playing an instrument can also reduce stress. Focusing on the music allows you to forget your worries for a while. Moreover, joining a band or orchestra helps you meet people and build lasting friendships. Even practising alone can give you a sense of achievement when you finally master a difficult piece.</p>
<p>It is never too late to start. While children often learn quickly, adults can make excellent progress too, as long as they practise regularly. The key is to choose an instrument you enjoy and to set aside a little time each day.</p>""",
        "questions": [
            {"q": "What is the main idea of the first paragraph?", "options": ["You should choose the piano.", "Learning an instrument has wide benefits.", "Playing music is easy.", "Instruments are expensive."], "correct": 1},
            {"q": "According to the text, learning an instrument helps with:", "options": ["only playing music", "memory and concentration", "sports performance", "cooking skills"], "correct": 1},
            {"q": "The text says that playing music can help you:", "options": ["earn more money", "forget your worries", "travel more", "work longer hours"], "correct": 1},
            {"q": "What does the text say about adults learning an instrument?", "options": ["They cannot learn as well as children.", "They need to practise regularly.", "They should only learn the piano.", "They find it too stressful."], "correct": 1},
            {"q": "What does 'set aside' mean in this context?", "options": ["save money", "find or reserve time", "put something down", "forget something"], "correct": 1},
            {"q": "The author's purpose is to:", "options": ["advertise music lessons", "encourage people to try learning an instrument", "compare different instruments", "explain how to join a band."], "correct": 1},
        ],
    },
    {
        "title": "Why we forget names",
        "text": """<p>Forgetting someone's name moments after being introduced is embarrassing, but it is extremely common. Scientists have studied why names are so difficult to remember compared to other information.</p>
<p>One reason is that names are arbitrary. If you meet someone called Mr Baker, his name does not tell you what he looks like or what he does. Unlike words that describe something, names are just labels with no built-in meaning. This makes them harder for the brain to store and retrieve.</p>
<p>Another factor is that we often do not pay full attention when we are introduced. We might be thinking about what we are going to say next, or worrying about making a good impression. When we are not fully focused, the name does not get properly encoded in our memory.</p>
<p>There are simple tricks that can help. Repeating the name when you hear it, and using it once or twice in the first few minutes of conversation, can make a big difference. Linking the name to a visual image or a famous person with the same name can also improve recall.</p>""",
        "questions": [
            {"q": "According to the text, why are names hard to remember?", "options": ["They are too long.", "They often have no meaning.", "People say them too quietly.", "We hear too many at once."], "correct": 1},
            {"q": "The text suggests we sometimes forget names because:", "options": ["we are not paying full attention", "the room is too noisy", "we have bad eyesight", "names are too short"], "correct": 0},
            {"q": "Which tip does the text give for remembering names?", "options": ["Write them down immediately.", "Repeat the name when you hear it.", "Only meet people one at a time.", "Avoid using the person's name."], "correct": 1},
            {"q": "What does 'arbitrary' mean here?", "options": ["difficult", "random or not descriptive", "important", "long"], "correct": 1},
            {"q": "The second paragraph explains:", "options": ["how to remember names", "why names lack meaning that helps memory", "who Mr Baker is", "what the brain stores."], "correct": 1},
            {"q": "The author's tone is:", "options": ["critical", "reassuring and practical", "humorous", "scientific only."], "correct": 1},
        ],
    },
]

# --- Part 6: Gapped text — 6 gaps, 7 sentences (A–G), one extra, 2 marks each ---
PART_6_DATA = [
    {
        "paragraphs": [
            "Tourism has grown enormously in the last fifty years. For many countries it is now the most important source of income.",
            "GAP1",
            "They need hotels, restaurants, and transport. They want to visit famous sights and buy souvenirs.",
            "GAP2",
            "This can lead to overcrowding and damage to historic sites. In some places, local people find it difficult to afford to live because prices have risen so much.",
            "GAP3",
            "Governments and local councils are trying to find a balance. They want to attract visitors but also protect the environment and the interests of residents.",
            "GAP4",
            "Some places have introduced limits on the number of visitors. Others charge higher fees at peak times.",
            "GAP5",
            "Tourists themselves can help by choosing responsible travel options and respecting local customs.",
            "GAP6",
            "If we manage tourism carefully, everyone can benefit from it.",
        ],
        "sentences": [
            "A) However, large numbers of tourists can also cause problems.",
            "B) When people go on holiday, they spend money and create jobs.",
            "C) There are no easy answers to these challenges.",
            "D) As a result, various solutions have been tried.",
            "E) In addition, they expect a certain level of comfort and service.",
            "F) This has created both opportunities and challenges for popular destinations.",
            "G) It is clear that tourism will continue to play a major role in the world economy.",
        ],
        "answers": [1, 4, 0, 2, 3, 5],  # indices into sentences: B=1, E=4, A=0, C=2, D=3, F=5 (G extra)
    },
]

# --- Part 7: Multiple matching — 10 statements matched to sections A–D, 1 mark each ---
PART_7_DATA = [
    {
        "sections": [
            {"id": "A", "title": "City Museum", "text": "The museum is open every day except Monday. Entry is free for under-18s. There are guided tours at 11am and 2pm. The café is open from 10am to 4pm. Wheelchair access is available at the side entrance."},
            {"id": "B", "title": "River Boat Tours", "text": "Tours run from April to October, weather permitting. Departures are at 10am, 12pm, and 3pm. Booking in advance is recommended at weekends. Children under 5 travel free. The tour lasts approximately one hour."},
            {"id": "C", "title": "Central Park", "text": "The park is open from dawn until dusk. Dogs must be kept on a lead. There is a children's play area near the main gate. No cycling is allowed on the grass. The bandstand hosts free concerts on Sunday afternoons in summer."},
            {"id": "D", "title": "Art Gallery", "text": "The gallery is closed on Tuesdays. Students get half-price entry on presentation of a valid ID. Photography is not allowed in the main halls. The shop sells postcards and books. Last entry is 30 minutes before closing."},
        ],
        "questions": [
            {"text": "You can get a discount if you are still in education.", "correct": "D"},
            {"text": "You need to book ahead at busy times.", "correct": "B"},
            {"text": "You can listen to live music here in the summer.", "correct": "C"},
            {"text": "Young people do not have to pay to enter.", "correct": "A"},
            {"text": "You cannot take photos in certain areas.", "correct": "D"},
            {"text": "This place is not open every day of the week.", "correct": "A"},
            {"text": "Your pet can come with you if it is controlled.", "correct": "C"},
            {"text": "The trip takes about sixty minutes.", "correct": "B"},
            {"text": "You can enter through a special entrance if you use a wheelchair.", "correct": "A"},
            {"text": "You have to leave before the official closing time.", "correct": "D"},
        ],
    },
]

READING_DATA = [
    [
        {"sentence": "The _____ of the new shopping centre has been delayed. COMPLETE", "key": "COMPLETE", "answer": "completion", "gapNum": 1},
        {"sentence": "She looked at him _____ when he told the joke. SUSPECT", "key": "SUSPECT", "answer": "suspiciously", "gapNum": 2},
        {"sentence": "It was _____ of you to leave the door unlocked. RESPONSIBLE", "key": "RESPONSIBLE", "answer": "irresponsible", "gapNum": 3},
        {"sentence": "We need to make a _____ soon. DECIDE", "key": "DECIDE", "answer": "decision", "gapNum": 4},
        {"sentence": "The _____ of the product has improved. RELIABLE", "key": "RELIABLE", "answer": "reliability", "gapNum": 5},
    ],
    [
        {"sentence": "He's a very _____ person — he never gets angry. PATIENCE", "key": "PATIENCE", "answer": "patient", "gapNum": 1},
        {"sentence": "There was a _____ change in the weather. SUDDEN", "key": "SUDDEN", "answer": "sudden", "gapNum": 2},
        {"sentence": "I find it _____ to believe he said that. POSSIBLE", "key": "POSSIBLE", "answer": "impossible", "gapNum": 3},
        {"sentence": "She spoke so _____ that I couldn't hear her. QUIET", "key": "QUIET", "answer": "quietly", "gapNum": 4},
        {"sentence": "The _____ of the building took three years. CONSTRUCT", "key": "CONSTRUCT", "answer": "construction", "gapNum": 5},
    ],
    [
        {"sentence": "We had an _____ discussion about the project. PRODUCE", "key": "PRODUCE", "answer": "productive", "gapNum": 1},
        {"sentence": "His _____ to help was very kind. WILLING", "key": "WILLING", "answer": "willingness", "gapNum": 2},
        {"sentence": "The situation is becoming increasingly _____. DANGER", "key": "DANGER", "answer": "dangerous", "gapNum": 3},
        {"sentence": "She accepted the criticism _____. GRACIOUS", "key": "GRACIOUS", "answer": "graciously", "gapNum": 4},
        {"sentence": "We need to reduce our _____ on fossil fuels. DEPEND", "key": "DEPEND", "answer": "dependence", "gapNum": 5},
    ],
]

READING_DATA = [
    {
        "title": "The benefits of learning a musical instrument",
        "text": """<p>Learning to play a musical instrument is one of the most rewarding activities a person can take up. Whether you choose the piano, guitar, or violin, the benefits extend far beyond simply being able to play music.</p>
<p>Research has shown that learning an instrument improves memory and concentration. When you read music and coordinate your hands, you are exercising your brain in ways that few other activities can match. Many students who learn music also perform better in subjects like maths and languages.</p>
<p>Playing an instrument can also reduce stress. Focusing on the music allows you to forget your worries for a while. Moreover, joining a band or orchestra helps you meet people and build lasting friendships. Even practising alone can give you a sense of achievement when you finally master a difficult piece.</p>
<p>It is never too late to start. While children often learn quickly, adults can make excellent progress too, as long as they practise regularly. The key is to choose an instrument you enjoy and to set aside a little time each day.</p>""",
        "questions": [
            {"q": "According to the text, learning an instrument helps with:", "options": ["only playing music", "memory and concentration", "sports performance", "cooking skills"], "correct": 1},
            {"q": "The text says that playing music can help you:", "options": ["earn more money", "forget your worries", "travel more", "work longer hours"], "correct": 1},
            {"q": "What does the text say about adults learning an instrument?", "options": ["They cannot learn as well as children.", "They need to practise regularly.", "They should only learn the piano.", "They find it too stressful."], "correct": 1},
        ],
    },
    {
        "title": "Why we forget names",
        "text": """<p>Forgetting someone's name moments after being introduced is embarrassing, but it is extremely common. Scientists have studied why names are so difficult to remember compared to other information.</p>
<p>One reason is that names are arbitrary. If you meet someone called Mr Baker, his name does not tell you what he looks like or what he does. Unlike words that describe something, names are just labels with no built-in meaning. This makes them harder for the brain to store and retrieve.</p>
<p>Another factor is that we often do not pay full attention when we are introduced. We might be thinking about what we are going to say next, or worrying about making a good impression. When we are not fully focused, the name does not get properly encoded in our memory.</p>
<p>There are simple tricks that can help. Repeating the name when you hear it, and using it once or twice in the first few minutes of conversation, can make a big difference. Linking the name to a visual image or a famous person with the same name can also improve recall.</p>""",
        "questions": [
            {"q": "According to the text, why are names hard to remember?", "options": ["They are too long.", "They often have no meaning.", "People say them too quietly.", "We hear too many at once."], "correct": 1},
            {"q": "The text suggests we sometimes forget names because:", "options": ["we are not paying full attention", "the room is too noisy", "we have bad eyesight", "names are too short"], "correct": 0},
            {"q": "Which tip does the text give for remembering names?", "options": ["Write them down immediately.", "Repeat the name when you hear it.", "Only meet people one at a time.", "Avoid using the person's name."], "correct": 1},
        ],
    },
    {
        "title": "The history of the bicycle",
        "text": """<p>The bicycle has been around for over two hundred years, but its design has changed dramatically. The first two-wheeled vehicle that we would recognise as a bicycle was invented in Germany in 1817. It had no pedals; riders pushed it along with their feet. It was known as the "running machine" and was used mainly for short trips.</p>
<p>Pedals were added in the 1860s, which made cycling much easier. Early bicycles had a very large front wheel and a small back wheel. They were fast but dangerous, and difficult to get on and off. The "safety bicycle", with two wheels of equal size and a chain drive, was developed in the 1880s. This design is still the basis of most bicycles today.</p>
<p>Cycling became a popular pastime and sport in the late nineteenth century. Today, bicycles are used for transport, exercise, and leisure all over the world. They are also seen as an environmentally friendly alternative to cars in crowded cities.</p>""",
        "questions": [
            {"q": "The first bicycle from 1817:", "options": ["had pedals", "had no pedals", "had an engine", "was made in France"], "correct": 1},
            {"q": "The 'safety bicycle' had:", "options": ["a large front wheel only", "two equal-sized wheels and a chain", "no chain", "three wheels"], "correct": 1},
            {"q": "According to the text, bicycles today are considered:", "options": ["old-fashioned", "bad for the environment", "an environmentally friendly option", "only for sports"], "correct": 2},
        ],
    },
]

# Seed tasks for Use of English (inserted into DB on first run)
UOE_SEED_TASKS = [
    {"sentence1": "I've never been to Paris before.", "keyword": "FIRST", "sentence2": "It's the _____ I've been to Paris.", "answer": "first time"},
    {"sentence1": "We couldn't go out because of the rain.", "keyword": "PREVENTED", "sentence2": "The rain _____ going out.", "answer": "prevented us from"},
    {"sentence1": "I don't think we need to leave yet.", "keyword": "NECESSARY", "sentence2": "I don't think _____ leave yet.", "answer": "it's necessary to"},
    {"sentence1": "She started learning English five years ago.", "keyword": "BEEN", "sentence2": "She _____ English for five years.", "answer": "has been learning"},
    {"sentence1": "Perhaps John forgot about the meeting.", "keyword": "MIGHT", "sentence2": "John _____ about the meeting.", "answer": "might have forgotten"},
    {"sentence1": "It was wrong of you to shout at her.", "keyword": "SHOULD", "sentence2": "You _____ at her.", "answer": "shouldn't have shouted"},
    {"sentence1": "The film wasn't as good as I expected.", "keyword": "LIVE", "sentence2": "The film _____ my expectations.", "answer": "didn't live up to"},
    {"sentence1": "I last saw him in 2019.", "keyword": "SINCE", "sentence2": "I _____ 2019.", "answer": "haven't seen him since"},
    {"sentence1": "They say the weather will be fine tomorrow.", "keyword": "SUPPOSED", "sentence2": "The weather _____ fine tomorrow.", "answer": "is supposed to be"},
    {"sentence1": "I'd prefer you not to tell anyone.", "keyword": "RATHER", "sentence2": "I'd _____ anyone.", "answer": "rather you didn't tell"},
    {"sentence1": "We had to cancel the match because of the storm.", "keyword": "CALLED", "sentence2": "The match _____ because of the storm.", "answer": "had to be called off"},
    {"sentence1": "He is too young to drive.", "keyword": "OLD", "sentence2": "He _____ to drive.", "answer": "isn't old enough"},
    {"sentence1": "I'm sorry I didn't phone you earlier.", "keyword": "WISH", "sentence2": "I _____ you earlier.", "answer": "wish I had phoned"},
    {"sentence1": "Nobody in the class is taller than Maria.", "keyword": "TALLEST", "sentence2": "Maria _____ in the class.", "answer": "is the tallest"},
    {"sentence1": "They are building a new hospital in the town.", "keyword": "BUILT", "sentence2": "A new hospital _____ in the town.", "answer": "is being built"},
]
