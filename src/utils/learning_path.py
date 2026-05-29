"""
🧬 Learning DNA Sequencer
Analyzes roadmap tags and generates an intelligent learning path with:
- Prerequisite detection via a curated knowledge graph
- Topological sort for optimal learning order
- Difficulty level assignment (Beginner → Intermediate → Advanced → Expert)
- Phase grouping (Foundation → Core → Specialization → Mastery)
- Estimated learning hours from actual resource durations
- Progress checkpoints with project suggestions
"""

from collections import defaultdict, deque

import yaml
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

FALLBACK_PREREQUISITE_GRAPH = {
    # Web Fundamentals
    "html": [],
    "css": ["html"],
    "sass": ["css"],
    "scss": ["css"],
    "tailwind": ["css"],
    "bootstrap": ["css"],
    "javascript": ["html", "css"],
    "typescript": ["javascript"],
    "dom": ["javascript"],
    # Frontend Frameworks
    "react": ["javascript"],
    "react js": ["javascript"],
    "next.js": ["react"],
    "nextjs": ["react"],
    "next js": ["react"],
    "gatsby": ["react"],
    "angular": ["typescript"],
    "vue": ["javascript"],
    "vue.js": ["javascript"],
    "nuxt": ["vue"],
    "nuxt.js": ["vue"],
    "svelte": ["javascript"],
    "sveltekit": ["svelte"],
    # State Management
    "redux": ["react"],
    "zustand": ["react"],
    "mobx": ["react"],
    "pinia": ["vue"],
    "vuex": ["vue"],
    "ngrx": ["angular"],
    "rxjs": ["typescript"],
    # CSS-in-JS / Styling
    "styled-components": ["react", "css"],
    "emotion": ["react", "css"],
    # Backend - Node
    "node": ["javascript"],
    "node.js": ["javascript"],
    "nodejs": ["javascript"],
    "node js": ["javascript"],
    "express": ["node"],
    "expressjs": ["node"],
    "express.js": ["node"],
    "nest.js": ["typescript", "node"],
    "nestjs": ["typescript", "node"],
    "fastify": ["node"],
    # Backend - Python
    "python": [],
    "flask": ["python"],
    "django": ["python"],
    "fastapi": ["python"],
    # Backend - Java
    "java": [],
    "spring": ["java"],
    "spring boot": ["java"],
    # Backend - C# / .NET
    "c#": [],
    "linq": ["c#"],
    "ef core": ["c#", "linq"],
    "entity framework core": ["c#", "linq"],
    "asp.net": ["c#", "linq", "ef core"],
    "asp.net core": ["c#", "linq", "ef core"],
    ".net": ["c#", "linq", "ef core"],
    ".net core": ["c#", "linq", "ef core"],
    "blazor": ["c#"],
    "signalr": ["asp.net core"],
    # Backend - Others
    "php": [],
    "laravel": ["php"],
    "ruby": [],
    "rails": ["ruby"],
    "ruby on rails": ["ruby"],
    "go": [],
    "golang": [],
    "rust": [],
    "kotlin": ["java"],
    "scala": ["java"],
    "elixir": [],
    "swift": [],
    "dart": [],
    # Mobile
    "android": ["java"],
    "jetpack compose": ["kotlin"],
    "ios": ["swift"],
    "swiftui": ["swift"],
    "flutter": ["dart"],
    "react native": ["react"],
    # Databases
    "sql": [],
    "mysql": ["sql"],
    "postgresql": ["sql"],
    "postgres": ["sql"],
    "sqlite": ["sql"],
    "mongodb": [],
    "redis": [],
    "dynamodb": [],
    "cassandra": [],
    "neo4j": [],
    "elasticsearch": [],
    # ORMs & Query
    "prisma": ["typescript"],
    "sequelize": ["node"],
    "sqlalchemy": ["python"],
    # APIs
    "rest api": ["javascript"],
    "restful api": ["javascript"],
    "graphql": ["javascript"],
    "grpc": [],
    "websocket": ["javascript"],
    "api design": [],
    # Auth
    "jwt": ["rest api"],
    "oauth": ["rest api"],
    "authentication": [],
    "authorization": ["authentication"],
    # Testing
    "testing": [],
    "unit testing": ["testing"],
    "jest": ["javascript"],
    "pytest": ["python"],
    "cypress": ["javascript"],
    "selenium": [],
    "mocha": ["javascript"],
    "vitest": ["javascript"],
    # DevOps
    "git": [],
    "github": ["git"],
    "gitlab": ["git"],
    "docker": ["linux"],
    "kubernetes": ["docker"],
    "k8s": ["docker"],
    "ci/cd": ["git"],
    "github actions": ["git", "ci/cd"],
    "jenkins": ["ci/cd"],
    "terraform": ["cloud deployment"],
    "ansible": ["linux"],
    # Cloud
    "aws": [],
    "azure": [],
    "gcp": [],
    "google cloud": [],
    "firebase": [],
    "supabase": [],
    "cloud deployment": [],
    "heroku": [],
    "vercel": ["next.js"],
    "netlify": [],
    # Linux & System
    "linux": [],
    "bash": ["linux"],
    "shell scripting": ["linux"],
    "powershell": [],
    # CS Fundamentals
    "data structures": [],
    "algorithms": ["data structures"],
    "dsa": [],
    "oop": [],
    "object oriented programming": [],
    "functional programming": [],
    "design patterns": ["oop"],
    "system design": ["design patterns"],
    "clean code": ["oop"],
    "solid principles": ["oop"],
    "clean architecture": ["clean code", "solid principles"],
    "domain driven design": ["clean architecture"],
    "ddd": ["clean architecture"],
    "microservices": ["system design", "docker"],
    "event driven architecture": ["system design"],
    # Data Science & AI
    "data science": ["python"],
    "data analysis": ["python"],
    "pandas": ["python"],
    "numpy": ["python"],
    "matplotlib": ["python"],
    "machine learning": ["python", "numpy"],
    "deep learning": ["machine learning"],
    "tensorflow": ["deep learning"],
    "pytorch": ["deep learning"],
    "keras": ["deep learning"],
    "scikit-learn": ["machine learning"],
    "nlp": ["machine learning"],
    "natural language processing": ["machine learning"],
    "computer vision": ["deep learning"],
    "ai": [],
    "artificial intelligence": [],
    # Big Data
    "spark": ["python"],
    "hadoop": [],
    "data engineering": ["python", "sql"],
    "big data": ["python"],
    # Security
    "cybersecurity": [],
    "ethical hacking": ["networking"],
    "penetration testing": ["networking"],
    "network security": ["networking"],
    "cryptography": [],
    "networking": [],
    # Build Tools
    "webpack": ["javascript"],
    "vite": ["javascript"],
    "rollup": ["javascript"],
    # Others
    "blockchain": [],
    "web3": ["blockchain"],
    "solidity": ["blockchain"],
    "embedded systems": [],
    "iot": [],
    "arduino": [],
}

