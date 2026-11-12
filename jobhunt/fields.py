"""Fields: what makes the app work for one line of work (software, psychology...).

A profile picks a field (`field:` in profile.yaml, "tech" when unset). The field decides:
- the job types you can tick, which titles count as the field's at all, and which are never yours,
- where postings come from (the startup and remote-tech boards only make sense for tech),
- red flags, how postings are grouped on Applications (`tracks`),
- the words Claude and the pages use: who to contact at a company, what "the team" is, which language to write in.

Title words are matched without accents ("psicóloga" and "psicologa" both match "psicologa"), so write them
without accents here.
"""

from __future__ import annotations

# ---------- software / tech ----------

TECH_ROLES: dict[str, dict] = {
    "backend": {"label": "Backend", "words": ["backend", "back-end", "back end", "api engineer", "integration engineer",
                                               "platform engineer"],
                "bonus": {"backend": 10, "back-end": 10, "back end": 10, "platform": 3, "integration": 3, "api": 3},
                "search": "backend engineer", "wellfound": "backend-engineer"},
    "frontend": {"label": "Frontend", "words": ["frontend", "front-end", "front end", "ui engineer", "ui developer"],
                 "bonus": {"frontend": 10, "front-end": 10, "front end": 10, "ui": 3},
                 "search": "frontend developer", "wellfound": "frontend-engineer"},
    "fullstack": {"label": "Full stack", "words": ["full stack", "full-stack", "fullstack"],
                  "bonus": {"full stack": 8, "full-stack": 8, "fullstack": 8},
                  "search": "full stack developer", "wellfound": "full-stack-engineer"},
    "mobile": {"label": "Mobile", "words": ["ios", "android", "mobile", "flutter", "react native"],
               "bonus": {"mobile": 8, "ios": 8, "android": 8, "flutter": 6, "react native": 6},
               "search": "mobile developer", "wellfound": "mobile-engineer"},
    "data": {"label": "Data engineering", "words": ["data engineer", "analytics engineer", "etl", "data platform"],
             "bonus": {"data engineer": 10, "analytics engineer": 8, "data platform": 6},
             "search": "data engineer", "wellfound": "data-engineer"},
    "devops": {"label": "DevOps / SRE / cloud", "words": ["devops", "sre", "site reliability", "infrastructure",
                                                         "cloud engineer", "platform engineer"],
               "bonus": {"devops": 10, "sre": 10, "site reliability": 10, "infrastructure": 6, "cloud": 4},
               "search": "devops engineer", "wellfound": "devops-engineer"},
    "ml": {"label": "Machine learning / AI", "words": ["machine learning", "ml engineer", "ai engineer", "mlops",
                                                       "data scientist", "research"],
           "bonus": {"machine learning": 10, "ml": 8, "ai": 6, "mlops": 6},
           "search": "machine learning engineer", "wellfound": "machine-learning-engineer"},
    "qa": {"label": "QA / test automation", "words": ["qa", "quality assurance", "test automation", "sdet", "tester",
                                                       "in test"],
           "bonus": {"qa": 8, "test automation": 8, "sdet": 8},
           "search": "qa automation engineer", "wellfound": "qa-engineer"},
    "embedded": {"label": "Embedded / firmware", "words": ["embedded", "firmware", "hardware"],
                 "bonus": {"embedded": 10, "firmware": 10},
                 "search": "embedded software engineer", "wellfound": "embedded-engineer"},
    "security": {"label": "Security", "words": ["security engineer", "appsec", "application security"],
                 "bonus": {"security": 8},
                 "search": "security engineer", "wellfound": "security-engineer"},
}

