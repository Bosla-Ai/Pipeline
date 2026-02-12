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

PREREQUISITE_GRAPH = {
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

# Resolve common aliases so "Node.js", "node js", "node" all match
TAG_ALIASES = {
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


def _normalize_tag(tag: str) -> str:
    clean = tag.lower().replace("-", " ").strip()
    return TAG_ALIASES.get(clean, clean)


def _get_depth(tag: str, memo: dict = None) -> int:
    if memo is None:
        memo = {}
    normalized = _normalize_tag(tag)
    if normalized in memo:
        return memo[normalized]

    prereqs = PREREQUISITE_GRAPH.get(normalized, [])
    if not prereqs:
        memo[normalized] = 0
        return 0

    max_depth = 0
    for prereq in prereqs:
        d = _get_depth(prereq, memo)
        max_depth = max(max_depth, d + 1)

    memo[normalized] = max_depth
    return max_depth


def _topological_sort(tags: list[str]) -> list[str]:
    normalized = [_normalize_tag(t) for t in tags]
    tag_set = set(normalized)

    # Build adjacency from prerequisites that exist in our tag set
    in_degree = defaultdict(int)
    adj = defaultdict(list)

    for tag in normalized:
        prereqs = PREREQUISITE_GRAPH.get(tag, [])
        for prereq in prereqs:
            prereq_norm = _normalize_tag(prereq)
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
            key=lambda t: _get_depth(t, depth_memo),
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

    original_map = {_normalize_tag(t): t for t in tags}
    return [original_map.get(t, t) for t in sorted_tags]


def _estimate_hours(tag: str, resource_data: dict = None) -> float:
    if resource_data and isinstance(resource_data, dict):
        duration = resource_data.get("duration_mins", 0)
        video_count = resource_data.get("videoCount", 0)

        if duration and duration > 0:
            return round(duration / 60 * 1.5, 1)  # 1.5x for practice

        if video_count and video_count > 0:
            avg_video_mins = 15
            return round((video_count * avg_video_mins) / 60 * 1.5, 1)

    normalized = _normalize_tag(tag)
    depth = _get_depth(normalized)

    base_hours = {
        0: 20,  # Beginner topics
        1: 30,
        2: 40,
        3: 50,
        4: 60,
        5: 80,
    }
    return base_hours.get(min(depth, 5), 40)


def _get_difficulty(tag: str) -> str:
    normalized = _normalize_tag(tag)
    depth = _get_depth(normalized)
    return DIFFICULTY_MAP.get(min(depth, 5), "Advanced")


def _detect_domain(tags: list[str]) -> str:
    normalized = [_normalize_tag(t) for t in tags]

    frontend_kw = {
        "react",
        "angular",
        "vue",
        "svelte",
        "css",
        "html",
        "next.js",
        "tailwind",
        "bootstrap",
        "sass",
        "nextjs",
        "nuxt",
        "gatsby",
    }
    backend_kw = {
        "node",
        "express",
        "django",
        "flask",
        "fastapi",
        "spring",
        "laravel",
        "asp.net",
        "nest.js",
        "rails",
    }
    data_kw = {
        "machine learning",
        "deep learning",
        "data science",
        "pandas",
        "tensorflow",
        "pytorch",
        "ai",
        "nlp",
        "computer vision",
    }
    devops_kw = {
        "docker",
        "kubernetes",
        "ci/cd",
        "terraform",
        "aws",
        "azure",
        "gcp",
        "jenkins",
        "ansible",
    }
    mobile_kw = {
        "flutter",
        "react native",
        "android",
        "ios",
        "swiftui",
        "jetpack compose",
    }

    scores = {
        "Frontend Development": sum(1 for t in normalized if t in frontend_kw),
        "Backend Development": sum(1 for t in normalized if t in backend_kw),
        "Full-Stack Development": 0,
        "Data Science & AI": sum(1 for t in normalized if t in data_kw),
        "DevOps & Cloud": sum(1 for t in normalized if t in devops_kw),
        "Mobile Development": sum(1 for t in normalized if t in mobile_kw),
    }

    if scores["Frontend Development"] > 0 and scores["Backend Development"] > 0:
        scores["Full-Stack Development"] = (
            scores["Frontend Development"] + scores["Backend Development"]
        )

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "Software Engineering"
    return best


def generate_learning_path(
    tags: list[str], roadmap_data: dict = None, tag_checkpoints: dict = None
) -> dict:
    if not tags:
        return {}

    sorted_tags = _topological_sort(tags)
    depth_memo = {}

    phases = []
    current_phase_tags = []
    current_depth_bucket = -1

    for tag in sorted_tags:
        normalized = _normalize_tag(tag)
        depth = _get_depth(normalized, depth_memo)
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
            )
        )

    total_hours = sum(p["estimated_hours"] for p in phases)
    domain = _detect_domain(tags)

    daily_hours = 2
    weeks = max(1, round(total_hours / (daily_hours * 7)))

    prereqs_outside = []
    tag_set_norm = {_normalize_tag(t) for t in tags}
    for tag in tags:
        normalized = _normalize_tag(tag)
        for prereq in PREREQUISITE_GRAPH.get(normalized, []):
            prereq_norm = _normalize_tag(prereq)
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
) -> dict:
    phase_tags = []
    total_hours = 0

    for tag in tags:
        resource = _find_resource(tag, roadmap_data)
        hours = _estimate_hours(tag, resource)
        total_hours += hours

        tag_info = {
            "tag": tag,
            "difficulty": _get_difficulty(tag),
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

        prereqs = PREREQUISITE_GRAPH.get(_normalize_tag(tag), [])
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


def _find_resource(tag: str, roadmap_data: dict = None) -> dict | None:
    """Find a resource for *tag* across all sources using progressively
    looser matching so that minor casing / punctuation differences don't
    cause a miss.
    """
    if not roadmap_data:
        return None

    tag_norm = _normalize_tag(tag)
    # Strip all non-alphanumeric chars for fuzzy pass
    tag_alnum = "".join(ch for ch in tag_norm if ch.isalnum())

    for source in ["youtube", "coursera", "udemy"]:
        source_data = roadmap_data.get(source, {})
        if not source_data:
            continue

        # Pass 1 – exact key match (case-insensitive after normalize)
        for key, resource in source_data.items():
            if resource and _normalize_tag(key) == tag_norm:
                return resource

        # Pass 2 – alphanumeric-only match (ignores punctuation / spaces)
        for key, resource in source_data.items():
            if not resource:
                continue
            key_alnum = "".join(ch for ch in _normalize_tag(key) if ch.isalnum())
            if key_alnum == tag_alnum:
                return resource

        # Pass 3 – substring containment (one contains the other)
        for key, resource in source_data.items():
            if not resource:
                continue
            key_norm = _normalize_tag(key)
            if tag_norm in key_norm or key_norm in tag_norm:
                return resource

    return None