FALLBACK_TAG_ALIASES = {
    "node.js": "node",
    "node js": "node",
    "nodejs": "node",
    "express.js": "express",
    "expressjs": "express",
    "nest.js": "nestjs",
    "vue.js": "vue",
    "nuxt.js": "nuxt",
    "react js": "react",
    "next js": "next.js",
    "nextjs": "next.js",
    "vue js": "vue",
    "golang": "go",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "react native": "react native",
    "ruby on rails": "rails",
    "asp.net core": "asp.net",
    ".net core": ".net",
    "entity framework core": "ef core",
    "object oriented programming": "oop",
}

DIFFICULTY_MAP = {
    0: "Beginner",
    1: "Beginner",
    2: "Intermediate",
    3: "Intermediate",
    4: "Advanced",
    5: "Advanced",
}

PHASE_NAMES = {
    0: "Foundation",
    1: "Core Skills",
    2: "Specialization",
    3: "Mastery",
}


def load_skill_graph():
    graph = {}
    base = DATA_DIR / "skill_graphs"
    if base.exists():
        for path in base.glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data:
                        for k, v in data.items():
                            if isinstance(v, dict):
                                v["_source_file"] = path.name
                            elif v is None:
                                v = {"prerequisites": [], "_source_file": path.name}
                            elif isinstance(v, list):
                                v = {"prerequisites": v, "_source_file": path.name}
                            graph[k] = v
            except Exception as e:
                print(f"Error loading skill graph {path}: {e}")
    return graph