TECH = {
    "label": "Software / tech",
    "roles": TECH_ROLES,
    "default_roles": ["backend"],
    # A title must have one of these, or a word of a job type you ticked.
    "titles": ["software engineer", "software developer", "software development engineer", "developer", "engineer",
               "programmer"],
    "titles_required": False,  # a ticked job type's word alone ("Backend Lead") is enough
    "reject_label": "backend/dev role",
    # Never this field's jobs, whoever uses it.
    "not_titles": ["manager", "director", "head of", "vp", "vice president", "sales", "presales", "pre-sales",
                   "account", "marketing", "designer", "recruiter", "support", "consultant", "analyst", "sap",
                   "salesforce", "servicenow", "dynamics", "network engineer", "electrical", "mechanical", "civil",
                   "mainframe", "cobol", "game", "unity", "unreal", "blockchain", "web3", "solidity",
                   "working student", "werkstudent"],
    "junior_titles": ["intern", "internship", "trainee"],  # dropped once you have a year of experience
    "top_titles": ["principal", "principle", "staff", "architect"],  # dropped under 6 years
    # What sources keep from a careers board or job board before scoring (a cheap first filter, not accent-folded).
    "title_gate": r"engineer|developer|programmer|software|backend|back-end|python|django|node(?:\.?js)?|typescript|"
                  r"devops|\bsre\b|platform|full.?stack|data|integration|\bapi\b|technical lead|tech lead|"
                  r"desenvolvedor|programador|engenheiro|entwickler",
    "sources": ["linkedin", "ats", "resolve", "wellfound", "yc", "landingjobs", "remotive", "remoteok", "arbeitnow",
                "himalayas", "hn"],
    "seed_companies": True,
    "remote_default": True,
    "red_flags": [
        {"pattern": r"\b(for|with) (one of )?our clients?\b|\b(on behalf of|for) an? (leading |global |major |"
                    r"international )?client\b|nearshore|near-shore|outsourcing|staff augmentation|body.?shop|"
                    r"allocated to (a|our) client|client projects?\b",
         "points": 15, "reason": "consultancy / outsourcing"},
        {"pattern": r"\bsecurity clearance\b", "points": 40, "reason": "security clearance"},
        {"pattern": r"\b(?:us|u\.s\.) (?:citizens?|persons?)\b", "points": 40, "reason": "US citizens only"},
    ],
    # Applications are grouped by these (the `stack` column): which terms the title + description mention.
    "tracks": {"python": ["python", "django", "fastapi", "flask"],
               "node": ["typescript", "node", "nodejs", "nestjs", "express.js", "expressjs"]},
    "track_scope": "text",
    "track_mixed": "both",  # more than one track mentioned
    "track_labels": {"python": "Python", "node": "Node / TypeScript", "both": "Python + Node"},
    "track_heading": "stack",
    "default_language": "en",
    "company_kinds": {"non-tech": "in-house tech", "tech": "tech company", "agency": "agency / consultancy"},
    "highlight_kind": "non-tech",  # the kind worth a pill on lists: a non-tech business with its own dev team
    "words": {
        "roles": "engineering roles",
        "roles_short": "eng roles",
        "team": "tech team",
        "company_intro": "people at a company that has an in-house tech team",
        "research_focus": "Evidence of a real in-house dev team: engineering blog, GitHub org, tech talks, number of "
                          "eng roles, stack.",
        "research_people": "CTO / VP or Head of Engineering / Engineering managers (ideally for {roles_wanted}, "
                           "ideally in {where}) / technical recruiters or talent acquisition for tech",
        "research_types": '"tech" | "non-tech with in-house dev team" | "agency/consultancy" | "unknown"',
        "research_type_map": {"tech": "tech", "non-tech with in-house dev team": "non-tech",
                              "agency/consultancy": "agency"},
        "evidence_label": "Dev team evidence",
        "focus_label": "Stack",
        "research_blurb": "Claude searches the web for their tech team, stack, the people who lead it and recruit "
                          "for it, and recent news to mention. Takes 1–3 minutes.",
        "manager": "the engineering manager or tech lead",
        "default_person": "the CTO / Head of Engineering",
        "person_example": "Ana Silva, Engineering Manager",
        "assess_note": "If the company is a startup, weigh ownership and breadth (things they built or ran end to "
                       "end) as strengths; startups often care less about years and titles.",
        "gaps": "years, language, stack, location, visa",
        "outreach_note": "If it is a startup or small team, lead with ownership and range: the things in the CV and "
                         "story they built, shipped or ran end to end. Founders and early CTOs care about \"can this "
                         "person own things end to end\", not titles.",
        "cv_must_have": "1-2 main languages or frameworks a posting should mention to be worth their time",
        "cv_avoid": "languages/stacks common in their field that they do NOT work with, so titles naming them are "
                    "dropped, e.g. java, .net, c#, php, ruby, go, rust, scala, kotlin, swift",
        "cv_searches": "4-6 job-board searches for the roles they'd apply for, e.g. 'python backend', "
                       "'django developer'",
        "cv_skills": 'Use plain lowercase names job postings would use ("postgres", "react", "aws", "ci/cd"). '
                     "15-18 for their main language/framework, 6-10 for things they use often, 2-5 for familiar.",
        "ph_searches": "python backend\ndjango developer",
        "ph_skills": "python: 18\ndjango: 8\npostgres: 5",
        "ph_must": "python",
        "ph_avoid": "java, php, .net",
        "ph_experience": "e.g. 3 years of Python, but on data tooling, not web backend",
        "avoid_hint": "tech you don't want to work in",
        "skills_hint": "15–18 for your main language, 6–10 for what you use often, 2–5 for familiar.",
    },
    "show_github": True,
}

