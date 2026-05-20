#!/usr/bin/env python3
"""
Book Library Scanner (v2)
-------------------------
Recursively scans a folder for book / comic / document files and produces a
CSV catalog: filename, file_type, file_path, category.

Improvements over v1:
  - Much broader category dictionary (Christianity/Theology, Comics, Adult,
    Medical, Law, Education, Art, Music, Sports, Gaming, etc.)
  - Author-name hints from folder names (e.g. "Mike Murdock Collection")
  - Extension-aware fallbacks (.cbz/.cbr default to Comics)
  - Junk / non-book detection (hash-only names, .css/.js, "Front Cover.pdf")
  - Per-category score caps so a single noisy word can't dominate
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# File types
# ---------------------------------------------------------------------------

BOOK_EXTENSIONS = {
    ".pdf", ".epub", ".mobi", ".azw", ".azw3", ".djvu",
    ".fb2", ".lit", ".cbr", ".cbz", ".txt", ".rtf", ".doc", ".docx",
}

COMIC_EXTENSIONS = {".cbr", ".cbz"}

# Anything with these extensions or matching these patterns inside a book
# folder is almost certainly NOT a book (stylesheets, scripts, etc.).
JUNK_EXTENSIONS = {".css", ".js", ".eps"}

# Filenames that are clearly metadata / scraps, not books.
JUNK_NAME_PATTERNS = [
    re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE),       # hash-only names
    re.compile(r"^front[\s_-]?cover", re.IGNORECASE),
    re.compile(r"^back[\s_-]?cover", re.IGNORECASE),
    re.compile(r"^cover(\s*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"^torrent[\s_-]?downloaded", re.IGNORECASE),
    re.compile(r"^_+\s*download", re.IGNORECASE),
    re.compile(r"^_+\s*uploads?\s*will\s*stop", re.IGNORECASE),
    re.compile(r"^readme", re.IGNORECASE),
    re.compile(r"^thumbs(\.db)?$", re.IGNORECASE),
    re.compile(r"^amazonuk[\s_-]?\d+", re.IGNORECASE),
    re.compile(r"^e+$", re.IGNORECASE),                   # "eeeeeeeeee"
    # css/js/html files that were renamed to .txt and similar
    re.compile(r"(css|js|htm|html|stylesheet)\s*$", re.IGNORECASE),
    re.compile(r"^[a-z0-9]{1,10}\d+(css|js)$", re.IGNORECASE),
    # NEW: test/sample fixtures and image-converted-to-pdf scraps
    re.compile(r"^sample(\s*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"^test(\s*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"^untitled(\s*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"^document(\s*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"^\d{3}\.(?:jpg|jpeg|png|gif|tiff?)$", re.IGNORECASE),
    re.compile(r"^new\s+(?:document|microsoft\s+word|microsoft\s+excel)", re.IGNORECASE),
    re.compile(r"^scan(?:ned)?\s*\d*$", re.IGNORECASE),
    re.compile(r"^img[\s_-]?\d+$", re.IGNORECASE),
    re.compile(r"^image[\s_-]?\d+$", re.IGNORECASE),
    re.compile(r"^\d{1,4}$"),                              # bare numbers
    # NEW
    re.compile(r"^year[\s_-]?c?\d+\s*htm$", re.IGNORECASE),    # year-c83htm.txt scrapes
    re.compile(r"^\d+__?c?_?htm$", re.IGNORECASE),             # 1011250005__c_htm.txt
    re.compile(r"^acdsee\s+pdf\s+image", re.IGNORECASE),
    re.compile(r"^microsoft\s+(word|excel|powerpoint)", re.IGNORECASE),
    re.compile(r"^output(\s*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"^copy\s+of\s+", re.IGNORECASE),
    re.compile(r"^\d+\s*[a-z]?\s*htm$", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Categories. Order here matters ONLY as a tiebreaker.
# ---------------------------------------------------------------------------

CATEGORIES = {
    # =========================================================
    # ADULT / EROTIC  (placed first so the strong signals win
    # tiebreaks against generic "romance" keywords)
    # =========================================================
    "Adult/Erotica": [
        "erotica", "erotic", "porn", "hentai", "adult comic", "xxx",
        "bdsm", "kink", "fetish", "milf", "bbw", "futanari", "yaoi",
        "yuri", "smut", "naked", "nude", "lust", "lustful", "sex offender",
        "sexual", "sex slave", "harlot", "concubine", "stripper", "escort",
        "anal", "blowjob", "threesome", "orgasm", "bestiality",
        "incest", "stepmom", "stepbrother", "stepsister", "stepdad",
        "interracial-comics", "verotika", "eurotica", "bizzare",
        "playboy", "penthouse", "hustler",
    ],

    # =========================================================
    # CHRISTIANITY / THEOLOGY
    # (huge chunk of the user's library; broader than "religion")
    # =========================================================
    "Christianity/Theology": [
        "jesus", "christ", "christian", "christianity", "gospel",
        "bible", "biblical", "scripture", "scriptures", "old testament",
        "new testament", "theology", "theological", "doctrine", "doctrinal",
        "sermon", "preaching", "preacher", "ministry", "pastor", "pastoral",
        "evangel", "evangelism", "evangelical", "revival", "salvation",
        "redemption", "holy spirit", "the spirit", "the lord", "god's",
        "the cross", "the kingdom", "the church", "discipleship",
        "born again", "faith in", "prayer", "prayers", "praying",
        "fasting", "worship", "worshipping", "anointing", "anointed",
        "prophetic", "prophecy", "prophesy", "prophet", "apostle",
        "apostolic", "spiritual warfare", "demonic", "deliverance",
        "wesleyan", "calvinist", "calvinism", "reformed dogmatics",
        "pentecost", "pentecostal", "baptist", "methodist", "presbyterian",
        "catholic", "vatican", "pope", "psalms", "proverbs", "genesis",
        "exodus", "revelation", "epistle", "epistles", "commentary on",
        "commentaries", "exegesis", "hermeneutics", "soteriology",
        "ecclesiology", "eschatology", "missiology", "trinity",
        "trinitarian", "messiah", "messianic", "righteousness",
        "wigglesworth", "spurgeon", "tozer", "macarthur", "piper",
        "lewis chafer", "stott", "john stott", "mike murdock", "greg laurie",
        "t.d. jakes", "td jakes", "joyce meyer", "joel osteen",
        "kenneth hagin", "kenneth copeland", "derek prince",
        "frances j roberts", "smith wigglesworth", "curry blake",
        "herman hoeksema", "john eldredge", "francis chan", "max lucado",
        "rick warren", "billy graham", "andrew murray", "watchman nee",
        "leonard ravenhill", "charles spurgeon", "tyndale", "zondervan",
        # devotional phrasing that's characteristic of this corpus
        "devotional", "devotions", "365-day", "365 day devotional",
        "the power of god", "the power of prayer", "the authority of",
        "the believer", "spirit-filled", "spirit filled",
        "soul winning", "soulwinning", "healing the sick",
        "divine healing", "kingdom of god", "kingdom of heaven",
        "your destiny", "your purpose", "abundant life", "victorious life",
        "walk in the spirit", "walking in the spirit",
        "name of jesus", "blood of jesus", "presence of god",
        "born of the spirit", "fruit of the spirit", "gifts of the spirit",
        # NEW phrasing patterns from the latest sample
        "kingdom living", "kingdom principles", "the kingdom of",
        "blood covenant", "the anointing", "anointing of",
        "deliverance ministry", "spiritual warfare", "intercession",
        "intercessor", "intercessors", "school of the supernatural",
        "supernatural power", "supernatural ways", "supernatural encount",
        "heavenly realit", "heavenly places", "ways of royalty",
        "the prodigal", "prodigal son", "the cross of christ",
        "letters to god", "adventures in god", "with god",
        "of god ", "for god ", "to god ", "from god ",
        "in christ", "for christ", "with christ",
        "marriage bed", "biblical marriage", "godly marriage",
        "christian marriage", "marriage ministry", "marriage covenant",
        "spirit of god", "voice of god", "heart of god",
        "purpose driven", "purpose-driven", "the believer's",
        "born again", "saved by grace", "amazing grace",
        "grace and truth", "by grace through faith",
        "the gift of", "gifts of the", "ministry of",
        "called to", "calling of", "anointed to",
        "from the pulpit", "pulpit ministry", "the pew",
        "spirit-led", "spirit led", "led by the spirit",
        # NEW: high-signal bare words. These are weight-1 each, so they only
        # decide a file when it isn't already winning a stronger category.
        "god", "jesus", "christ", "christly", "lord",
        "gospel", "salvation", "savior", "saviour", "redeemer",
        "redemption", "atonement", "sanctification", "justification",
        "grace", "faith", "heaven", "heavenly", "spiritual",
        "church", "pastor", "preach", "ministry", "minister",
        "sin", "sinful", "sinner", "sinners", "righteous",
        "righteousness", "scripture", "holy", "holiness",
        "satan", "satanic", "demon", "demons", "demonic",
        "the devil", "intercessor", "intercession",
        # Bible book references — use unambiguous forms only.
        # Names like "matthew", "mark", "luke", "john", "james" are
        # avoided here because they collide with author first names.
        "book of genesis", "book of exodus", "book of leviticus",
        "book of numbers", "book of deuteronomy", "book of joshua",
        "book of judges", "book of ruth", "book of samuel",
        "book of kings", "book of chronicles", "book of ezra",
        "book of nehemiah", "book of esther", "book of job",
        "book of psalms", "book of proverbs", "book of ecclesiastes",
        "book of isaiah", "book of jeremiah", "book of lamentations",
        "book of ezekiel", "book of daniel", "book of hosea",
        "book of joel", "book of amos", "book of obadiah",
        "book of jonah", "book of micah", "book of habakkuk",
        "book of zephaniah", "book of haggai", "book of zechariah",
        "book of malachi", "book of matthew", "book of mark",
        "book of luke", "book of john", "book of acts",
        "book of romans", "book of revelation",
        "gospel of matthew", "gospel of mark", "gospel of luke",
        "gospel of john", "the gospels", "synoptic gospels",
        "epistles of paul", "pauline epistles", "minor prophets",
    ],

    # Other religions kept separate so search still works.
    "Religion: Other": [
        "quran", "qur'an", "koran", "islam", "islamic", "muslim", "hadith",
        "sharia", "sufi", "sufism",
        "torah", "talmud", "judaism", "jewish", "kabbalah", "rabbi",
        "buddhism", "buddhist", "buddha", "dharma", "zen", " sutra",
        "hinduism", "hindu", "vedic", "vedanta", "upanishad", "bhagavad",
        "krishna", "yoga sutras",
        "sikh", "sikhism", "guru granth",
        "taoism", "taoist", "tao te ching",
        "shinto", "shintoism",
        "wicca", "wiccan", "pagan", "paganism", "occult", "esoteric",
        "spiritualism", "new age",
    ],

    # =========================================================
    # COMICS / GRAPHIC NOVELS
    # =========================================================
    "Comics/Graphic Novels": [
        "comic", "comics", "graphic novel", "manga", "manhwa", "manhua",
        "marvel", "dc comics", "batman", "superman", "spiderman",
        "spider-man", "x-men", "avengers", "wonder woman", "justice league",
        "watchmen", "sandman", "hellboy", "tintin", "asterix", "garfield",
        "calvin and hobbes", "peanuts",
    ],

    # =========================================================
    # FICTION GENRES
    # =========================================================
    "Sci-Fi": [
        "scifi", "sci-fi", "science fiction", "space opera", "galactic",
        "galaxy", "starship", "robot", "android", "cyberpunk", "dystopia",
        "dystopian", "asimov", "heinlein", "philip k dick", "le guin",
        "alien", "extraterrestrial", "interstellar", "star wars", "star trek",
        "thrawn", "foundation series", "dune ", "ender's", "hyperion",
        "timothy zahn", "andy weir", "martian",
    ],
    "Fantasy": [
        "fantasy", "dragon", "dragons", "wizard", "wizards", "sorcerer",
        "sorceress", "magic", "mage", "elf", "elves", "dwarves",
        "tolkien", "lotr", "lord of the rings", "hobbit", "narnia",
        "game of thrones", "rowling", "harry potter", "sanderson",
        "stormlight", "mistborn", "wheel of time", "discworld",
        "robin hobb", "brandon sanderson", "name of the wind",
        "the witcher", "eternal sky",
    ],
    "Mystery/Thriller": [
        "mystery", "thriller", "detective", "noir", "crime fiction",
        "murder mystery", "whodunit", "sherlock", "poirot", "agatha christie",
        "gillian flynn", "jack reacher", "le carre", "le carré",
        "dalziel and pascoe", "spy novel", "espionage",
    ],
    "Horror": [
        "horror", "ghost", "haunted", "vampire", "vampires", "werewolf",
        "zombie", "zombies", "lovecraft", "cthulhu",
        "stephen king", "supernatural thriller",
    ],
    "Romance": [
        "romance", "love story", "lovers", "passion", "regency",
        "austen", "bronte", "harlequin", "highlander romance",
        "billionaire romance", "alpha male", "alpha romance",
    ],
    "Comedy": [
        "comedy", "humor", "humour", "funny", "satire", "wodehouse",
        "pratchett", "douglas adams", "hitchhiker", "david sedaris",
    ],
    "Historical Fiction": [
        "historical fiction", "wartime", "victorian", "tudor",
        "medieval romance", "ancient rome novel",
    ],
    "Young Adult": [
        "young adult", "ya novel", "ya fiction", "coming of age",
        "hunger games", "divergent", "twilight saga",
    ],
    "Classic Literature": [
        "shakespeare", "dickens", "dostoevsky", "tolstoy",
        "hemingway", "orwell", "kafka", "joyce", "jane austen",
        "mark twain", "moby dick", "ulysses",
    ],
    "Poetry": ["poetry", "poems", "sonnets", "haiku", "verse anthology"],

    # =========================================================
    # NON-FICTION
    # =========================================================
    "Biography/Memoir": [
        "biography", "memoir", "autobiography", "my life", "life of ",
        " a life", "diaries of", "letters of",
    ],
    "History": [
        "history of", "historical", "war ", "world war", "ww1", "ww2",
        "wwi", "wwii", "empire", "civilization", "ancient", "medieval",
        "renaissance", "great depression", "cold war", "vietnam war",
        "civil war", "holocaust", "third reich", "soviet union",
    ],
    "Philosophy": [
        "philosophy", "philosophical", "ethics", "metaphysics", "stoic",
        "nietzsche", "kant", "plato", "aristotle", "wittgenstein",
        "epistemology", "existential", "phenomenology",
    ],
    "Psychology": [
        "psychology", "cognitive", "behavioral", "behavioural",
        "freud", "jung", "thinking fast and slow", "psychotherapy",
        "psychoanalysis", "psychiatry", "attachment theory",
        "trauma", "ptsd", "anxiety", "depression treatment",
    ],
    "Self-Help": [
        "self help", "self-help", "habits", "productivity", "mindfulness",
        "atomic habits", "7 habits", "how to win", "law of attraction",
        "miracle morning", "high performance", "personal development",
    ],
    "Business/Finance": [
        "business", "management", "leadership", "startup", "entrepreneur",
        "marketing", "finance", "investing", "investment", "economics",
        "stock market", "trading", "personal finance", "accounting",
        "weygandt", "kpmg", "bookkeeping", "corporate", "ceo", "harvard business",
        "retail arbitrage", "passive income",
    ],
    "Science": [
        "science", "physics", "biology", "chemistry", "astronomy",
        "quantum", "relativity", "evolution", "cosmos", "neuroscience",
        "genetics", "ecology", "geology", "kinetic theory", "thermodynamic",
        "molecular", "scientific american",
    ],
    "Mathematics": [
        "math ", "mathematics", "mathematical", "algebra", "calculus",
        "geometry", "statistics", "statistician", "linear algebra",
        "discrete math", "topology", "number theory", "banach",
        "dirichlet", "variational",
        # additional math vocabulary
        "complex variables", "real analysis", "functional analysis",
        "differential equations", "fokker-planck", "fokkerplanck",
        "bifurcation", "manifold", "manifolds", "lie algebra",
        "lie group", "azumaya", "abelian", "galois", "harmonic analysis",
        "ergodic", "measure theory", "set theory", "graph theory",
        "combinatorics", "probability theory", "stochastic",
        "convex optimization", "operator theory",
        "representations and characters",
        # NEW
        "trigonometry", "precalculus", "pre-calculus",
        "matrix algebra", "matrix theory", "tensor calculus",
        "vector calculus", "integral equations", "partial differential",
        "ordinary differential", "numerical analysis",
        "numerical methods", "laplace transform", "fourier transform",
        "fourier analysis", "complex analysis", "real and complex",
        "p-adic", "elliptic curve", "modular form", "singularities",
        "curve shortening", "knot theory", "category theory",
        "model theory", "recursion theory", "metamathematics",
        "homological algebra", "commutative algebra", "ring theory",
        "field theory", "group theory", "representation theory",
        "spectral theory", "boundary value", "schrodinger equation",
    ],
    "Medical/Health": [
        "medicine", "medical", "anatomy", "physiology", "pharmacology",
        "nursing", "surgery", "surgical", "clinical", "diagnosis",
        "disease", "diseases", "therapy", "therapeutics", "patient",
        "doctor", "physician", "health and wellness", "nutrition",
        "diet ", "weight loss", "acupuncture", "chinese medicine",
        "herbal medicine", "naturopathic", "homeopathy", "yoga for",
        "chronic pain", "pain chronicles", "microbiology",
    ],
    "Law/Legal": [
        "law ", "legal", "lawyer", "attorney", "constitutional",
        "criminal law", "civil law", "contract law", "tort", "torts",
        "jurisprudence", "supreme court", "litigation",
    ],
    "Education/Teaching": [
        "teaching", "pedagogy", "instructional design", "classroom",
        "curriculum", "lesson plans", "homeschool", "tutoring",
        "study guide", "textbook", "solutions manual",
    ],
    "Art/Photography": [
        "painting", "drawing", "sketching", "art history",
        "fine art", "modern art", "photography", "photographer",
        "photographers", "sculpture", "calligraphy", "design book",
    ],
    "Music": [
        "music theory", "musician", "songwriting", "guitar", "piano",
        "violin", "drumming", "jazz", "classical music", "rock music",
        "hip hop", "songbook",
    ],
    "Cooking/Food": [
        "cookbook", "cooking", "recipes", "baking", "cuisine",
        "tacopedia", "preserving", "canning", "fermenting", "bbq",
        "vegetarian cookbook", "vegan cookbook",
    ],
    "Travel": [
        "travel guide", "guidebook", "lonely planet", "wanderlust",
        "rough guide", "fodor",
    ],
    "Sports/Fitness": [
        "fitness", "bodybuilding", "weightlifting", "crossfit",
        "marathon", "running guide", "cycling", "martial arts",
        "boxing", "yoga ", "pilates", "chi kung", "shaolin",
        "tai chi", "kung fu",
    ],
    "Politics/Current Affairs": [
        "politics", "political", "election", "democracy", "republican",
        "democrat", "socialism", "communism", "capitalism", "fascism",
        "geopolitics", "foreign policy", "terrorism", "extremism",
    ],
    "Sociology/Anthropology": [
        "sociology", "anthropology", "ethnography", "cultural studies",
        "race and", "feminism", "feminist", "gender studies",
        "social movement", "social theory",
    ],
    "Drugs/Cannabis": [
        "cannabis", "marijuana", "weed", "psychedelic", "psychedelics",
        "lsd", "mushrooms", "drug policy",
    ],
    "Games/RPG": [
        "dungeons and dragons", "d&d", "pathfinder", "warhammer",
        "tabletop rpg", "rpg sourcebook", "game master", "dungeon master",
        "video games", "speedrun",
    ],
    "Reference": [
        "dictionary", "encyclopedia", "encyclopaedia", "handbook of",
        "thesaurus", "almanac", "atlas of", "glossary",
    ],
    "Interview/Career": [
        "interview questions", "resume writing", "cover letter",
        "career guide", "job search",
    ],

    # =========================================================
    # PROGRAMMING / TECH
    # =========================================================
    "Programming: Python": [
        "python programming", "python crash", "learning python",
        "python cookbook", "django", "flask", "pandas", "numpy",
        "pytorch", "fluent python",
    ],
    "Programming: Java": [
        "java programming", "effective java", "spring framework",
        "hibernate orm", "jvm", "java concurrency",
    ],
    "Programming: JavaScript": [
        "javascript", "node.js", "nodejs", "react.js", " reactjs",
        "vue.js", "angular.js", "typescript", "ecmascript",
        "eloquent javascript",
    ],
    "Programming: C/C++": [
        "c++ programming", "the c programming language", " c++ primer",
        "effective c++", "modern c++",
    ],
    "Programming: C#/.NET": [
        "c# programming", "csharp programming", ".net framework",
        "asp.net", "entity framework",
    ],
    "Programming: Go": [
        "golang", "go programming language", "go in action",
    ],
    "Programming: Rust": [
        "rust programming", "rust language", "rust in action",
        "the rust book",
    ],
    "Programming: Ruby": [
        "ruby programming", "ruby on rails", "rails framework",
    ],
    "Programming: PHP": [
        "php programming", "laravel framework", "symfony framework",
    ],
    "Programming: Swift/iOS": [
        "swift programming", "ios development", "objective-c",
        "cocoa framework", "swiftui",
    ],
    "Programming: Kotlin/Android": [
        "kotlin programming", "android development", "android studio",
    ],
    "Programming: SQL/Databases": [
        "sql server", "mysql", "postgresql", "postgres ",
        "sqlite", "mongodb", "database design", "database systems",
        "oracle database",
    ],
    "Programming: General": [
        "programming language", "coding interview", "algorithms",
        "data structures", "design patterns", "clean code",
        "refactoring", "compiler design", "operating systems",
        "software engineering", "pragmatic programmer",
    ],
    "Web Development": [
        "html5", "css3", "web development", "frontend development",
        "backend development", "responsive design", "web design",
    ],
    "DevOps/Cloud": [
        "devops", "docker", "kubernetes", "amazon aws", " aws ",
        "azure cloud", "google cloud", "terraform", "ansible",
        "ci/cd", "site reliability",
    ],
    "Machine Learning/AI": [
        "machine learning", "deep learning", "neural network",
        "artificial intelligence", "tensorflow", "transformer model",
        " llm ", "large language model", "reinforcement learning",
        "computer vision", "natural language processing",
    ],
    "Cybersecurity": [
        "cybersecurity", "cyber security", "hacking", "ethical hacking",
        "pentesting", "penetration testing", "cryptography",
        "infosec", "malware analysis", "reverse engineering",
        "network security",
    ],
    "Data Science": [
        "data science", "data analysis", "data analytics", "big data",
        "data visualization",
    ],
    "Linux/Unix": [
        "linux ", "unix ", "bash scripting", "shell scripting",
        "ubuntu", "debian", "red hat", "kernel programming",
    ],

    # =========================================================
    # CRAFTS / DIY / HOBBIES
    # =========================================================
    "Woodworking/DIY": [
        "woodworking", "shopnotes", "shop notes", "wood turning",
        "wood working", "router jig", "dado jig", "joinery",
        "carpentry", "cabinetmaking", "cabinet making", "table saw",
        "workbench", "mortising", "the art of woodworking",
        "diy project", "diy projects", "leatherwork", "leathercraft",
        "metalworking", "blacksmithing", "knife making", "knifemaking",
        "soap making", "candle making", "knitting pattern",
        "crochet pattern", "quilting", "sewing pattern",
        "model railroad", "model railroading",
    ],
    "Gardening/Homesteading": [
        "gardening", "permaculture", "homestead", "homesteading",
        "beekeeping", "composting", "vegetable garden",
        "growing your own", "self-sufficient", "self sufficient",
        "off-grid", "off grid", "chicken keeping", "raising chickens",
        "small farm",
        # NEW broader plant/garden terms
        "growing plants", "houseplants", "indoor plants", "container garden",
        "garden design", "garden plants", "garden plan",
        "pruning", "landscape gardening", "horticulture",
        "plantiful", "herb garden", "herb gardening",
        "organic gardening", "raised beds", "raised bed",
        "seed starting", "seed saving", "edible garden", "edible plants",
        "flower garden", "perennials", "annuals plants",
        "kitchen garden", "back to the land",
    ],

    # =========================================================
    # ENGINEERING / APPLIED SCIENCE
    # (distinct from pure Science — covers the InTech books and
    # applied-physics / EE / mech-eng heavy tail.)
    # =========================================================
    "Engineering/Applied Science": [
        "intech", "fiber optic", "fiber optics", "optical detection",
        "laser remote sensing", "laser applications",
        "linear position sensor", "atomic absorption spectroscopy",
        "hydrodynamics", "fluid mechanics", "fluid dynamics",
        "heat transfer", "thermal engineering",
        "control theory", "control system", "control systems",
        "control design", "signal processing", "digital signal",
        "electrical engineering", "electronics engineering",
        "power electronics", "mechanical engineering",
        "civil engineering", "structural engineering",
        "chemical engineering", "process engineering",
        "industrial engineering", "manufacturing engineering",
        "discrete event simulation", "finite element",
        "energy conservation", "energy conversion",
        "renewable energy", "wind energy", "solar energy",
        "fuel cell", "fuel cells", "nuclear engineering",
        "robotics", "control engineering", "instrumentation",
        "antenna", "antennas", "microwave engineering",
        "telecommunications", "telecom engineering",
        "embedded system", "embedded systems",
        "experimental techniques", "measurement techniques",
        "perturbation", "perturbations", "low-temperature measurement",
    ],

    # =========================================================
    # RELATIONSHIPS / PARENTING
    # =========================================================
    "Marriage/Relationships": [
        "marriage", "your marriage", "great marriage", "the marriage",
        "marriages", "love and respect", "love languages",
        "love language", "dating advice", "relationship advice",
        "soulmate", "soul mate", "couples counseling",
        "couples therapy", "intimacy in", "save your marriage",
        "before you marry", "men are from mars",
        "for better or for worse", "premarital",
    ],
    "Parenting/Family": [
        "parenting", "raising kids", "raising children",
        "raising boys", "raising girls", "raising sons",
        "raising daughters", "for parents", "to parent",
        "your child", "your children", "your kids", "your son",
        "your daughter", "your teen", "your teenager",
        "fatherhood", "motherhood", "single mom", "single dad",
        "family ministry", "family life", "blended family",
        "adoption journey",
    ],

    # =========================================================
    # WRITING / AUTHORSHIP
    # =========================================================
    "Writing/Authorship": [
        "creative writing", "fiction writing", "novel writing",
        "how to write a novel", "you can write", "self publishing",
        "self-publishing", "screenwriting", "writers workshop",
        "writer's workshop", "writing craft", "on writing",
        "writing prompts", "the writer's", "writers digest",
        "writer's digest", "elements of style",
    ],

    # =========================================================
    # POLITICS / IDEOLOGY  (narrower additions)
    # =========================================================
    "Marxism/Critical Theory": [
        "marxism", "marxist", "why marx", "marx was right",
        "das kapital", "communist manifesto", "vygotsky",
        "frankfurt school", "critical theory", "lenin",
        "leninism", "trotsky", "trotskyism", "maoism",
        "revisionist revolution",
    ],
}

# Strong author-name signals — if any of these strings appear ANYWHERE in
# the path (filename or folder), treat them as a direct hit for the mapped
# category. These get a hefty score bonus.
AUTHOR_HINTS = {
    "Christianity/Theology": [
        "mike murdock", "greg laurie", "john stott", "curry blake",
        "tyndale", "smith wigglesworth", "td jakes", "t.d. jakes",
        "derek prince", "francis chan", "max lucado", "rick warren",
        "billy graham", "andrew murray", "watchman nee", "kenneth hagin",
        "kenneth copeland", "joyce meyer", "joel osteen",
        "charles spurgeon", "leonard ravenhill", "a.w. tozer", "aw tozer",
        "john macarthur", "john piper", "francis a. schaeffer",
        "herman hoeksema", "kavyakanta", "kaavyakanta",
        "sunday adelaja",
        # earlier expansion
        "t.l. osborn", "tl osborn", "tony evans", "john maxwell",
        "lester sumrall", "jerry savelle", "kathryn kuhlman",
        "mike connell", "kynan bridges", "john macmillan",
        "stephen kendrick", "ed stetzer", "don gossett",
        "roberts liardon", "priscilla shirer", "cindy jacobs",
        "mahesh chavda", "steve mcvey", "jentezen franklin",
        "rice broocks", "eddie smith", "eddie snipes",
        "randy alcorn", "stephen kaung", "john eldredge",
        "lisa bevere", "pamela mcquade", "joshua benjamin",
        "newton joseph", "julia audrina carrington",
        "frances j roberts", "clark pinnock", "j.l. taft",
        # NEW: high-volume authors found in the uncategorized chunk
        "john edmiston", "david oyedepo", "norvel hayes",
        "andrew wommack", "gloria copeland", "myles munroe",
        "marilyn hickey", "rudi louw", "rick johnson",
        "randy clark", "john hamel", "adam houge", "andy stanley",
        "creflo dollar", "jerry linkous", "charles stanley",
        "r.c. sproul", "rc sproul", "bill johnson",
        "pat holliday", "neil t. anderson", "neil anderson",
        "timothy keller", "tim keller", "gene getz",
        "frank hammond", "john eckhardt", "dennis clark",
        "francis frangipane", "willard f. harley", "casey treat",
        "cindy trimm", "john bevere",
        "charles hunter", "john g. lake", "john lake",
        "r.t. kendall", "rt kendall", "happy caldwell",
        "james maloney", "douglas weiss", "lee strobel",
        "kevin basconi", "jerry b. jenkins",
        "lysa terkeurst", "e.w. kenyon", "ew kenyon",
        "frank damazio", "bill farrel", "jennifer leclaire",
        "horatius bonar", "john baker", "guillermo maldonado",
        "leif hetland", "robert morris", "les parrott",
        "matthew robert payne", "david herzog",
        "tullian tchividjian", "dr. don colbert", "don colbert",
        "ryan rufus", "martyn lloyd-jones",
        "lloyd jones", "jim cymbala", "d. k. olukoya",
        "dk olukoya", "olukoya", "chip ingram", "terri savelle foy",
        "dutch sheets", "john bunyan", "gregory dickow",
        "heidi baker", "stephen arterburn", "christine caine",
        "wendy treat", "rick joyner", "ruben barreto",
        "john paul jackson", "kevin deyoung", "emerson eggerichs",
        "paul david tripp", "win worley", "joshua nickel",
        "stormie omartian", "jennifer kennedy dean",
        "michael whitworth", "henri nouwen", "kevin gerald",
        "ravi zacharias", "n.t. wright", "nt wright",
        "wayne grudem", "matt chandler", "david platt",
        "francis macnutt", "smith wigglesworth", "reinhard bonnke",
        "john wesley", "dwight l. moody", "d.l. moody",
        "george whitefield", "jonathan edwards", "j.i. packer",
        "ji packer", "henry blackaby", "beth moore", "joni eareckson",
        "philip yancey", "elisabeth elliot", "jim elliot",
        "j. vernon mcgee", "vernon mcgee", "charles finney",
        "oswald chambers", "e.m. bounds", "em bounds",
        "andrew bonar", "f.b. meyer", "fb meyer", "g. campbell morgan",
        "campbell morgan", "alistair begg", "voddie baucham",
        "paul washer", "ray comfort", "kirk cameron",
    ],
    "Sci-Fi": [
        "isaac asimov", "robert heinlein", "philip k dick", "ursula le guin",
        "frank herbert", "andy weir", "timothy zahn", "orson scott card",
        "arthur c clarke", "ray bradbury",
    ],
    "Fantasy": [
        "brandon sanderson", "patrick rothfuss", "robin hobb",
        "george r r martin", "george rr martin", "j r r tolkien",
        "j.r.r. tolkien", "terry pratchett", "neil gaiman",
    ],
    "Mystery/Thriller": [
        "lee child", "john le carre", "john le carré", "agatha christie",
        "stieg larsson", "james patterson", "michael connelly",
        "reginald hill",
    ],
    "Horror": ["stephen king", "h p lovecraft", "h.p. lovecraft", "clive barker"],
    "Romance": [
        "nora roberts", "danielle steel", "nicholas sparks",
        "katie porter", "karina halle",
    ],
    "Comedy": ["terry pratchett", "douglas adams", "p.g. wodehouse"],
}

# ---------------------------------------------------------------------------
# Pattern compilation
# ---------------------------------------------------------------------------

def _compile_keyword_index():
    """Return a list of (compiled_pattern, category) tuples."""
    out = []
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            # For purely-alphanumeric keywords, use soft word boundaries so
            # "god" doesn't match inside "good" but does match inside
            # "god's plan". An optional trailing "s" lets "cookbook" match
            # the very common subject form "cookbooks". For keywords with
            # punctuation (c++, .net, c#), just do a substring match.
            if re.match(r"^[a-z0-9 ']+$", kw_lower):
                # Only allow a trailing s when the keyword ends in a letter
                # (so "1990" doesn't become "1990s").
                tail_s = r"s?" if kw_lower[-1].isalpha() else ""
                pattern = re.compile(
                    r"(?<![a-z0-9])" + re.escape(kw_lower) + tail_s + r"(?![a-z0-9])"
                )
            else:
                pattern = re.compile(re.escape(kw_lower))
            out.append((pattern, category))
    return out


def _compile_author_index():
    out = []
    for category, authors in AUTHOR_HINTS.items():
        for a in authors:
            a_lower = a.lower().strip()
            pattern = re.compile(
                r"(?<![a-z0-9])" + re.escape(a_lower) + r"(?![a-z0-9])"
            )
            out.append((pattern, category))
    return out


KEYWORD_INDEX = _compile_keyword_index()
AUTHOR_INDEX = _compile_author_index()

# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

# Per-category max contribution per text source — prevents a single noisy
# folder/filename from running up the score with the same word repeated.
PER_SOURCE_CAP = 4


def _normalize(text: str) -> str:
    return text.lower().replace("_", " ").replace("-", " ")


def _looks_like_junk(file_path: Path) -> bool:
    if file_path.suffix.lower() in JUNK_EXTENSIONS:
        return True
    stem = file_path.stem
    for pat in JUNK_NAME_PATTERNS:
        if pat.match(stem):
            return True
    return False


def categorize(file_path: Path, root: Path) -> str:
    """Score categories and return the winner, or a sensible fallback."""

    # 1. Junk filter first — flag clearly non-book files.
    if _looks_like_junk(file_path):
        return "Junk/Non-book"

    scores = Counter()

    # 2. Filename text — weight 1
    name_text = _normalize(file_path.stem)
    name_hits = Counter()
    for pattern, category in KEYWORD_INDEX:
        if pattern.search(name_text):
            name_hits[category] += 1
    for cat, n in name_hits.items():
        scores[cat] += min(n, PER_SOURCE_CAP) * 1

    # Author hints in filename get a strong bonus.
    for pattern, category in AUTHOR_INDEX:
        if pattern.search(name_text):
            scores[category] += 5

    # 3. Folder names — weight 3 per folder, capped per folder per category
    try:
        rel_parts = file_path.parent.relative_to(root).parts
    except ValueError:
        rel_parts = file_path.parent.parts

    for folder_name in rel_parts:
        folder_text = _normalize(folder_name)
        folder_hits = Counter()
        for pattern, category in KEYWORD_INDEX:
            if pattern.search(folder_text):
                folder_hits[category] += 1
        for cat, n in folder_hits.items():
            scores[cat] += min(n, PER_SOURCE_CAP) * 3
        # Author hits in folders are extremely strong (e.g. "Mike Murdock
        # Collection (51 Books)").
        for pattern, category in AUTHOR_INDEX:
            if pattern.search(folder_text):
                scores[category] += 10

    if scores:
        return scores.most_common(1)[0][0]

    # 4. Extension-based fallback
    ext = file_path.suffix.lower()
    if ext in COMIC_EXTENSIONS:
        return "Comics/Graphic Novels"

    return "Uncategorized"


# ---------------------------------------------------------------------------
# OpenLibrary lookup (optional, only for files that local logic can't categorize)
# ---------------------------------------------------------------------------

import json
import time
import threading
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

OPENLIBRARY_URL = "https://openlibrary.org/search.json"
USER_AGENT = "BookScanner/1.0 (personal-library-cataloging)"

# Title-cleaning patterns
_AUTHOR_TAIL = re.compile(r"\s+[-–—]\s+[A-Z][A-Za-z'.\- ]{1,60}$")
_PAREN_TAIL = re.compile(r"\s*\([^)]{1,80}\)\s*$")
_BRACKET_TAIL = re.compile(r"\s*\[[^\]]{1,80}\]\s*$")
_SERIES_TAG = re.compile(r"\s+#\d+(\.\d+)?\b")
_VOLUME_TAG = re.compile(r"\b(vol|volume|v|book|part|pt)\.?\s*\d+\b", re.IGNORECASE)
_UNDERSCORE_GAP = re.compile(r"_+")
_DOUBLE_DOT = re.compile(r"\.{2,}")
_MULTI_SPACE = re.compile(r"\s+")
_TRUNCATION = re.compile(r"\s+[A-Z][a-z]{1,3}\s*$")     # "...The Practi"


def clean_title_for_lookup(filename: str) -> str:
    """
    Turn a messy filename into something OpenLibrary can search by title.
    Strips extension, "- Author Name" suffix, series numbers, parens, etc.
    """
    # Strip extension
    title = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename)
    # Underscores → spaces (your library often has "Title_ Subtitle")
    title = _UNDERSCORE_GAP.sub(" ", title)
    # Double-dots → single
    title = _DOUBLE_DOT.sub(".", title)
    # Trailing "- Author Name"
    while True:
        new = _AUTHOR_TAIL.sub("", title)
        if new == title:
            break
        title = new
    # Trailing (parenthetical) chunks like "(Series #3)" or "(v1.0)"
    title = _PAREN_TAIL.sub("", title)
    title = _BRACKET_TAIL.sub("", title)
    # Series tags like "#13"
    title = _SERIES_TAG.sub("", title)
    # Strip "vol. 2" / "part 3" tail tags
    title = _VOLUME_TAG.sub("", title)
    # Common file-suffix artifacts
    for junk in (" copy", "_1", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9",
                 " (1)", " (2)", " (3)", " (4)", " (5)"):
        if title.lower().endswith(junk):
            title = title[: -len(junk)]
    # Trailing single capitalized word (likely truncation)
    title = _TRUNCATION.sub("", title)
    # Collapse whitespace and punctuation crumbs
    title = title.replace(":", " ").replace(",", " ")
    title = _MULTI_SPACE.sub(" ", title).strip(" -–—_.,;:")
    return title


class _RateLimiter:
    """Tiny token-bucket-ish limiter: ensures min_gap seconds between calls."""

    def __init__(self, min_gap: float):
        self.min_gap = min_gap
        self.lock = threading.Lock()
        self.next_ok = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if now < self.next_ok:
                time.sleep(self.next_ok - now)
                now = time.monotonic()
            self.next_ok = now + self.min_gap


class OpenLibraryClient:
    """
    Thin client with on-disk JSON cache and rate limiting.
    Returns a list of lowercased subject strings, or [] when not found / on error.
    """

    def __init__(self, cache_path: Path, min_gap: float = 0.12, timeout: float = 10.0):
        self.cache_path = cache_path
        self.timeout = timeout
        self.limiter = _RateLimiter(min_gap)
        self.cache: dict = {}
        self.cache_lock = threading.Lock()
        self.dirty = False
        self._load_cache()

    def _load_cache(self):
        if self.cache_path.is_file():
            try:
                with self.cache_path.open("r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}

    def save_cache(self):
        if not self.dirty:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
            tmp.replace(self.cache_path)
            self.dirty = False
        except Exception as e:
            print(f"  (warning: could not save cache: {e})", file=sys.stderr)

    def subjects_for(self, title: str) -> list[str]:
        if not title or len(title) < 3:
            return []
        key = title.lower()

        with self.cache_lock:
            if key in self.cache:
                return self.cache[key]

        self.limiter.wait()
        params = {
            "title": title,
            "fields": "title,subject,author_name,first_publish_year",
            "limit": "3",
        }
        url = OPENLIBRARY_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        subjects: list[str] = []
        api_failed = False
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            docs = data.get("docs") or []
            for doc in docs[:3]:
                for s in (doc.get("subject") or []):
                    if isinstance(s, str):
                        subjects.append(s.lower())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            api_failed = True
        except Exception:
            api_failed = True

        # Cache result. We cache both hits AND legitimate "no subjects found"
        # responses (so we don't re-query rare/obscure titles forever). But
        # we do NOT cache responses where the API call itself failed —
        # those should be retried on the next run when the network is back.
        if not api_failed:
            with self.cache_lock:
                self.cache[key] = subjects
                self.dirty = True
        return subjects


def categorize_from_subjects(subjects: list[str]) -> str:
    """
    Map a list of OpenLibrary subjects to one of our categories.

    A small list of DECISIVE phrases pins the category outright (e.g. any
    subject containing "science fiction" -> Sci-Fi). Otherwise we score
    each subject by the longest matching keyword per category.
    """
    if not subjects:
        return "Uncategorized"

    # 1. Decisive overrides — short list of unambiguous phrases.
    # Order matters: more specific genres come BEFORE broader categorizations
    # like "young adult" or "juvenile fiction".
    decisive = [
        ("science fiction", "Sci-Fi"),
        ("fantasy fiction", "Fantasy"),
        ("dragons, fiction", "Fantasy"),
        ("wizards, fiction", "Fantasy"),
        ("wizards", "Fantasy"),
        ("mystery fiction", "Mystery/Thriller"),
        ("detective and mystery", "Mystery/Thriller"),
        ("horror fiction", "Horror"),
        ("romance fiction", "Romance"),
        ("romance novel", "Romance"),
        ("love stories", "Romance"),
        ("self-help", "Self-Help"),
        ("self help", "Self-Help"),
        ("comic books, strips", "Comics/Graphic Novels"),
        ("graphic novels", "Comics/Graphic Novels"),
        ("comic books", "Comics/Graphic Novels"),
        ("manga", "Comics/Graphic Novels"),
        ("cookbook", "Cooking/Food"),
        ("cookery", "Cooking/Food"),
        ("biography", "Biography/Memoir"),
        ("autobiography", "Biography/Memoir"),
        ("memoir", "Biography/Memoir"),
        ("poetry", "Poetry"),
        ("travel guide", "Travel"),
        ("woodwork", "Woodworking/DIY"),
        ("cabinetmak", "Woodworking/DIY"),
        ("erotic", "Adult/Erotica"),
        ("christian life", "Christianity/Theology"),
        ("theology", "Christianity/Theology"),
        ("biblical", "Christianity/Theology"),
        ("evangelical", "Christianity/Theology"),
        ("dystopia", "Sci-Fi"),
        # Broader genre tags AFTER specific ones
        ("juvenile fiction", "Young Adult"),
        ("young adult", "Young Adult"),
    ]
    joined = " | ".join(s.lower() for s in subjects)
    for needle, cat in decisive:
        if needle in joined:
            return cat

    # 2. Otherwise score by longest matching keyword per category per subject.
    scores = Counter()
    for s in subjects:
        text = _normalize(s)
        best_per_cat: dict[str, int] = {}
        for pattern, category in KEYWORD_INDEX:
            if pattern.search(text):
                length = len(pattern.pattern)
                if length > best_per_cat.get(category, 0):
                    best_per_cat[category] = length
        for cat, length in best_per_cat.items():
            scores[cat] += 1 + (length / 20.0)

    if not scores:
        return "Uncategorized"
    return scores.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_folder(
    root: Path,
    output_csv: Path,
    include_all: bool = False,
    *,
    use_lookup: bool = False,
    cache_path: Path | None = None,
    workers: int = 8,
) -> int:
    """
    Walk `root` and write a categorized CSV. When `use_lookup` is True,
    files that local logic can't categorize get a second pass via the
    OpenLibrary search API (with caching).
    """

    # Pass 1: local categorization
    rows = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            file_path = Path(dirpath) / fname
            ext = file_path.suffix.lower()
            if not include_all and ext not in BOOK_EXTENSIONS:
                continue
            category = categorize(file_path, root)
            rows.append({
                "filename": file_path.name,
                "file_type": ext.lstrip(".") if ext else "",
                "file_path": str(file_path.resolve()),
                "category": category,
            })

    print(f"  Local pass: {len(rows)} files, "
          f"{sum(1 for r in rows if r['category'] == 'Uncategorized')} uncategorized")

    # Pass 2 (optional): OpenLibrary
    if use_lookup:
        cache_file = cache_path or (Path.home() / ".book_scanner_cache.json")
        client = OpenLibraryClient(cache_file)
        targets = [r for r in rows if r["category"] == "Uncategorized"]

        if targets:
            print(f"  OpenLibrary lookup for {len(targets)} files "
                  f"(cache: {cache_file})...")
            looked_up = 0
            new_categories = 0
            t0 = time.monotonic()

            def worker(row):
                title = clean_title_for_lookup(row["filename"])
                if not title:
                    return row, "Uncategorized", title
                subjects = client.subjects_for(title)
                new_cat = categorize_from_subjects(subjects)
                return row, new_cat, title

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(worker, r) for r in targets]
                for fut in as_completed(futures):
                    try:
                        row, new_cat, _title = fut.result()
                    except Exception:
                        continue
                    looked_up += 1
                    if new_cat != "Uncategorized":
                        row["category"] = new_cat
                        new_categories += 1
                    if looked_up % 100 == 0:
                        elapsed = time.monotonic() - t0
                        rate = looked_up / max(elapsed, 0.001)
                        remaining = (len(targets) - looked_up) / max(rate, 0.001)
                        print(f"    ... {looked_up}/{len(targets)} "
                              f"({new_categories} new categories so far, "
                              f"~{remaining:.0f}s remaining)")
                        client.save_cache()

            client.save_cache()
            print(f"  OpenLibrary categorized {new_categories} additional files.")

    # Write the CSV
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "file_type", "file_path", "category"])
        for r in rows:
            writer.writerow([r["filename"], r["file_type"],
                             r["file_path"], r["category"]])

    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan a folder for book files and produce a categorized CSV.",
    )
    parser.add_argument("folder", help="Root folder to scan (recurses).")
    parser.add_argument(
        "-o", "--output", default="books_catalog.csv",
        help="Output CSV path (default: books_catalog.csv).",
    )
    parser.add_argument(
        "--all-files", action="store_true",
        help="Include every file, not just known book extensions.",
    )
    parser.add_argument(
        "--lookup", action="store_true",
        help="For files that can't be categorized locally, query the free "
             "OpenLibrary API to find subjects and map them to our categories. "
             "Results are cached on disk so subsequent runs are fast.",
    )
    parser.add_argument(
        "--cache", default=None,
        help="Path to the OpenLibrary lookup cache "
             "(default: ~/.book_scanner_cache.json).",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Concurrent OpenLibrary lookups (default: 8). "
             "Be polite — the public API is free.",
    )
    args = parser.parse_args()

    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output).expanduser().resolve()
    cache_path = Path(args.cache).expanduser().resolve() if args.cache else None

    print(f"Scanning {root}")
    count = scan_folder(
        root, out_path,
        include_all=args.all_files,
        use_lookup=args.lookup,
        cache_path=cache_path,
        workers=args.workers,
    )
    print(f"Wrote {count} rows to {out_path}")


if __name__ == "__main__":
    main()