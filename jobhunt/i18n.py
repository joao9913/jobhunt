"""Interface text in English and European Portuguese (pt-PT).

Pages write English and wrap it in `_()` (web.py); in Portuguese, `t()` looks it up in PT and falls back to the
English text when there's no entry. `reason()` translates the score reasons scoring.py writes ("Lisbon area",
"asks 3+ years, you have 1: -24"...). What Claude writes is in your language already (llm.output_language).
The fetch log's detail lines stay in English.
"""

from __future__ import annotations

import re

PT: dict[str, str] = {
    # ---- navigation, header, login ----
    "Main": "Principal",
    "Today": "Hoje",
    "Jobs": "Ofertas",
    "Applications": "Candidaturas",
    "Companies": "Empresas",
    "Profile": "Perfil",
    "See what the fetch is doing": "Ver o que a pesquisa está a fazer",
    "Cancelling, finishing the current request": "A cancelar, a terminar o pedido atual",
    "Cancelling, finishing the current request →": "A cancelar, a terminar o pedido atual →",
    "Fetching: {step}": "A pesquisar: {step}",
    "Fetching: {step} →": "A pesquisar: {step} →",
    "Last fetch": "Última pesquisa",
    "{n} Claude task running": "{n} tarefa do Claude em curso",
    "{n} Claude tasks running": "{n} tarefas do Claude em curso",
    "Cancelling…": "A cancelar…",
    "Cancel": "Cancelar",
    "Search every source for new postings": "Procurar ofertas novas em todas as fontes",
    "Search": "Pesquisar",
    "Log out": "Terminar sessão",
    "Log in": "Iniciar sessão",
    "Logging in…": "A entrar…",
    "Your own job search: your profile, postings and applications.":
        "A sua procura de emprego: o seu perfil, ofertas e candidaturas.",
    "Wrong username or password.": "Utilizador ou palavra-passe errados.",
    "Username": "Utilizador",
    "Password": "Palavra-passe",
    "No account? Ask whoever runs this computer to add one with": "Sem conta? Peça a quem gere este computador que a crie com",
    "<b>Set up your profile first.</b> Postings are ranked against it.":
        "<b>Comece por preencher o perfil.</b> As ofertas são ordenadas com base nele.",
    "Upload your CV or fill it in →": "Carregue o CV ou preencha-o →",
    "Fetch failed: see why →": "A pesquisa falhou: ver porquê →",
    "<b>Net-Empregos is asking for a captcha</b> (since {since}), so searches skip it until {until}. To get it back "
    "sooner, open it, solve the captcha yourself, then retry.":
        "<b>O Net-Empregos está a pedir um captcha</b> (desde as {since}), por isso as pesquisas saltam-no até "
        "{until}. Para o recuperar mais cedo, abra-o, resolva o captcha e tente de novo.",
    "Open Net-Empregos ↗": "Abrir o Net-Empregos ↗",
    "Retry Net-Empregos": "Tentar o Net-Empregos de novo",
    "Fetch cancelled: reload to see what it found": "Pesquisa cancelada: recarregue para ver o que encontrou",
    "Fetch finished: reload to see new postings": "Pesquisa terminada: recarregue para ver as ofertas novas",
    "Copied": "Copiado",
    "Copy": "Copiar",
    "Save changes": "Guardar alterações",
    "Saved": "Guardado",
    "Save": "Guardar",
    # ---- shared bits ----
    "Status": "Estado",
    "Filter": "Filtrar",
    "Clear": "Limpar",
    "clear": "limpar",
    "clear filters": "limpar filtros",
    "Role": "Função",
    "Location": "Local",
    "Notes": "Notas",
    "remote": "remoto",
    "Remote": "Remoto",
    "Remote:": "Remoto:",
    "Kind": "Tipo",
    "Company": "Empresa",
    "Country": "País",
    "Why": "Porquê",
    "Level": "Nível",
    "Sort": "Ordenar",
    "Back": "Voltar",
    "Fit score out of 100": "Pontuação de adequação (0 a 100)",
    "chars": "caracteres",
    "Claude is working on this… the page refreshes by itself.": "O Claude está a tratar disto… a página atualiza sozinha.",
    "Triage": "Triagem",
    "Application": "Candidatura",
    "Close as": "Fechar como",
    "applied here ×{n}": "já me candidatei aqui ×{n}",
    "Doesn't say if they hire from {country}: ask the recruiter before applying":
        "Não diz se contratam quem vive em {country}: pergunte ao recrutador antes de se candidatar",
    "your country": "o seu país",
    "check remote": "confirmar remoto",
    "← Previous": "← Anterior",
    "Next →": "Seguinte →",
    "{a}–{b} of {n}": "{a}–{b} de {n}",
    "all levels": "todos os níveis",
    "junior–mid (up to 2 years)": "júnior–intermédio (até 2 anos)",
    "senior (more than 2 years)": "sénior (mais de 2 anos)",
    "level not stated": "nível não indicado",
    "junior–mid": "júnior–intermédio",
    "senior": "sénior",
    "startup": "startup",
    "{n} people": "{n} pessoas",
    "source": "fonte",
    "Drafting…": "A redigir…",
    "Draft": "Redigir",
    "Redraft": "Redigir de novo",
    "Subject": "Assunto",
    "Text": "Texto",
    "Message": "Mensagem",
    "Seen": "Vista",
    "Not interested": "Não me interessa",
    # ---- statuses (db.py) ----
    "new": "nova",
    "interested": "interessa-me",
    "not interested": "não me interessa",
    "closed by employer": "fechada pelo empregador",
    "applied": "candidatei-me",
    "interviewing": "em entrevistas",
    "offer": "proposta",
    "rejected by them": "rejeitada por eles",
    "I withdrew": "desisti",
    "no reply": "sem resposta",
    "offer accepted": "proposta aceite",
    "offer declined": "proposta recusada",
    "all": "todas",
    "target": "alvo",
    "contacted": "contactada",
    "replied": "respondeu",
    "ignore": "ignorar",
    # Claude's verdicts
    "apply": "candidatar",
    "maybe": "talvez",
    "skip": "passar",
    # ---- Today ----
    "New postings": "Ofertas novas",
    "New companies": "Empresas novas",
    "Interested": "Interessa-me",
    "Ongoing applications": "Candidaturas em curso",
    "Messages sent this week": "Mensagens enviadas esta semana",
    "Follow-ups due": "Seguimentos para fazer",
    "sent {date}": "enviada a {date}",
    "due {date}": "para {date}",
    "Replied": "Respondeu",
    "Give up": "Desistir",
    "Mark all {n} shown as seen": "Marcar as {n} visíveis como vistas",
    "Mark all {n} as seen": "Marcar todas ({n}) como vistas",
    "Hide without a status": "Esconder sem lhe dar um estado",
    "No new postings at this level. Pick another level above.": "Não há ofertas novas neste nível. Escolha outro acima.",
    "You're up to date. New postings appear here after the next fetch.":
        "Está tudo visto. As ofertas novas aparecem aqui depois da próxima pesquisa.",
    "Companies with roles that fit you. Set <b>target</b> to keep one on your list, or <b>ignore</b> to hide it and its jobs for good.":
        "Empresas com ofertas que lhe servem. Escolha <b>alvo</b> para a manter na sua lista, ou <b>ignorar</b> para a "
        "esconder, a ela e às suas ofertas, de vez.",
    "{fit} fitting · {all} {roles}": "{fit} adequadas · {all} {roles}",
    "No new companies since your last review.": "Não há empresas novas desde a última vez.",
    "Targets not contacted yet": "Alvos ainda por contactar",
    "researched": "pesquisada",
    "not researched": "por pesquisar",
    "Set companies to <b>target</b> to keep them here until you contact them.":
        "Marque empresas como <b>alvo</b> para ficarem aqui até as contactar.",
    "best score first": "melhor pontuação primeiro",
    "newest first": "mais recentes primeiro",
    "clear about remote first": "claras sobre remoto primeiro",
    # ---- Jobs ----
    "applied →": "candidaturas →",
    "search title, company, text": "procurar título, empresa, texto",
    "remote + on-site": "remoto + presencial",
    "remote only": "só remoto",
    "on-site / hybrid only": "só presencial / híbrido",
    "Remote check": "Confirmação de remoto",
    "from {city}: confirmed + to check": "a partir de {city}: confirmadas + a confirmar",
    "from {city}: confirmed only": "a partir de {city}: só confirmadas",
    "from {city}: to check only": "a partir de {city}: só a confirmar",
    "all companies": "todas as empresas",
    "startups only": "só startups",
    "all countries": "todos os países",
    "min score": "pontuação mínima",
    "Mark as not interested": "Marcar como não me interessa",
    "No postings match. Try a lower min score or another tab.":
        "Nenhuma oferta corresponde. Experimente uma pontuação mínima mais baixa ou outro separador.",
    # ---- a job ----
    "posted {date}": "publicada a {date}",
    "You applied: move it to Applications": "Candidatou-se: passa para Candidaturas",
    "Applied": "Candidatei-me",
    "Doesn't fit: hide it from new postings": "Não serve: esconder das ofertas novas",
    "Open posting ↗": "Abrir oferta ↗",
    "<b>Check remote before applying.</b> This posting doesn't say whether they hire someone living in {city}. Ask the recruiter first, for example: <i>“I'm based in {city} and would be glad to work remotely as a contractor or through an EOR. Is that an option for this role?”</i>":
        "<b>Confirme o remoto antes de se candidatar.</b> Esta oferta não diz se contratam quem vive em {city}. "
        "Pergunte primeiro ao recrutador, por exemplo: <i>«Vivo em {city} e teria todo o gosto em trabalhar "
        "remotamente, como independente ou através de um EOR. É uma opção para esta função?»</i>",
    "Claude's take": "A opinião do Claude",
    "Assessing…": "A avaliar…",
    "Re-assess": "Avaliar de novo",
    "Assess fit": "Avaliar adequação",
    "Why you fit": "Porque lhe serve",
    "Gaps": "Lacunas",
    "Lead with": "Comece por",
    "Not assessed yet. Takes ~20 seconds.": "Ainda não avaliada. Demora uns 20 segundos.",
    "Messages": "Mensagens",
    "Redraft all": "Redigir tudo de novo",
    "Draft all": "Redigir tudo",
    "Draft only what you need. You edit and send them yourself.":
        "Redija só o que precisa. É a própria pessoa que edita e envia.",
    "Cover note": "Carta de apresentação",
    "LinkedIn note to the recruiter": "Nota no LinkedIn para o recrutador",
    "Message to the hiring manager": "Mensagem para quem contrata",
    "Find the people on the <a href=\"/companies/{id}\">{name} page</a>.":
        "Encontre as pessoas na <a href=\"/companies/{id}\">página da {name}</a>.",
    "Description": "Descrição",
    "No description fetched for this posting. Open the posting to read it.":
        "Não foi possível obter a descrição desta oferta. Abra a oferta para a ler.",
    "Salary": "Salário",
    "Read from the description: check it there": "Lido na descrição: confirme lá",
    "From the job board": "Indicado pelo site de emprego",
    "Not stated in the posting": "Não indicado na oferta",
    "Score breakdown": "Como foi pontuada",
    "Source:": "Fonte:",
    # ---- Applications ----
    "ongoing": "em curso",
    "archive": "arquivo",
    "search role, company, location, notes": "procurar função, empresa, local, notas",
    "all ongoing": "todas em curso",
    "all archived": "todas arquivadas",
    "Ongoing": "Em curso",
    "Archive": "Arquivo",
    "The day you applied": "O dia em que se candidatou",
    "applied from": "candidaturas de",
    "to": "a",
    "Stack": "Stack",
    "Area": "Área",
    "By stack": "Por stack",
    "By area": "Por área",
    "every application so far, each posting once; “no reply” after {n} days without an answer":
        "todas as candidaturas até hoje, cada oferta uma vez; «sem resposta» ao fim de {n} dias sem resposta",
    "Waiting": "À espera",
    "Interview": "Entrevista",
    "Rejected": "Rejeitada",
    "No reply": "Sem resposta",
    "Reply rate": "Taxa de resposta",
    "not stated": "não indicada",
    "{a}% answered · {b}% interview": "{a}% com resposta · {b}% entrevista",
    "Closed": "Fechada",
    "No ongoing applications match these filters.": "Nenhuma candidatura em curso corresponde a estes filtros.",
    "No archived applications match these filters.": "Nenhuma candidatura arquivada corresponde a estes filtros.",
    "See {n} in the archive →": "Ver {n} no arquivo →",
    "See {n} ongoing →": "Ver {n} em curso →",
    "Nothing archived yet.": "Ainda não há nada no arquivo.",
    "No ongoing applications. Set a posting to “applied” on its page and it shows up here.":
        "Não há candidaturas em curso. Marque uma oferta como «candidatei-me» na página dela e aparece aqui.",
    # ---- Companies ----
    "all kinds": "todos os tipos",
    "startups": "startups",
    "not classified yet": "ainda sem tipo",
    "active (not ignored)": "ativas (não ignoradas)",
    "name": "nome",
    "Fitting roles": "Ofertas adequadas",
    "All {roles} (45 days)": "Todas as {roles} (45 dias)",
    "Careers board": "Página de carreiras",
    "Research": "Pesquisa",
    "No companies yet. Run a fetch.": "Ainda não há empresas. Faça uma pesquisa.",
    "{n} {roles} in the last 45 days · {fit} fit your profile": "{n} {roles} nos últimos 45 dias · {fit} servem ao seu perfil",
    "careers board:": "página de carreiras:",
    "kind: unknown": "tipo: desconhecido",
    "Researching…": "A pesquisar…",
    "Research again": "Pesquisar de novo",
    "Research with Claude": "Pesquisar com o Claude",
    "Local": "No país",
    "Things to mention": "O que mencionar",
    "Why you": "Porquê a si",
    "Careers page ↗": "Página de carreiras ↗",
    "People": "Pessoas",
    "Check each person on LinkedIn before writing; research can be out of date.":
        "Confirme cada pessoa no LinkedIn antes de escrever; a pesquisa pode estar desatualizada.",
    "Find people on LinkedIn (opens while you're logged in)": "Encontrar pessoas no LinkedIn (abre com a sua sessão)",
    "Someone else, e.g. {example}": "Outra pessoa, p. ex. {example}",
    "Draft for them": "Redigir para esta pessoa",
    "Drafts": "Rascunhos",
    "LinkedIn connection note": "Nota do pedido de ligação no LinkedIn",
    "Follow-up (a week later)": "Seguimento (uma semana depois)",
    "Open roles": "Ofertas abertas",
    "filtered:": "filtrada:",
    "No {roles} seen yet.": "Ainda não foram vistas {roles}.",
    "Log a message you sent": "Registar uma mensagem enviada",
    "Who": "Para quem",
    "Channel": "Canal",
    "Email": "Email",
    "Other": "Outro",
    "sent": "enviada a",
    "follow up on": "seguimento a",
    "What you sent (optional)": "O que enviou (opcional)",
    "Log it": "Registar",
    "History": "Histórico",
    "follow up {date}": "seguimento a {date}",
    # people searches on a company page
    "CTO / Head of Engineering": "CTO / Head of Engineering",
    "Engineering managers": "Engineering managers",
    "Tech recruiters": "Recrutadores de tecnologia",
    "Clinical / technical director": "Diretor/a clínico/a ou técnico/a",
    "Psychology coordination": "Coordenação de psicologia",
    "HR / recruitment": "RH / recrutamento",
    # ---- Fetch page and steps ----
    "Fetch": "Pesquisa",
    "Claude assessments": "Avaliações do Claude",
    "What it's doing": "O que está a fazer",
    "No log for this fetch yet. Press <b>Search</b> to watch one live.":
        "Ainda não há registo desta pesquisa. Carregue em <b>Pesquisar</b> para acompanhar uma em direto.",
    "Cancelling": "A cancelar",
    "Running": "Em curso",
    "Failed": "Falhou",
    "Cancelled": "Cancelada",
    "Finished": "Terminada",
    "Started {time}": "Começou às {time}",
    "running for {d}": "a correr há {d}",
    "took {d}": "demorou {d}",
    "{n} of {total} done": "{n} de {total} feitas",
    "Starting": "A começar",
    "Waiting for another search on this computer to finish": "À espera que outra pesquisa neste computador termine",
    "Job boards": "Sites de emprego",
    "LinkedIn (public job pages, throttled)": "LinkedIn (páginas públicas de ofertas, com pausas)",
    "Checking LinkedIn postings on your lists still take applications":
        "A confirmar se as ofertas do LinkedIn nas suas listas ainda aceitam candidaturas",
    "Scoring postings": "A pontuar ofertas",
    "Company careers boards": "Páginas de carreiras das empresas",
    "Scoring the careers-board postings": "A pontuar as ofertas das páginas de carreiras",
    "Cancelled. Scoring what was found so far": "Cancelada. A pontuar o que foi encontrado até agora",
    "Cancelled: postings found before the cancel are saved": "Cancelada: as ofertas encontradas antes estão guardadas",
    # ---- Profile ----
    "Language": "Idioma",
    "the app and everything Claude writes for you": "da aplicação e de tudo o que o Claude escreve por si",
    "Field": "Área profissional",
    "sets the job types, titles, sources and wording": "define os tipos de função, títulos, fontes e linguagem",
    "Software / tech": "Software / tecnologia",
    "Psychology": "Psicologia",
    "Your CV": "O seu CV",
    "Loaded from {name} ({n} characters). Claude reads it to judge fit and write your messages.":
        "Carregado de {name} ({n} caracteres). O Claude lê-o para avaliar a adequação e escrever as suas mensagens.",
    "No CV yet. Upload one and Claude fills in the form below for you to check.":
        "Ainda sem CV. Carregue um e o Claude preenche o formulário abaixo para o rever.",
    "Reading…": "A ler…",
    "Upload a new CV": "Carregar um CV novo",
    "Upload CV": "Carregar CV",
    "Upload a PDF, Word (.docx), HTML, Markdown or text file.": "Carregue um ficheiro PDF, Word (.docx), HTML, Markdown ou texto.",
    "Couldn't read text from that file. If it's a scanned PDF, upload a text-based PDF or a Word file.":
        "Não foi possível ler texto desse ficheiro. Se for um PDF digitalizado, carregue um PDF com texto ou um ficheiro Word.",
    "Reading your CV takes about a minute.": "Ler o CV demora cerca de um minuto.",
    "<b>Claude filled the form from your CV.</b> Check every field and fix what's off, then press <b>Save profile</b>. Nothing is used until you save.":
        "<b>O Claude preencheu o formulário a partir do seu CV.</b> Reveja cada campo, corrija o que estiver mal e "
        "carregue em <b>Guardar perfil</b>. Nada é usado até guardar.",
    "Discard suggestions": "Descartar sugestões",
    "Saved. Re-ranking every posting against your new profile (about 20 seconds)…":
        "Guardado. A reordenar todas as ofertas com o novo perfil (cerca de 20 segundos)…",
    "Saved. Postings are ranked with your new profile; the next <b>Search</b> uses it too.":
        "Guardado. As ofertas estão ordenadas com o novo perfil; a próxima <b>Pesquisa</b> também o usa.",
    "Welcome. Upload your CV above, or fill this in by hand, then save. Your profile and CV stay on this computer, in your own folder, which git ignores.":
        "Bem-vindo/a. Carregue o CV acima, ou preencha à mão, e guarde. O perfil e o CV ficam neste computador, "
        "na sua própria pasta, que o git ignora.",
    "What you're looking for": "O que procura",
    "Job types": "Tipos de função",
    "postings only for the types you don't tick are hidden": "as ofertas só dos tipos que não marcar ficam escondidas",
    "Searches": "Pesquisas",
    "one per line, used on LinkedIn and the job boards": "uma por linha, usadas no LinkedIn e nos sites de emprego",
    "Experience in these roles (years)": "Experiência nestas funções (anos)",
    "postings asking for more rank lower": "ofertas que pedem mais ficam mais abaixo",
    "Count real jobs in this field. Different experience (other field, freelance, studies) goes in the note.":
        "Conte empregos reais nesta área. Outra experiência (outra área, independente, estudos) vai na nota.",
    "Seniority": "Senioridade",
    "by the level badge on each posting (title words first, then the years it asks for)":
        "pelo nível de cada oferta (primeiro as palavras do título, depois os anos que pede)",
    "Any level": "Qualquer nível",
    "Hide senior postings": "Esconder ofertas séniores",
    "Only postings that say junior–mid (also hides the ones that don't say)":
        "Só ofertas que dizem júnior–intermédio (esconde também as que não dizem)",
    "Skills": "Competências",
    "Skills and points": "Competências e pontos",
    "one per line; a posting that mentions it gets the points": "uma por linha; uma oferta que a mencione recebe os pontos",
    "Must mention one of": "Tem de mencionar uma de",
    "comma-separated; postings without any lose points": "separadas por vírgulas; ofertas sem nenhuma perdem pontos",
    "Hide titles with": "Esconder títulos com",
    "Languages you speak": "Línguas que fala",
    "postings needing others lose points": "ofertas que pedem outras perdem pontos",
    "Never show these companies": "Nunca mostrar estas empresas",
    "e.g. your current employer": "p. ex. o seu empregador atual",
    "Minimum score to show a posting": "Pontuação mínima para mostrar uma oferta",
    "Where you work from": "De onde trabalha",
    "City": "Cidade",
    "choose…": "escolher…",
    "Towns that count as your city": "Localidades que contam como a sua cidade",
    "comma-separated": "separadas por vírgulas",
    "Other cities you'd go to on-site": "Outras cidades onde iria trabalhar presencialmente",
    "Open to remote roles at companies elsewhere in Europe": "Aberto/a a trabalho remoto para empresas noutros países da Europa",
    "About you": "Sobre si",
    "used by Claude for assessments and the messages it drafts": "usado pelo Claude nas avaliações e nas mensagens que redige",
    "Name": "Nome",
    "Your story": "A sua história",
    "a few sentences in your own words; drafts never claim anything that isn't here or in the CV":
        "algumas frases suas; os rascunhos nunca afirmam nada que não esteja aqui ou no CV",
    "Save profile": "Guardar perfil",
    # ---- field words (fields.py) ----
    "engineering roles": "ofertas de engenharia",
    "eng roles": "ofertas de engenharia",
    "psychology roles": "ofertas de psicologia",
    "Dev team evidence": "Sinais de equipa de desenvolvimento",
    "Psychology work there": "Trabalho de psicologia lá",
    "Areas and approaches": "Áreas e abordagens",
    "Claude searches the web for their tech team, stack, the people who lead it and recruit for it, and recent news to mention. Takes 1–3 minutes.":
        "O Claude procura na web a equipa técnica, a stack, quem a lidera e recruta, e notícias recentes para "
        "mencionar. Demora 1–3 minutos.",
    "Claude searches the web for the psychology work they do, who leads it and hires for it, and recent news to mention. Takes 1–3 minutes.":
        "O Claude procura na web o trabalho de psicologia que fazem, quem o coordena e contrata, e notícias "
        "recentes para mencionar. Demora 1–3 minutos.",
    "tech you don't want to work in": "tecnologias com que não quer trabalhar",
    "kinds of work you don't want": "tipos de trabalho que não quer",
    "15–18 for your main language, 6–10 for what you use often, 2–5 for familiar.":
        "15–18 para a sua linguagem principal, 6–10 para o que usa muito, 2–5 para o que conhece.",
    "12–18 for your main area, 6–10 for what you do often, 2–5 for familiar. Write them without accents; postings are matched without accents.":
        "12–18 para a sua área principal, 6–10 para o que faz muitas vezes, 2–5 para o que conhece. Escreva sem "
        "acentos; as ofertas são comparadas sem acentos.",
    "e.g. 3 years of Python, but on data tooling, not web backend":
        "p. ex. 3 anos de Python, mas em ferramentas de dados, não em backend web",
    "e.g. 2 years of clinical work since the OPP internship, plus volunteering at an IPSS":
        "p. ex. 2 anos de prática clínica desde o estágio da OPP, mais voluntariado numa IPSS",
    # company kinds
    "in-house tech": "tecnologia interna",
    "tech company": "empresa de tecnologia",
    "agency / consultancy": "agência / consultora",
    "clinic / practice": "clínica / consultório",
    "hospital / health service": "hospital / serviço de saúde",
    "school / education": "escola / educação",
    "NGO / IPSS / social": "ONG / IPSS / social",
    "company (HR)": "empresa (RH)",
    "public sector": "setor público",
    # job types and tracks
    "Backend": "Backend", "Frontend": "Frontend", "Full stack": "Full stack", "Mobile": "Mobile",
    "Data engineering": "Engenharia de dados", "DevOps / SRE / cloud": "DevOps / SRE / cloud",
    "Machine learning / AI": "Machine learning / IA", "QA / test automation": "QA / automação de testes",
    "Embedded / firmware": "Sistemas embebidos / firmware", "Security": "Segurança",
    "Python": "Python", "Node / TypeScript": "Node / TypeScript", "Python + Node": "Python + Node",
    "Clinical and health": "Clínica e da saúde",
    "Education / school": "Educação",
    "Work and organisations / HR": "Trabalho e organizações / RH",
    "Social and community": "Social e comunitária",
    "Childhood and development": "Infância e desenvolvimento",
    "Neuropsychology": "Neuropsicologia",
    "Forensic and justice": "Forense e justiça",
    # countries that show up most in the filter
    "Portugal": "Portugal", "Spain": "Espanha", "France": "França", "Germany": "Alemanha",
    "United Kingdom": "Reino Unido", "Ireland": "Irlanda", "Netherlands": "Países Baixos", "Belgium": "Bélgica",
    "Switzerland": "Suíça", "Italy": "Itália", "Poland": "Polónia", "United States": "Estados Unidos",
    "Remote (no country)": "Remoto (sem país)", "Unknown": "Desconhecido",
}