# ---------- psychology ----------

PSY_ROLES: dict[str, dict] = {
    "clinical": {"label": "Clinical and health",
                 "words": ["clinico", "clinica", "clinical", "saude", "saude mental", "mental health", "psicoterapeuta",
                           "psicoterapia", "psychotherapist", "hospital", "hospitalar", "health"],
                 "bonus": {"clinico": 8, "clinica": 8, "clinical": 8, "saude": 6, "psicoterapia": 6,
                           "psicoterapeuta": 6},
                 "search": "psicólogo clínico"},
    "educational": {"label": "Education / school",
                    "words": ["educacional", "educacao", "escolar", "escola", "escolas", "agrupamento", "spo",
                              "orientacao vocacional", "educational", "school"],
                    "bonus": {"educacional": 8, "educacao": 8, "escolar": 8, "school": 6},
                    "search": "psicólogo educacional"},
    "organisational": {"label": "Work and organisations / HR",
                       "words": ["organizacional", "organizacoes", "psicologia do trabalho", "recursos humanos", "rh",
                                 "recrutamento e selecao", "talent", "organizational", "occupational", "hr"],
                       "bonus": {"organizacional": 8, "recursos humanos": 6, "recrutamento e selecao": 4,
                                 "organizational": 8},
                       "search": "psicólogo organizacional"},
    "social": {"label": "Social and community",
               "words": ["social", "comunitario", "comunitaria", "comunidade", "intervencao social", "ipss", "cpcj",
                         "familia", "familias", "community"],
               "bonus": {"social": 6, "comunitaria": 6, "comunitario": 6, "intervencao social": 6},
               "search": "psicólogo social"},
    "child": {"label": "Childhood and development",
              "words": ["infantil", "infancia", "crianca", "criancas", "pediatria", "pediatrico", "intervencao precoce",
                        "desenvolvimento", "child", "children"],
              "bonus": {"infantil": 6, "intervencao precoce": 6, "infancia": 6, "child": 6},
              "search": "psicólogo infantil"},
    "neuro": {"label": "Neuropsychology",
              "words": ["neuropsicologo", "neuropsicologa", "neuropsicologia", "neuropsychologist", "neuropsychology",
                        "reabilitacao cognitiva"],
              "bonus": {"neuropsicologia": 8, "neuropsicologo": 8, "neuropsicologa": 8, "reabilitacao cognitiva": 6},
              "search": "neuropsicólogo"},
    "forensic": {"label": "Forensic and justice",
                 "words": ["forense", "forensic", "justica", "prisional", "reinsercao"],
                 "bonus": {"forense": 8, "justica": 6, "prisional": 6},
                 "search": "psicólogo forense"},
}

