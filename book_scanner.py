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
        # additional authors found in the user's library
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
            # "god's plan". For keywords with punctuation (c++, .net, c#),
            # just do a substring match.
            if re.match(r"^[a-z0-9 ']+$", kw_lower):
                pattern = re.compile(
                    r"(?<![a-z0-9])" + re.escape(kw_lower) + r"(?![a-z0-9])"
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
# Scanning
# ---------------------------------------------------------------------------

def scan_folder(root: Path, output_csv: Path, include_all: bool = False) -> int:
    rows_written = 0
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "file_type", "file_path", "category"])

        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                file_path = Path(dirpath) / fname
                ext = file_path.suffix.lower()

                if not include_all and ext not in BOOK_EXTENSIONS:
                    continue

                category = categorize(file_path, root)
                writer.writerow([
                    file_path.name,
                    ext.lstrip(".") if ext else "",
                    str(file_path.resolve()),
                    category,
                ])
                rows_written += 1

    return rows_written


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
    args = parser.parse_args()

    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output).expanduser().resolve()
    count = scan_folder(root, out_path, include_all=args.all_files)
    print(f"Scanned {root}")
    print(f"Wrote {count} rows to {out_path}")


if __name__ == "__main__":
    main()