# Fetch steps with numbers in them.
_STEPS = [(re.compile(p), r) for p, r in [
    (r"^Looking for careers boards \(up to (\d+) companies\)$", r"A procurar páginas de carreiras (até \1 empresas)"),
    (r"^Claude assessing new postings \(up to (\d+)\)$", r"O Claude está a avaliar as ofertas novas (até \1)"),
    (r"^Done: (\d+) postings checked, (\d+) new fitting postings, (\d+) new companies, (\d+) assessed$",
     r"Feito: \1 ofertas vistas, \2 novas adequadas, \3 empresas novas, \4 avaliadas"),
]]


def t(text: str, lang: str) -> str:
    if lang != "pt" or not text:
        return text
    if text in PT:
        return PT[text]
    for rx, repl in _STEPS:
        if rx.match(text):
            return rx.sub(repl, text)
    return text


# Score reasons (scoring.py) -> pt-PT. Patterns over the English text; the first match wins.
_REASONS: list[tuple[re.Pattern, str]] = [(re.compile(p), r) for p, r in [
    (r"^(.+) area$", r"zona de \1"),
    (r"^(.+) remote$", r"\1, remoto"),
    (r"^(.+) \(city not given\)$", r"\1 (cidade não indicada)"),
    (r"^acceptable city$", "cidade aceitável"),
    (r"^remote EU-friendly$", "remoto, aberto à UE"),
    (r"^remote \(region unclear\)$", "remoto (região pouco clara)"),
    (r"^location unknown$", "local desconhecido"),
    (r"^remote, listed in (.+) \(check they hire from (.+)\)$", r"remoto, listada em \1 (confirme se contratam em \2)"),
    (r"^(.*); mentions hybrid \(check it can be fully remote\)$", r"\1; menciona híbrido (confirme se pode ser 100% remoto)"),
    (r"^title \+(.+)$", r"título +\1"),
    (r"^title -(.+)$", r"título -\1"),
    (r"^title: (.+)$", r"título: \1"),
    (r"^skills: (.+)$", r"competências: \1"),
    (r"^no (.+) mentioned$", r"não menciona \1"),
    (r"^no description yet$", "ainda sem descrição"),
    (r"^asks (\d+)\+ years, you have (\d+): (.+)$", r"pede \1+ anos, tem \2: \3"),
    (r"^asks (\d+)-(\d+) years, you have (\d+): (.+)$", r"pede \1-\2 anos, tem \3: \4"),
    (r"^asks (\d+) years, you have (\d+): (.+)$", r"pede \1 anos, tem \2: \3"),
    (r"^asks (\d+)\+ years$", r"pede \1+ anos"),
    (r"^asks (\d+)-(\d+) years$", r"pede \1-\2 anos"),
    (r"^asks (\d+) years$", r"pede \1 anos"),
    (r"^title: (\S+), asks (.+)$", r"título: \1, pede \2"),
    (r"^-consultancy / outsourcing$", "-consultora / outsourcing"),
    (r"^-security clearance$", "-credenciação de segurança"),
    (r"^-US citizens only$", "-só cidadãos dos EUA"),
    (r"^-needs another language$", "-pede outra língua"),
    (r"^-unpaid / volunteer$", "-não remunerado / voluntariado"),
    (r"^-recibos verdes \(no contract\)$", "-recibos verdes (sem contrato)"),
    (r"^-paid per consultation$", "-pago à consulta"),
    (r"^-only for current public employees$", "-só para quem já tem vínculo público"),
    (r"^excluded company$", "empresa excluída"),
    (r"^title not a (.+)$", r"o título não é de \1"),
    (r"^senior \((.+)\)$", r"sénior (\1)"),
    (r"^level not stated$", "nível não indicado"),
    (r"^on-site/hybrid outside (.+?): (.+)$", r"presencial/híbrido fora de \1: \2"),
    (r"^on-site: (.+)$", r"presencial: \1"),
    (r"^hybrid / office days in (.+)$", r"híbrido / dias no escritório em \1"),
    (r"^remote abroad \(you only want local roles\)$", "remoto no estrangeiro (só quer funções locais)"),
    (r"^remote, but asks you to live in another country$", "remoto, mas pede que viva noutro país"),
    (r"^remote, restricted: (.+)$", r"remoto, restrito: \1"),
    (r"^remote, but only US/Americas/Asia$", "remoto, mas só EUA/Américas/Ásia"),
    (r"^remote in (.+), posting in (\w+): local hires only$", r"remoto em \1, oferta em \2: só contratações locais"),
    (r"^remote in (.+), asks you to live there$", r"remoto em \1, pede que viva lá"),
]]
_ROLE_NAMES = {"backend/dev role": "backend/desenvolvimento", "psychology role": "psicologia"}


def reason(text: str, lang: str) -> str:
    if lang != "pt" or not text:
        return text
    for rx, repl in _REASONS:
        if rx.match(text):
            out = rx.sub(repl, text)
            for en, pt in _ROLE_NAMES.items():
                out = out.replace(en, pt)
            return out.replace("asks", "pede").replace("years", "anos")
    return text