PSYCHOLOGY = {
    "label": "Psychology",
    "roles": PSY_ROLES,
    "default_roles": ["clinical", "educational", "organisational", "social"],
    "titles": ["psicologo", "psicologa", "psicologos", "psicologas", "psicologo(a)", "psicologia", "psychologist",
               "psychologists", "psychology", "psicoterapeuta", "psychotherapist", "neuropsicologo", "neuropsicologa",
               "neuropsicologia", "neuropsychologist"],
    "titles_required": True,  # "Assistente Social" has a social word but isn't a psychologist's job
    "reject_label": "psychology role",
    "not_titles": ["psicomotricista", "psicomotricidade", "terapeuta da fala", "terapeuta ocupacional",
                   "fisioterapeuta", "enfermeiro", "enfermeira", "comercial", "vendedor", "vendedora", "sales",
                   "delegado de informacao medica", "professor de psicologia", "docente"],
    "junior_titles": ["estagio", "estagios", "estagiario", "estagiaria", "estagiario(a)", "ano profissional junior",
                      "intern", "internship", "trainee"],
    "top_titles": ["coordenador", "coordenadora", "coordenacao", "diretor", "diretora", "director", "directora",
                   "head of"],
    "title_gate": r"psic[oó]log|psychol|psicoterap|psychotherap|neuropsic",
    "sources": ["linkedin", "netempregos", "ats"],
    "seed_companies": False,
    "remote_default": False,
    "red_flags": [
        {"pattern": r"\bvoluntari[oa]s?\b|\bvoluntariado\b|nao remunerad|sem remuneracao|\bunpaid\b|"
                    r"\bvolunteer\b",
         "points": 40, "reason": "unpaid / volunteer"},
        {"pattern": r"recibos? verdes?|prestacao de servicos|trabalhador(a)? independente|\bfreelancer?\b",
         "points": 5, "reason": "recibos verdes (no contract)"},
        {"pattern": r"percentagem (das|por|de cada|sobre a?s?) ?consultas?|\b\d{2} ?% (das|por|de cada) consultas?|"
                    r"comissao por consulta|valor por consulta",
         "points": 5, "reason": "paid per consultation"},
    ],
    "tracks": {k: v["words"] for k, v in PSY_ROLES.items()},
    "track_scope": "title_then_text",  # the title says the area; the description only when the title doesn't
    "track_mixed": None,
    "track_labels": {k: v["label"] for k, v in PSY_ROLES.items()},
    "track_heading": "area",
    "default_language": "pt",
    "company_kinds": {"clinic": "clinic / practice", "health": "hospital / health service", "school": "school / education",
                      "social": "NGO / IPSS / social", "company": "company (HR)", "public": "public sector"},
    "highlight_kind": None,
    "words": {
        "roles": "psychology roles",
        "roles_short": "psychology roles",
        "team": "psychology team",
        "company_intro": "people at an organisation that employs psychologists (a clinic, hospital, school, IPSS / NGO, "
                         "company or public service)",
        "research_focus": "What psychology work they do: services (consultas, avaliação, intervenção, formação), the "
                          "populations they serve, roughly how many psychologists work there, specialties and approaches, "
                          "and whether they hire on contract or recibos verdes when that's public.",
        "research_people": "clinical or technical director (diretor/a clínico/a, diretor/a técnico/a) / coordinator of "
                           "the psychology team / the founder of a small practice / HR or recruitment (ideally in "
                           "{where})",
        "research_types": '"clinic / private practice" | "hospital / health service" | "school / education" | '
                          '"NGO / IPSS / social" | "company (HR / organisational)" | "public sector" | "unknown"',
        "research_type_map": {"clinic / private practice": "clinic", "hospital / health service": "health",
                              "school / education": "school", "NGO / IPSS / social": "social",
                              "company (HR / organisational)": "company", "public sector": "public"},
        "evidence_label": "Psychology work there",
        "focus_label": "Areas and approaches",
        "research_blurb": "Claude searches the web for the psychology work they do, who leads it and hires for it, and "
                          "recent news to mention. Takes 1–3 minutes.",
        "manager": "the clinical / technical director or the coordinator of the psychology team",
        "default_person": "the clinical or technical director",
        "person_example": "Ana Silva, Diretora Clínica",
        "assess_note": "Weigh the match of specialty and population (children, adults, older people, families...), "
                       "the type of contract (contrato de trabalho vs recibos verdes, pay per consultation) and any "
                       "requirement they may not meet: OPP membership or a specialty (especialidade / especialidade "
                       "avançada), a driving licence, a specific therapy training (e.g. CBT, EMDR, systemic).",
        "gaps": "years, specialty, OPP requirements, language, location, contract type",
        "outreach_note": "For a small clinic or practice, write to the person who runs it: be specific about the "
                         "population and approach that match theirs.",
        "cv_must_have": "leave empty unless the CV shows a narrow specialty that every posting should mention",
        "cv_avoid": "title words for kinds of psychology work they clearly do NOT want, if the CV makes that obvious; "
                    "usually empty",
        "cv_searches": "4-6 job-board searches in Portuguese for the roles they'd apply for, e.g. 'psicólogo', "
                       "'psicóloga clínica', 'psicólogo educacional'",
        "cv_skills": "Use plain lowercase words Portuguese postings would use, without accents (\"avaliacao "
                     "psicologica\", \"psicoterapia\", \"terapia cognitivo-comportamental\", \"intervencao precoce\", "
                     "\"criancas\", \"adolescentes\", \"recrutamento\", \"opp\"). 12-18 for their main area, "
                     "6-10 for what they do often, 2-5 for familiar.",
        "ph_searches": "psicólogo\npsicóloga\npsicologia clínica",
        "ph_skills": "avaliacao psicologica: 12\npsicoterapia: 10\ncriancas: 6",
        "ph_must": "",
        "ph_avoid": "",
        "ph_experience": "e.g. 2 years of clinical work since the OPP internship, plus volunteering at an IPSS",
        "avoid_hint": "kinds of work you don't want",
        "skills_hint": "12–18 for your main area, 6–10 for what you do often, 2–5 for familiar. Write them without "
                       "accents; postings are matched without accents.",
    },
    "show_github": False,
}

FIELDS: dict[str, dict] = {"tech": TECH, "psychology": PSYCHOLOGY}


def get(name: str | None) -> dict:
    return FIELDS.get(name or "tech", TECH)