def load_aliases():
    aliases = {}
    path = DATA_DIR / "aliases.yaml"
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    aliases.update(data)
        except Exception as e:
            print(f"Error loading aliases: {e}")
    return aliases


def load_context_aliases():
    """Load context-aware aliases from data/context_aliases.yaml.

    Returns a dict mapping ambiguous alias keys to a list of
    {target, default, context} entries.
    """
    ctx_aliases = {}
    path = DATA_DIR / "context_aliases.yaml"
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and isinstance(data, dict):
                    ctx_aliases.update(data)
        except Exception as e:
            print(f"Error loading context aliases: {e}")
    return ctx_aliases


# Load dynamic data
_graph_data = load_skill_graph()
_aliases_data = load_aliases()
_context_aliases_data = load_context_aliases()

if _graph_data:
    PREREQUISITE_GRAPH = {
        k: v.get("prerequisites", []) if isinstance(v, dict) else (v or [])
        for k, v in _graph_data.items()
    }
else:
    PREREQUISITE_GRAPH = FALLBACK_PREREQUISITE_GRAPH

if _aliases_data:
    TAG_ALIASES = _aliases_data
else:
    TAG_ALIASES = FALLBACK_TAG_ALIASES

CONTEXT_ALIASES = _context_aliases_data



def _resolve_context_alias(clean_key: str, context_tags: set | None = None) -> str | None:
    """Resolve an ambiguous alias using sibling tags as context.

    Returns the resolved target string, or None if the key is not a
    context alias.
    """
    entry = CONTEXT_ALIASES.get(clean_key)
    if not entry or not isinstance(entry, list):
        return None

    if context_tags:
        # Score each candidate by counting context-hint overlaps
        best_target = None
        best_score = -1
        default_target = None

        for candidate in entry:
            target = candidate.get("target", "")
            hints = set(candidate.get("context", []))
            is_default = candidate.get("default", False)
            if is_default:
                default_target = target

            score = len(hints & context_tags)
            if score > best_score:
                best_score = score
                best_target = target

        # If any context matched, use the best match; otherwise fall back
        if best_score > 0:
            return best_target
        return default_target or best_target

    # No context provided — use default entry
    for candidate in entry:
        if candidate.get("default", False):
            return candidate.get("target", "")
    # Fallback to first entry
    return entry[0].get("target", "") if entry else None


def _normalize_tag(tag: str, context_tags: set | None = None) -> str:
    clean = tag.lower().replace("-", " ").strip()
    # Try context-aware alias first
    ctx_result = _resolve_context_alias(clean, context_tags)
    if ctx_result is not None:
        return ctx_result
    return TAG_ALIASES.get(clean, clean)


def _get_depth(tag: str, memo: dict = None, context_tags: set | None = None) -> int:
    if memo is None:
        memo = {}
    normalized = _normalize_tag(tag, context_tags)
    if normalized in memo:
        return memo[normalized]

    prereqs = PREREQUISITE_GRAPH.get(normalized, [])
    if not prereqs:
        memo[normalized] = 0
        return 0

    max_depth = 0
    for prereq in prereqs:
        d = _get_depth(prereq, memo, context_tags)
        max_depth = max(max_depth, d + 1)

    memo[normalized] = max_depth
    return max_depth


def _topological_sort(tags: list[str], context_tags: set | None = None) -> list[str]:
    normalized = [_normalize_tag(t, context_tags) for t in tags]
    tag_set = set(normalized)

    # Build adjacency from prerequisites that exist in our tag set
    in_degree = defaultdict(int)
    adj = defaultdict(list)

    for tag in normalized:
        prereqs = PREREQUISITE_GRAPH.get(tag, [])
        for prereq in prereqs:
            prereq_norm = _normalize_tag(prereq, context_tags)
            if prereq_norm in tag_set:
                adj[prereq_norm].append(tag)
                in_degree[tag] += 1

    for tag in normalized:
        if tag not in in_degree:
            in_degree[tag] = 0

    # Sort by depth first so Foundation tags come before Advanced ones
    depth_memo = {}
    queue = deque(
        sorted(
            [t for t in normalized if in_degree[t] == 0],
            key=lambda t: _get_depth(t, depth_memo, context_tags),
        )
    )
    sorted_tags = []

    while queue:
        tag = queue.popleft()
        sorted_tags.append(tag)
        for neighbor in adj[tag]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    remaining = [t for t in normalized if t not in sorted_tags]
    sorted_tags.extend(remaining)

    original_map = {_normalize_tag(t, context_tags): t for t in tags}
    return [original_map.get(t, t) for t in sorted_tags]


def _estimate_hours(tag: str, resource_data: dict = None, context_tags: set | None = None) -> float:
    if resource_data and isinstance(resource_data, dict):
        duration = resource_data.get("duration_mins", 0)
        video_count = resource_data.get("videoCount", 0)

        if duration and duration > 0:
            return round(duration / 60 * 1.5, 1)  # 1.5x for practice

        if video_count and video_count > 0:
            avg_video_mins = 15
            return round((video_count * avg_video_mins) / 60 * 1.5, 1)

    normalized = _normalize_tag(tag, context_tags)
    if _graph_data:
        node_data = _graph_data.get(normalized)
        if isinstance(node_data, dict) and "estimated_hours" in node_data:
            val = node_data["estimated_hours"]
            if isinstance(val, (int, float)):
                return float(val)

    depth = _get_depth(normalized, context_tags=context_tags)

    base_hours = {
        0: 20,  # Beginner topics
        1: 30,
        2: 40,
        3: 50,
        4: 60,
        5: 80,
    }
    return base_hours.get(min(depth, 5), 40)


def _get_difficulty(tag: str, context_tags: set | None = None) -> str:
    normalized = _normalize_tag(tag, context_tags)
    if _graph_data:
        node_data = _graph_data.get(normalized)
        if isinstance(node_data, dict) and "difficulty" in node_data:
            diff = node_data["difficulty"]
            if isinstance(diff, str):
                return diff.capitalize()

    depth = _get_depth(normalized, context_tags=context_tags)
    return DIFFICULTY_MAP.get(min(depth, 5), "Advanced")



def _detect_domain(tags: list[str], context_tags: set | None = None) -> str:
    if context_tags is None:
        context_tags = {t.lower().replace("-", " ").strip() for t in tags}
    normalized = [_normalize_tag(t, context_tags) for t in tags]

    # Software Engineering domain mappings for nodes in software_engineering.yaml
    SOFTWARE_ENG_DOMAINS = {
        # Frontend
        "html": "Frontend Development", "css": "Frontend Development", "sass": "Frontend Development",
        "scss": "Frontend Development", "tailwind": "Frontend Development", "bootstrap": "Frontend Development",
        "javascript": "Frontend Development", "typescript": "Frontend Development", "dom": "Frontend Development",
        "react": "Frontend Development", "next.js": "Frontend Development", "gatsby": "Frontend Development",
        "angular": "Frontend Development", "vue": "Frontend Development", "nuxt": "Frontend Development",
        "svelte": "Frontend Development", "sveltekit": "Frontend Development", "redux": "Frontend Development",
        "zustand": "Frontend Development", "mobx": "Frontend Development", "pinia": "Frontend Development",
        "vuex": "Frontend Development", "ngrx": "Frontend Development", "rxjs": "Frontend Development",
        "styled-components": "Frontend Development", "emotion": "Frontend Development", "webpack": "Frontend Development",
        "vite": "Frontend Development", "rollup": "Frontend Development",

        # Backend
        "node": "Backend Development", "express": "Backend Development", "nestjs": "Backend Development",
        "fastify": "Backend Development", "python": "Backend Development", "flask": "Backend Development",
        "django": "Backend Development", "fastapi": "Backend Development", "java": "Backend Development",
        "spring": "Backend Development", "spring boot": "Backend Development", "c#": "Backend Development",
        "linq": "Backend Development", "ef core": "Backend Development", "asp.net": "Backend Development",
        ".net": "Backend Development", "blazor": "Backend Development", "signalr": "Backend Development",
        "php": "Backend Development", "laravel": "Backend Development", "ruby": "Backend Development",
        "rails": "Backend Development", "go": "Backend Development", "rust": "Backend Development",
        "kotlin": "Backend Development", "scala": "Backend Development", "elixir": "Backend Development",
        "sql": "Backend Development", "mysql": "Backend Development", "postgresql": "Backend Development",
        "sqlite": "Backend Development", "mongodb": "Backend Development", "redis": "Backend Development",
        "dynamodb": "Backend Development", "cassandra": "Backend Development", "neo4j": "Backend Development",
        "elasticsearch": "Backend Development", "prisma": "Backend Development", "sequelize": "Backend Development",
        "sqlalchemy": "Backend Development", "rest api": "Backend Development", "graphql": "Backend Development",
        "grpc": "Backend Development", "websocket": "Backend Development", "api design": "Backend Development",
        "jwt": "Backend Development", "oauth": "Backend Development", "authentication": "Backend Development",
        "authorization": "Backend Development", "unit testing": "Backend Development", "pytest": "Backend Development",
        "mocha": "Backend Development", "testing": "Backend Development", "cypress": "Backend Development",
        "selenium": "Backend Development", "vitest": "Backend Development",

        # Mobile
        "android": "Mobile Development", "jetpack compose": "Mobile Development", "ios": "Mobile Development",
        "swiftui": "Mobile Development", "flutter": "Mobile Development", "react native": "Mobile Development",
        "swift": "Mobile Development", "dart": "Mobile Development",

        # Cybersecurity & Networking -> DevOps
        "cybersecurity": "DevOps & Cloud", "ethical hacking": "DevOps & Cloud", "penetration testing": "DevOps & Cloud",
        "network security": "DevOps & Cloud", "cryptography": "DevOps & Cloud", "networking": "DevOps & Cloud",
    }

    # Initialize domain scores
    scores = {
        "Frontend Development": 0.0,
        "Backend Development": 0.0,
        "Full-Stack Development": 0.0,
        "Data Science & AI": 0.0,
        "DevOps & Cloud": 0.0,
        "Mobile Development": 0.0,
    }

    for tag in normalized:
        domain = None
        node_data = _graph_data.get(tag)
        if node_data and isinstance(node_data, dict):
            source_file = node_data.get("_source_file", "")
            if source_file == "frontend_modern.yaml":
                domain = "Frontend Development"
            elif source_file in ("devops.yaml", "cloud_native.yaml", "security.yaml"):
                domain = "DevOps & Cloud"
            elif source_file in ("data_ai.yaml", "ai_agents.yaml", "data_engineering.yaml"):
                domain = "Data Science & AI"
            elif source_file == "software_engineering.yaml":
                domain = SOFTWARE_ENG_DOMAINS.get(tag)

        # Fallback to hardcoded/explicit checks if not found dynamically or not in software_engineering map
        if not domain:
            if tag in SOFTWARE_ENG_DOMAINS:
                domain = SOFTWARE_ENG_DOMAINS[tag]
            elif any(kw in tag for kw in ("react", "angular", "vue", "svelte", "css", "html", "next.js", "tailwind", "bootstrap", "sass", "nextjs", "nuxt", "gatsby")):
                domain = "Frontend Development"
            elif any(kw in tag for kw in ("node", "express", "django", "flask", "fastapi", "spring", "laravel", "asp.net", "nestjs", "rails")):
                domain = "Backend Development"
            elif any(kw in tag for kw in ("machine learning", "deep learning", "data science", "pandas", "tensorflow", "pytorch", "ai", "nlp", "computer vision", "generative ai", "llms", "rag")):
                domain = "Data Science & AI"
            elif any(kw in tag for kw in ("docker", "kubernetes", "ci/cd", "terraform", "aws", "azure", "gcp", "jenkins", "ansible")):
                domain = "DevOps & Cloud"
            elif any(kw in tag for kw in ("flutter", "react native", "android", "ios", "swiftui", "jetpack compose")):
                domain = "Mobile Development"

        if domain:
            scores[domain] += 1.0

    # Classify as Full-Stack only if BOTH Frontend and Backend are present,
    # and the minority score is at least 30% of the majority score.
    fe_score = scores["Frontend Development"]
    be_score = scores["Backend Development"]
    if fe_score > 0 and be_score > 0:
        majority = max(fe_score, be_score)
        minority = min(fe_score, be_score)
        if minority >= 0.3 * majority:
            scores["Full-Stack Development"] = fe_score + be_score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "Software Engineering"
    return best


def generate_learning_path(
    tags: list[str], roadmap_data: dict = None, tag_checkpoints: dict = None
) -> dict:
    if not tags:
        return {}

    # Build context set from raw tags for context-aware alias resolution.
    # Use simple lowercase normalization (no alias resolution) to avoid
    # chicken-and-egg: the context set is used to *decide* alias resolution.
    context_tags = {t.lower().replace("-", " ").strip() for t in tags}

    sorted_tags = _topological_sort(tags, context_tags)
    depth_memo = {}

    phases = []
    current_phase_tags = []
    current_depth_bucket = -1

    for tag in sorted_tags:
        normalized = _normalize_tag(tag, context_tags)
        depth = _get_depth(normalized, depth_memo, context_tags)
        bucket = min(depth // 2, 3)  # Group into 4 phases max

        if bucket != current_depth_bucket:
            if current_phase_tags:
                phase_idx = len(phases)
                phase_name = PHASE_NAMES.get(phase_idx, f"Phase {phase_idx + 1}")
                phases.append(
                    _build_phase(
                        phase_num=phase_idx + 1,
                        name=phase_name,
                        tags=current_phase_tags,
                        roadmap_data=roadmap_data,
                        tag_checkpoints=tag_checkpoints,
                        context_tags=context_tags,
                    )
                )
            current_phase_tags = []
            current_depth_bucket = bucket

        current_phase_tags.append(tag)

    if current_phase_tags:
        phase_idx = len(phases)
        phase_name = PHASE_NAMES.get(phase_idx, f"Phase {phase_idx + 1}")
        phases.append(
            _build_phase(
                phase_num=phase_idx + 1,
                name=phase_name,
                tags=current_phase_tags,
                roadmap_data=roadmap_data,
                tag_checkpoints=tag_checkpoints,
                context_tags=context_tags,
            )
        )

    total_hours = sum(p["estimated_hours"] for p in phases)
    domain = _detect_domain(tags, context_tags)

    daily_hours = 2
    weeks = max(1, round(total_hours / (daily_hours * 7)))

    prereqs_outside = []
    tag_set_norm = {_normalize_tag(t, context_tags) for t in tags}
    for tag in tags:
        normalized = _normalize_tag(tag, context_tags)
        for prereq in PREREQUISITE_GRAPH.get(normalized, []):
            prereq_norm = _normalize_tag(prereq, context_tags)
            if prereq_norm not in tag_set_norm and prereq_norm not in prereqs_outside:
                prereqs_outside.append(prereq_norm)

    result = {
        "domain": domain,
        "phases": phases,
        "total_estimated_hours": total_hours,
        "recommended_daily_hours": daily_hours,
        "estimated_completion_weeks": weeks,
        "total_tags": len(tags),
    }

    if prereqs_outside:
        result["recommended_prerequisites"] = prereqs_outside[:5]

    return result


def _build_phase(
    phase_num: int,
    name: str,
    tags: list[str],
    roadmap_data: dict = None,
    tag_checkpoints: dict = None,
    context_tags: set | None = None,
) -> dict:
    phase_tags = []
    total_hours = 0

    for tag in tags:
        resource = _find_resource(tag, roadmap_data, context_tags)
        hours = _estimate_hours(tag, resource, context_tags)
        total_hours += hours

        tag_info = {
            "tag": tag,
            "difficulty": _get_difficulty(tag, context_tags),
            "estimated_hours": hours,
        }

        # Use AI-generated checkpoints if available
        if tag_checkpoints:
            # Try exact match, then case-insensitive match
            checkpoints = tag_checkpoints.get(tag)
            if not checkpoints:
                tag_lower = tag.lower()
                for key, val in tag_checkpoints.items():
                    if key.lower() == tag_lower:
                        checkpoints = val
                        break
            if checkpoints:
                tag_info["checkpoints"] = checkpoints

        prereqs = PREREQUISITE_GRAPH.get(_normalize_tag(tag, context_tags), [])
        if prereqs:
            tag_info["prerequisites"] = prereqs

        if resource and isinstance(resource, dict):
            tag_info["has_resource"] = True
            tag_info["resource_type"] = resource.get("contentType", "Unknown")
        else:
            tag_info["has_resource"] = False

        phase_tags.append(tag_info)

    difficulties = [t["difficulty"] for t in phase_tags]
    difficulty_order = ["Beginner", "Intermediate", "Advanced"]
    phase_difficulty = max(
        difficulties,
        key=lambda d: difficulty_order.index(d) if d in difficulty_order else 0,
    )

    return {
        "phase": phase_num,
        "name": name,
        "difficulty": phase_difficulty,
        "tags": phase_tags,
        "estimated_hours": round(total_hours, 1),
    }


def _find_resource(tag: str, roadmap_data: dict = None, context_tags: set | None = None) -> dict | None:
    """Find a resource for *tag* across all sources using progressively
    looser matching so that minor casing / punctuation differences don't
    cause a miss.
    """
    if not roadmap_data:
        return None

    tag_norm = _normalize_tag(tag, context_tags)
    # Strip all non-alphanumeric chars for fuzzy pass
    tag_alnum = "".join(ch for ch in tag_norm if ch.isalnum())

    for source in ["youtube", "coursera", "udemy"]:
        source_data = roadmap_data.get(source, {})
        if not source_data:
            continue

        # Pass 1 – exact key match (case-insensitive after normalize)
        for key, resource in source_data.items():
            if resource and _normalize_tag(key, context_tags) == tag_norm:
                return resource

        # Pass 2 – alphanumeric-only match (ignores punctuation / spaces)
        for key, resource in source_data.items():
            if not resource:
                continue
            key_alnum = "".join(ch for ch in _normalize_tag(key, context_tags) if ch.isalnum())
            if key_alnum == tag_alnum:
                return resource

        # Pass 3 – substring containment (one contains the other)
        for key, resource in source_data.items():
            if not resource:
                continue
            key_norm = _normalize_tag(key, context_tags)
            if tag_norm in key_norm or key_norm in tag_norm:
                return resource

    return None
