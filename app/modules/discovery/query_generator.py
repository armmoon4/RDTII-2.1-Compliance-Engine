"""
Module 1 — Query Generator
Converts (country, indicator_id) → ordered list of web search queries.

Implements the 7-template formula from RDTII spec §6.5.4.
Hardcoded INDICATOR_QUESTION_BANK covers all 61 RDTII 2.1 indicators.
COUNTRY_PORTAL_REGISTRY covers Malaysia, Singapore, Australia.

Supports LLM-enhanced query generation: when enabled, an LLM generates
targeted, country-aware search queries that find specific law names and
section numbers instead of relying solely on generic keyword templates.
"""
import logging
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class IndicatorMeta:
    indicator_id: str
    title: str
    research_question: str
    keyword_seeds: list[str]


@dataclass
class CountryPortalMeta:
    country: str
    legal_system: str
    legislation_portal: str
    gazette_portal: str
    ict_regulator_portal: str
    known_regulators: list[str]
    portal_search_url: str = ""
    portal_act_url: str = ""


@dataclass
class SearchQuery:
    query_string: str
    strategy: str
    priority: int  # 1 = highest priority


# ─── Indicator Question Bank — All 61 RDTII 2.1 Indicators ──────────────────

INDICATOR_QUESTION_BANK: dict[str, IndicatorMeta] = {

    "1.4": IndicatorMeta("1.4", "Trade defence on ICT",
        "Does this country have anti-dumping, countervailing duty, or safeguard measures on ICT goods? Look for: specific anti-dumping orders on electronics, semiconductors, telecom equipment; safeguard investigations on digital products; CVD investigations on ICT goods.",
        ["anti-dumping duties", "countervailing duties", "trade defence", "safeguard measures", "trade remedies", "customs duties", "anti-dumping ICT", "safeguard investigation", "dumping duty electronics"]),
    "2.1": IndicatorMeta("2.1", "Foreign exclusions procurement",
        "Does any law exclude foreign firms from ICT public procurement? Look for: domestic preference schemes, set-asides for local firms, foreign exclusion clauses, preferential treatment for domestic suppliers in government ICT tenders.",
        ["government procurement", "public procurement", "procurement rules", "procurement foreign exclusion", "ICT tender", "procurement regulations", "domestic preference", "local supplier preference", "procurement act"]),
    "2.2": IndicatorMeta("2.2", "Source code in procurement",
        "Does any tender require surrender of source code, patents, or trade secrets? Look for: mandatory source code escrow, algorithm disclosure, patent assignment, trade secret surrender, IP transfer requirements in ICT procurement.",
        ["source code", "procurement disclosure", "procurement requirements", "patent surrender", "trade secret tender", "ICT procurement", "algorithm disclosure", "source code escrow", "IP transfer procurement"]),
    "2.3": IndicatorMeta("2.3", "Procurement bidding limits",
        "Does any measure discriminate against foreign bidders or impose local content conditions in ICT tenders? Look for: local content requirements, offset obligations, preference margins, bidding restrictions on foreign firms.",
        ["procurement regulations", "local content procurement", "government procurement", "procurement bidding", "foreign bidder", "procurement discrimination", "offset requirements", "local content requirement ICT"]),
    "3.1": IndicatorMeta("3.1", "Foreign equity digital sectors",
        "What is the maximum foreign ownership allowed in sectors relevant to digital trade (excl. telecom and e-commerce)? Look for: negative list entries, foreign equity caps, strategic sector restrictions, approved sectors for FDI (e.g. media, broadcasting, insurance, transport, energy, health, education).",
        ["foreign investment", "foreign ownership", "companies act", "foreign equity", "investment limit", "acquisitions and takeovers", "negative list", "FDI restriction", "strategic sector", "foreign equity cap"]),
    "3.2": IndicatorMeta("3.2", "Joint venture requirement",
        "Does any law require foreign firms to form a joint venture with a local partner to operate in digital trade sectors? Look for: mandatory JV requirements, local equity participation, Bumiputera/indigenous partnership requirements, local partner mandatory.",
        ["joint venture", "foreign partnership", "companies act", "local partner", "JV requirement", "foreign investment", "local equity", "mandatory joint venture", "Bumiputera requirement"]),
    "3.3": IndicatorMeta("3.3", "Board nationality requirement",
        "Does any law require board members or managers to be nationals or residents? Look for: director nationality, local director requirement, board residency rules, citizenship requirements for key management, company secretary local requirements.",
        ["director nationality", "board residency", "companies act", "local director", "board requirement", "residency requirement", "citizenship requirement board", "local manager", "company secretary"]),
    "3.4": IndicatorMeta("3.4", "Investment screening",
        "Is there an investment screening mechanism that has been used to block digital trade investments? Look for: foreign investment review boards, national security screening, CFIUS-like mechanisms, takeovers acts, critical infrastructure screening.",
        ["foreign investment", "investment screening", "national security", "takeovers act", "critical infrastructure", "investment review", "investment committee", "screening mechanism", "foreign acquisition"]),
    "3.5": IndicatorMeta("3.5", "Commercial presence requirement",
        "Does any law require a foreign company to establish local commercial presence to offer cross-border digital services? Look for: branch registration, representative office, local entity requirement, place of business requirement for cross-border services.",
        ["commercial presence", "local establishment", "companies act", "foreign company", "business registration", "local entity", "branch registration", "representative office", "place of business"]),
    "4.01": IndicatorMeta("4.01", "Patent application",
        "Are there discriminatory patent application requirements or non-transparent patent filing processes? Look for: local filing first requirements, foreign applicant discrimination, working requirements, compulsory local agent, discriminatory fees, non-transparent examination.",
        ["patent act", "patent application", "intellectual property", "patent filing", "patent registration", "patent office", "local filing", "working requirement", "patent examination"]),
    "4.2": IndicatorMeta("4.2", "Patent civil enforcement",
        "Are civil procedures, administrative remedies, and provisional measures available for patent enforcement? Look for: patent infringement remedies, preliminary injunctions, discovery, damages, accounts of profits, administrative enforcement customs seizures.",
        ["patent act", "patent enforcement", "patent remedies", "patent infringement", "patent injunction", "intellectual property", "preliminary injunction", "patent damages", "customs seizure counterfeits"]),
    "4.3": IndicatorMeta("4.3", "Patent enforcement other",
        "Are there other patent enforcement restrictions with significant impact? Look for: compulsory licensing provisions, patent revocation procedures, opposition proceedings, Bolar exemptions, parallel import restrictions.",
        ["patent act", "compulsory licence", "patent invalidation", "patent enforcement", "patent opposition", "patent revocation", "compulsory licensing", "Bolar exemption", "parallel import"]),
    "4.5": IndicatorMeta("4.5", "Copyright framework",
        "Is there a copyright legal framework with clear fair use or fair dealing exceptions? Look for: copyright act, fair dealing provisions, fair use, three-step test, copyright exceptions for education/research, limitations and exceptions.",
        ["copyright act", "copyright law", "fair dealing", "copyright exceptions", "intellectual property", "copyright framework", "fair use", "three-step test", "copyright limitations"]),
    "4.6": IndicatorMeta("4.6", "Online copyright enforcement",
        "Are civil procedures and provisional measures available for online copyright enforcement? Look for: notice and takedown, safe harbour, ISP liability, blocking injunctions, site blocking, online copyright infringement remedies.",
        ["copyright act", "copyright enforcement", "copyright infringement", "online copyright", "copyright remedy", "intellectual property", "notice and takedown", "site blocking", "ISP liability copyright"]),
    "4.9": IndicatorMeta("4.9", "Trade secret disclosure",
        "Does any law require mandatory disclosure of source code or algorithms? Look for: source code disclosure mandates, algorithm transparency, encryption key disclosure, API disclosure requirements, software escrow requirements.",
        ["trade secret", "source code", "confidential information", "algorithm disclosure", "mandatory disclosure", "privacy act", "source code disclosure", "algorithm transparency", "encryption key disclosure"]),
    "4.10": IndicatorMeta("4.10", "Trade secret protection",
        "Is there an effective legal framework protecting trade secrets? Look for: trade secrets act, breach of confidence, misappropriation remedies, protection of confidential business information, trade secret misappropriation civil/criminal penalties.",
        ["trade secret", "confidential information", "breach of confidence", "trade secrets act", "confidentiality law", "intellectual property", "misappropriation", "trade secret protection", "confidential business information"]),
    "5.1": IndicatorMeta("5.1", "Passive infrastructure sharing",
        "Is passive telecom infrastructure sharing mandated by law? Look for: tower sharing mandates, co-location requirements, infrastructure sharing regulations, access to existing facilities, telecom infrastructure sharing obligations for operators.",
        ["telecommunications act", "infrastructure sharing", "telecom regulations", "tower sharing", "access pricing", "telecom infrastructure", "co-location", "facilities sharing", "passive infrastructure"]),
    "5.2": IndicatorMeta("5.2", "Foreign equity telecom",
        "What is the maximum foreign ownership allowed in the telecom sector? Look for: FDI caps in telecom, foreign equity limits for NFP/CLS licences, telecom foreign ownership restrictions, media/telecom cross-ownership rules.",
        ["telecommunications act", "foreign ownership", "telecom sector", "telecom equity", "FDI telecom", "telecommunications licence", "foreign equity telecom", "telecom FDI cap", "NFP licence"]),
    "5.3": IndicatorMeta("5.3", "Government telecom ownership",
        "Does the government hold shares in any telecom company? Look for: state-owned telecom operator, government golden share, government stake in telecom, partial privatisation, government holding in telecom sector, sovereign wealth fund telecom.",
        ["telecommunications act", "government ownership", "telecom shares", "state-owned telecom", "government telecom", "telecommunications company", "golden share", "government stake", "SOE telecom"]),
    "5.4": IndicatorMeta("5.4", "Functional/accounting separation",
        "Is functional or accounting separation mandated for telecom operators? Look for: accounting separation requirements, functional separation, structural separation, cost accounting, transfer pricing rules, separate financial accounts for telecom services.",
        ["telecommunications act", "accounting separation", "telecom competition", "functional separation", "structural separation", "carrier licence", "cost accounting", "transfer pricing telecom", "regulatory accounting"]),
    "5.5": IndicatorMeta("5.5", "Telecom licensing",
        "Are there strict licensing requirements for telecom operators? Look for: individual licences, class licences, NFP licence, facilities-based licence, services-based licence, spectrum licence, licence conditions, compliance obligations, performance bonds.",
        ["telecommunications act", "telecom licence", "network facilities", "telecommunications licence", "carrier licence", "telecom regulation", "NFP", "spectrum licence", "service provider licence"]),
    "5.7": IndicatorMeta("5.7", "Independent telecom authority",
        "Is there an independent telecom regulatory authority? Look for: telecom regulator, communications authority, media authority, MCMC, IMDA, ACMA, independent commission, regulatory powers, enforcement authority.",
        ["telecommunications act", "regulatory authority", "telecom regulator", "communications authority", "media authority", "telecommunications commission", "MCMC", "IMDA", "ACMA"]),
    "6.1": IndicatorMeta("6.1", "Ban/local processing",
        "Does this country restrict cross-border data transfers? Look for: transfer limitation obligations, prior approval requirements, consent conditions, adequacy decisions, standard contractual clauses, binding corporate rules, or any condition/ban on sending data abroad. Also look for: PDPA Section 26 (or equivalent), data export prohibition, cross-border data transfer restriction, local processing mandate.",
        ["personal data protection", "data privacy law", "cross-border data transfer", "Section 26", "transfer limitation", "data localisation", "data export restriction", "overseas data transfer", "adequacy requirement", "prior approval data transfer", "consent data export", "standard contractual clauses", "transfer restriction", "data export prohibition"]),
    "6.2": IndicatorMeta("6.2", "Local storage requirement",
        "Does the law require a LOCAL COPY of data to be stored domestically? Look for: mandatory local storage, data residency, data mirroring, requirement to keep a copy in-country, domestic server requirement, records kept within the jurisdiction, data retention domestic.",
        ["data protection act", "data privacy legislation", "health records", "personal data must be stored", "data storage law", "local server requirement", "mandatory local copy", "data retention domestic", "record keeping law", "data residency", "local storage mandate"]),
    "6.3": IndicatorMeta("6.3", "Infrastructure requirement",
        "Does the law require physical local servers or data centres as a condition to offer services? Look for: local server mandate, data centre requirement, in-country infrastructure, cloud localisation, computing facilities within country, physical presence for data processing.",
        ["data protection act", "data localisation policy", "health records", "local server mandate", "data centre requirement", "infrastructure localisation", "server located in country", "physical ICT infrastructure requirement", "cloud localisation", "computing facilities"]),
    "6.4": IndicatorMeta("6.4", "Conditional flow regime",
        "Is cross-border data transfer allowed but only under specific conditions? Look for: adequacy decisions, standard contractual clauses, binding corporate rules, consent exception, contractual clauses, prior approval, or other conditions that allow transfer.",
        ["data protection law", "cross-border data transfer", "health records", "overseas data transfer", "data transfer conditions", "adequacy decision", "standard contractual clauses", "consent data export", "binding corporate rules", "prior approval data abroad", "data transfer mechanism"]),
    "7.1": IndicatorMeta("7.1", "Data protection framework",
        "Does this country have a horizontal personal data protection law? Look for: Personal Data Protection Act, privacy act, data protection law, comprehensive data protection framework, notification requirements, individual rights (access, correction, deletion), enforcement authority.",
        ["personal data protection", "privacy act", "data protection", "PDPA", "data privacy", "information protection", "data protection authority", "personal data", "privacy principles"]),
    "7.2": IndicatorMeta("7.2", "Cybersecurity framework",
        "Does this country have a dedicated cybersecurity law? Look for: Cybersecurity Act, cybercrime law, Computer Misuse Act, critical information infrastructure (CII) framework, Computer Emergency Response Team (CERT), national cybersecurity strategy, security breach notification.",
        ["cybersecurity act", "cyber crime", "computer offences", "cyber security", "computer crimes", "digital security", "CII", "critical information infrastructure", "CERT", "cybersecurity framework"]),
    "7.3": IndicatorMeta("7.3", "Minimum retention",
        "Does the law require data to be kept for a MINIMUM period? Look for: mandatory minimum retention, records retention requirement, archiving obligations, data preservation orders, minimum period of data retention, statutory retention periods.",
        ["data retention", "records retention", "retention period", "minimum retention", "records keeping", "data preservation", "mandatory retention", "archiving requirement", "minimum period"]),
    "7.4": IndicatorMeta("7.4", "DPO/DPIA requirement",
        "Does the law require a Data Protection Officer or Data Protection Impact Assessment? Look for: DPO appointment, data protection officer mandatory, privacy impact assessment, PIA requirement, DPIA mandatory, data protection compliance programme.",
        ["data protection", "privacy impact assessment", "data protection officer", "DPIA", "DPO requirement", "privacy framework", "PIA", "data protection compliance", "appoint DPO"]),
    "7.5": IndicatorMeta("7.5", "Government data access",
        "Does any law allow government or law enforcement to access personal data? Look for: law enforcement access, surveillance law, government access, lawful interception, criminal procedure disclosure, national security access, cybercrime investigation powers, data retention for law enforcement.",
        ["law enforcement access", "surveillance law", "government access", "lawful interception", "criminal procedure", "security offences", "data access law enforcement", "national security data", "investigation powers"]),
    "8.1": IndicatorMeta("8.1", "Safe harbour copyright",
        "Is there a safe harbour for copyright infringement by intermediaries? Look for: safe harbour provisions, DMCA-like framework, notice and takedown, ISP liability limitation, hosting provider safe harbour, platform liability exemption for copyright, intermediary liability limitation.",
        ["intermediary liability", "safe harbour", "copyright infringement", "ISP liability", "online platform", "hosting provider", "notice and takedown", "DMCA safe harbour", "platform liability copyright"]),
    "8.2": IndicatorMeta("8.2", "Safe harbour other",
        "Is there a safe harbour for intermediaries regarding other illegal activities? Look for: intermediary liability for defamation, platform liability for user content, hosting safe harbour for non-copyright, digital services act, platform liability framework, mere conduit safe harbour.",
        ["intermediary liability", "safe harbour", "online platform", "hosting liability", "platform liability", "digital services", "defamation intermediary", "user content liability", "platform immunity"]),
    "8.3": IndicatorMeta("8.3", "User identity",
        "Does any law require user identity verification to access the internet or online services? Look for: SIM registration, real-name verification, KYC requirements, eKYC, mandatory registration for online services, national digital ID requirement for internet access, prepaid SIM registration.",
        ["user identity", "SIM registration", "identity verification", "real name", "user verification", "digital identity", "KYC", "prepaid SIM", "national digital ID"]),
    "8.4": IndicatorMeta("8.4", "Monitoring requirement",
        "Does any law require platforms to monitor user activities or proactively remove/block content? Look for: proactive monitoring obligation, content removal duty, duty of care for online platforms, user surveillance requirement, automated filtering, proactive content moderation, blocking orders.",
        ["content monitoring", "platform obligation", "user surveillance", "content removal", "platform monitoring", "online content", "proactive monitoring", "duty of care platform", "automated filtering"]),
    "9.1": IndicatorMeta("9.1", "Web content blocking",
        "Has this country blocked or filtered commercial web content? Look for: website blocking injunctions, DNS filtering, URL blocking, ISP blocking orders, internet censorship, firewall, content filtering, blocking of illegal content, child abuse website blocking.",
        ["website blocking", "content filtering", "internet censorship", "web blocking", "content restriction", "online censorship", "URL blocking", "DNS filtering", "ISP blocking"]),
    "9.3": IndicatorMeta("9.3", "Online advertising",
        "Are there restrictions on online advertising? Look for: advertising restrictions, digital advertising regulation, online advertising ban (e.g. alcohol, tobacco, gambling, pharmaceuticals), targeted advertising restrictions, advertising content rules, influencer marketing regulation.",
        ["online advertising", "digital advertising", "advertising regulation", "internet advertising", "advertising restriction", "digital marketing", "targeted advertising", "influencer regulation", "advertising ban"]),
    "9.4": IndicatorMeta("9.4", "Online content licensing",
        "Are there licensing requirements for online content providers? Look for: online content provider licence, streaming service licence, social media licence, broadcasting licence for online, platform licensing regime, news licensing, video-on-demand licence, content regulation authority.",
        ["online platform licence", "content provider", "social media", "online licensing", "platform regulation", "broadcasting licence", "streaming licence", "VOD licence", "news licence"]),
    "10.1": IndicatorMeta("10.1", "ICT import ban",
        "Is there a ban on importing specific ICT goods or online services? Look for: import prohibition on telecom equipment, customs prohibition on electronics, import ban on encryption, banned ICT goods, trade prohibition for security reasons, import control list.",
        ["customs prohibition imports", "import restriction", "import ban", "prohibited imports", "customs order", "import control", "ICT import ban", "telecom equipment import", "prohibited electronics"]),
    "10.2": IndicatorMeta("10.2", "Other ICT import restrictions",
        "Are there other import restrictions on ICT goods? Look for: import licensing requirements, non-automatic licences, import permits, technology import controls, strategic trade controls, dual-use import restrictions, quantitative restrictions on ICT.",
        ["strategic trade", "import control", "trade restrictions", "customs prohibition", "import licence", "technology goods", "non-automatic licence", "dual-use", "import permit ICT"]),
    "10.3": IndicatorMeta("10.3", "Local content requirement",
        "Are there local content requirements for ICT goods or services? Look for: local content quota for broadcasting, domestic content requirements, local production requirements, local sourcing mandates, preferences for locally produced ICT goods, audio-visual content quota.",
        ["local content", "domestic content", "broadcasting services", "local requirement", "content quota", "broadcasting act", "local content quota", "audio-visual quota", "domestic production ICT"]),
    "10.4": IndicatorMeta("10.4", "ICT export restriction",
        "Are there restrictions on exporting ICT goods or online services? Look for: export controls, strategic goods control, dual-use export restrictions, encryption export controls, defence trade controls, technology export permits, national security export bans.",
        ["export control", "strategic goods", "customs prohibition exports", "export restriction", "defence trade", "export ban", "dual-use export", "encryption export", "technology transfer control"]),
    "11.1": IndicatorMeta("11.1", "Transparent standards",
        "Are foreigners allowed to participate in technical standard-setting bodies? Look for: standards development organisation, foreign participation in standards, standards act, SDO membership, technical standards committee, national standards body, transparency in standard-setting.",
        ["standards act", "standard setting", "technical standards", "standards development", "standardisation", "conformity assessment", "SDO", "standards committee", "foreign participation standards"]),
    "11.2": IndicatorMeta("11.2", "Self-certification",
        "Is supplier declaration of conformity (SDoC) allowed for product safety certification? Look for: self-certification, type approval, conformity assessment, supplier declaration of conformity, mutual recognition agreement, acceptance of foreign testing, product certification.",
        ["self-certification", "conformity assessment", "mutual recognition", "supplier declaration", "product certification", "equipment registration", "SDoC", "type approval", "foreign testing acceptance"]),
    "11.3": IndicatorMeta("11.3", "Product testing",
        "Are there mandatory product screening or testing requirements for ICT goods? Look for: mandatory testing, equipment registration, type approval, product screening, telecom equipment certification, safety testing, EMC testing, conformity mark requirements.",
        ["product testing", "equipment registration", "technical standards", "product screening", "telecom equipment", "type approval", "mandatory testing", "EMC testing", "safety certification ICT"]),
    "11.4": IndicatorMeta("11.4", "Encryption standards",
        "Does the country deviate from international encryption standards? Look for: national encryption standard, cryptography requirements, local encryption algorithm, non-standard encryption, mandatory encryption, key escrow, encryption backdoor, deviation from ISO/IEC/ITU standards.",
        ["encryption standard", "cryptographic", "security standard", "encryption requirement", "cryptography", "national encryption", "key escrow", "encryption algorithm", "national standard cryptography"]),
    "12.01": IndicatorMeta("12.01", "E-commerce foreign equity",
        "What is the maximum foreign ownership allowed in the e-commerce sector? Look for: foreign ownership in retail trade, FDI in e-commerce, foreign equity cap for online retail, multi-level marketing restrictions, distributive trade limits, foreign investment in digital commerce.",
        ["e-commerce", "foreign ownership", "companies act", "electronic commerce", "foreign equity", "distributive trade", "e-commerce FDI", "retail trade foreign", "online retail equity"]),
    "12.2": IndicatorMeta("12.2", "Online purchase limits",
        "Are there limits on the number or type of products that can be purchased online? Look for: online purchase restrictions, limit on products per transaction, import restrictions on consumer goods online, e-commerce product bans, cross-border shopping limits, postal import restrictions.",
        ["electronic commerce", "online purchase", "e-commerce regulation", "electronic transactions", "online retail", "digital commerce", "purchase limit", "product ban online", "cross-border online shopping"]),
    "12.3": IndicatorMeta("12.3", "E-commerce licence",
        "Is a licence required for e-commerce providers? Look for: e-commerce licence, online business registration, trading licence for online, direct selling licence, business licence for digital services, marketplace licence, platform registration.",
        ["e-commerce", "business registration", "online retail", "electronic commerce", "trading licence", "digital services", "e-commerce licence", "marketplace licence", "online seller registration"]),
    "12.4.1": IndicatorMeta("12.4.1", "Local bank account",
        "Does any law require use of a local bank account for online payments? Look for: local bank account requirement, domestic account for payments, local currency settlement, banking act provisions, payment systems regulation, local financial institution requirement.",
        ["payment services", "financial services", "anti-money laundering", "banking act", "payment regulation", "financial sector", "local bank account", "domestic account payment", "local currency payment"]),
    "12.4.2": IndicatorMeta("12.4.2", "Payment currency",
        "Does any law mandate specific currency for international online payments? Look for: mandatory currency, domestic currency requirement for cross-border payments, foreign exchange controls, local currency settlement requirement, currency conversion mandates.",
        ["payment services", "financial services", "international payment", "currency regulation", "foreign exchange", "cross-border payment", "mandatory currency", "local currency", "foreign exchange control"]),
    "12.4.3": IndicatorMeta("12.4.3", "Payment standards",
        "Does the country use payment security standards that deviate from international norms? Look for: national payment standard, domestic payment protocol, unique technical standard for payments, deviation from ISO 20022, PCI DSS, or EMV; proprietary payment system.",
        ["payment system", "payment standard", "electronic payment", "payment security", "technical reference", "payment regulation", "national payment standard", "PCI DSS", "ISO 20022"]),
    "12.4.4": IndicatorMeta("12.4.4", "Payment licensing",
        "Are there restrictive licensing requirements for online payment services? Look for: payment service licence, e-money licence, payment institution licence, banking licence for payments, restrictive conditions, capital requirements, prior approval for payment services.",
        ["payment services", "financial services", "payment licence", "banking act", "electronic money", "payment regulation", "e-money licence", "payment institution", "payment service provider licence"]),
    "12.4.5": IndicatorMeta("12.4.5", "Payment ceiling",
        "Are there ceilings on the maximum amount payable by electronic means? Look for: transaction limit, payment ceiling, maximum transaction amount, daily limit on electronic payment, value limit for digital payments, AML transaction thresholds.",
        ["payment services", "financial services", "transaction limit", "payment ceiling", "electronic money", "anti-money laundering", "maximum transaction", "daily limit payment", "value limit digital"]),
    "12.4.6": IndicatorMeta("12.4.6", "Mandatory intermediary",
        "Does any law mandate use of specific intermediaries for online payments? Look for: mandatory intermediary, compulsory payment gateway, designated payment system, national payment switch, mandated settlement system, central bank payment system requirement.",
        ["payment services", "financial services", "payment intermediary", "payment gateway", "competition act", "anti-money laundering", "mandatory intermediary", "designated payment system", "national payment switch"]),
    "12.4.7": IndicatorMeta("12.4.7", "Other payment restrictions",
        "Are there other restrictions on online payment services? Look for: other payment restrictions, digital payment barriers, online transaction restrictions, additional compliance requirements, fintech restrictions, innovative payment service barriers.",
        ["electronic commerce", "electronic transactions", "digital payment", "payment restriction", "financial services", "online payment", "fintech regulation", "digital payment restriction", "payment barrier"]),
    "12.5": IndicatorMeta("12.5", "De minimis threshold",
        "What is the de minimis threshold for import duties on e-commerce goods? Look for: de minimis threshold, low value goods threshold, customs duty exemption threshold, GST/VAT on low value imports, duty-free allowance, import duty threshold for e-commerce.",
        ["customs duty", "de minimis", "low value goods", "import duty", "sales tax", "goods and services tax", "de minimis threshold", "duty-free allowance", "low value import"]),
    "12.6": IndicatorMeta("12.6", "Customs on e-transmission",
        "Are customs duties imposed on electronic transmissions? Look for: customs duties on electronic transmissions, digital services tax, digital goods tariff, WTO moratorium on electronic transmissions, customs on software downloads, streaming tax, e-commerce duties.",
        ["customs tariff", "electronic transmission", "digital goods", "customs duty", "electronic commerce", "digital product", "digital services tax", "electronic transmissions duty", "WTO moratorium"]),
    "12.7": IndicatorMeta("12.7", "Domain name requirement",
        "Is physical or legal presence required to register a local domain name? Look for: ccTLD registration requirements, local presence for domain, domain name registry rules, residence requirement for domain, local company for domain registration, MyDomain, .sg, .my, .au registry policies.",
        ["domain name", "domain registration", "country code domain", "domain registry", "internet domain", "ccTLD", "local presence domain", "my domain", "sg domain", "au domain"]),
    "12.8": IndicatorMeta("12.8", "Local presence online services",
        "Are there local presence requirements for online service providers? Look for: local presence requirement, branch requirement for digital services, physical office for online business, local establishment for cross-border services, registered address requirement, place of business.",
        ["companies act", "local presence", "business registration", "foreign company", "local entity", "commercial presence", "branch registration", "physical office requirement", "registered address online"]),
    "12.9": IndicatorMeta("12.9", "Consumer protection online",
        "Is there a consumer protection legal framework applicable to online commerce? Look for: consumer protection act, fair trading act, competition and consumer commission, online consumer rights, cooling-off period, cancellation rights, e-commerce consumer protection, distance selling regulations.",
        ["consumer protection", "competition and consumer", "electronic commerce", "consumer law", "fair trading", "consumer rights", "online consumer protection", "distance selling", "cooling-off period", "e-commerce consumer"]),
}


# ─── Country Portal Registry ─────────────────────────────────────────────────

COUNTRY_PORTAL_REGISTRY: dict[str, CountryPortalMeta] = {
    "Malaysia": CountryPortalMeta(
        country="Malaysia",
        legal_system="common",
        legislation_portal="agc.gov.my",
        gazette_portal="federalgazette.agc.gov.my",
        ict_regulator_portal="pdpcommissioner.gov.my",
        known_regulators=["MCMC", "Bank Negara Malaysia", "Securities Commission Malaysia", "MDEC"],
        portal_search_url="https://lom.agc.gov.my/search.php?search={query}",
        portal_act_url="https://lom.agc.gov.my/act-view.php?act={act_id}",
    ),
    "Singapore": CountryPortalMeta(
        country="Singapore",
        legal_system="common",
        legislation_portal="sso.agc.gov.sg",
        gazette_portal="egazette.agc.gov.sg",
        ict_regulator_portal="pdpc.gov.sg",
        known_regulators=["PDPC", "CSA", "IMDA", "MAS", "ACRA"],
        portal_search_url="https://sso.agc.gov.sg/Search?searchString={query}",
        portal_act_url="https://sso.agc.gov.sg/Act/{act_id}",
    ),
    "Australia": CountryPortalMeta(
        country="Australia",
        legal_system="common",
        legislation_portal="legislation.gov.au",
        gazette_portal="legislation.gov.au/gazettes",
        ict_regulator_portal="oaic.gov.au",
        known_regulators=["OAIC", "ACSC", "ACMA", "APRA", "ASIC"],
        portal_search_url="https://www.legislation.gov.au/Search?s={query}",
        portal_act_url="https://www.legislation.gov.au/Details/{act_id}",
    ),
}


# ─── Indicator Legal Profile ────────────────────────────────────────────────
# Per-indicator guidance on what TYPE of legal instruments are relevant.
# NOT hardcoded law names — just descriptions of legal categories to search for.
# The LLM uses these to infer what laws a country is likely to have.

_INDICATOR_LEGAL_PROFILES: dict[str, str] = {
    # Pillar 1: Tariffs
    "1.4": "customs acts, anti-dumping regulations, trade remedies legislation, countervailing duty laws, safeguard measures",
    # Pillar 2: Procurement
    "2.1": "government procurement acts, public procurement regulations, treasury directives on foreign participation in tenders",
    "2.2": "procurement regulations, ICT procurement policies, intellectual property assignment rules for government contracts",
    "2.3": "procurement acts, local content regulations, offset policy frameworks, industry participation plans",
    # Pillar 3: FDI
    "3.1": "foreign investment acts, companies acts, negative investment lists, strategic sector regulations, sector-specific foreign equity caps",
    "3.2": "companies acts, joint venture regulations, partnership laws, Bumiputera/indigenous participation frameworks",
    "3.3": "companies acts, directors requirements, board composition regulations, residency requirements for company officers",
    "3.4": "foreign investment screening mechanisms, national security legislation, takeovers acts, critical infrastructure protection laws",
    "3.5": "companies acts, business registration acts, commercial presence requirements for foreign service providers",
    # Pillar 4: IP
    "4.01": "patents acts, patent regulations, intellectual property office rules, patent examination guidelines, TRIPS implementation",
    "4.2": "patents acts, intellectual property enforcement regulations, civil procedure codes for IP, customs IP enforcement",
    "4.3": "patents acts, compulsory licensing frameworks, patent revocation procedures, Bolar exemption provisions",
    "4.5": "copyright acts, copyright amendments, fair dealing/fair use provisions, copyright exceptions for education and research",
    "4.6": "copyright acts, online copyright enforcement, notice-and-takedown frameworks, ISP liability copyright, site blocking",
    "4.9": "trade secrets acts, source code disclosure laws, algorithm transparency regulations, encryption key escrow requirements",
    "4.10": "trade secrets acts, breach of confidence, confidential business information protection, misappropriation remedies",
    # Pillar 5: Telecom
    "5.1": "telecommunications acts, infrastructure sharing codes, access regulations, facilities sharing mandates for telecom operators",
    "5.2": "telecommunications acts, foreign equity rules for telecom licences, media ownership regulations, telecom FDI frameworks",
    "5.3": "telecommunications acts, government ownership policies, state-owned enterprise frameworks, golden share provisions",
    "5.4": "telecommunications acts, accounting separation regulations, functional separation rules, cost accounting directives",
    "5.5": "telecommunications acts, licensing regulations, carrier licence frameworks, network facility provider rules, class licence schemes",
    "5.7": "telecommunications acts, regulatory authority establishment acts, independent commission frameworks",
    # Pillar 6: Cross-border Data
    "6.1": "data protection acts, privacy acts, cross-border data transfer provisions, sector-specific data localisation laws (health, finance, telecom), data export restriction regulations",
    "6.2": "data protection acts, data residency requirements, local storage mandates, record-keeping regulations specifying domestic storage",
    "6.3": "data protection acts, data centre localisation policies, cloud computing regulations, physical infrastructure requirements for data processing",
    "6.4": "data protection acts, cross-border data transfer frameworks, adequacy decisions, standard contractual clauses provisions, binding corporate rules, consent-based transfer allowances",
    # Pillar 7: Data Protection
    "7.1": "data protection acts, privacy acts, personal data protection frameworks, comprehensive privacy laws, data protection authority establishment acts",
    "7.2": "cybersecurity acts, cybercrime acts, computer misuse acts, critical information infrastructure protection laws, computer emergency response team frameworks",
    "7.3": "data retention laws, records retention regulations, archiving acts, minimum data retention period requirements",
    "7.4": "data protection acts, data protection officer requirements, privacy impact assessment mandates, data protection compliance frameworks",
    "7.5": "law enforcement access laws, surveillance acts, lawful interception frameworks, criminal procedure codes, national security data access, cybersecurity investigation powers",
    # Pillar 8: Intermediaries
    "8.1": "copyright acts, intermediary liability frameworks, safe harbour provisions, DMCA-style notice-and-takedown, ISP liability limitation for copyright",
    "8.2": "intermediary liability frameworks, safe harbour for non-copyright, platform liability, defamation laws, digital services acts",
    "8.3": "SIM registration regulations, identity verification laws, e-KYC frameworks, national digital ID acts, prepaid SIM registration rules",
    "8.4": "online content regulation acts, platform monitoring obligations, content removal duties, social media regulation, blocking orders",
    # Pillar 9: Content
    "9.1": "website blocking laws, content filtering regulations, internet censorship frameworks, ISP blocking order provisions, DNS filtering rules",
    "9.3": "online advertising regulations, digital marketing restrictions, advertising content codes, targeted advertising bans, influencer marketing rules",
    "9.4": "online content licensing, streaming service regulations, social media licensing, broadcasting acts applicable to online, video-on-demand licensing",
    # Pillar 10: NTMs
    "10.1": "customs acts, import prohibition regulations, trade sanctions, ICT goods import bans, telecommunications equipment import restrictions",
    "10.2": "strategic trade acts, import licensing regulations, dual-use trade controls, technology import permits, quantitative restriction frameworks",
    "10.3": "broadcasting acts, local content quotas, audio-visual content regulations, domestic production requirements for ICT goods",
    "10.4": "export control acts, strategic goods regulations, dual-use export controls, defence trade acts, encryption export restrictions, technology transfer controls",
    # Pillar 11: Standards
    "11.1": "standards acts, standardisation frameworks, technical regulations, conformity assessment acts, standards development organisation rules",
    "11.2": "conformity assessment regulations, product certification rules, supplier declaration of conformity frameworks, mutual recognition agreements",
    "11.3": "equipment registration regulations, type approval frameworks, mandatory product testing, telecom equipment certification, EMC compliance",
    "11.4": "national encryption standards, cryptography regulations, cybersecurity certification frameworks, deviation from international crypto standards",
    # Pillar 12: E-commerce
    "12.01": "e-commerce regulations, foreign equity rules for retail trade, distributive trade acts, foreign investment frameworks for online retail",
    "12.2": "e-commerce regulations, online purchase restrictions, cross-border e-commerce limits, consumer goods import restrictions online",
    "12.3": "e-commerce acts, business registration frameworks, online marketplace licensing, direct selling acts, digital platform regulations",
    "12.4.1": "payment systems acts, banking acts, electronic payment regulations, local account requirements for online transactions",
    "12.4.2": "foreign exchange controls, currency regulations, central bank acts, cross-border payment currency mandates, exchange control acts",
    "12.4.3": "payment security standards, national payment protocols, electronic transactions acts, technical payment standards",
    "12.4.4": "payment services acts, e-money regulations, banking acts, payment institution licensing, fintech regulatory frameworks",
    "12.4.5": "anti-money laundering acts, payment transaction limits, electronic money ceilings, AML/CFT regulations for digital payments",
    "12.4.6": "payment systems acts, national payment switch regulations, mandatory payment gateway, designated payment system frameworks",
    "12.4.7": "fintech regulations, digital payment frameworks, innovative payment service rules, financial technology sandbox frameworks",
    "12.5": "customs acts, de minimis threshold regulations, GST/VAT acts, low-value import duty exemptions, e-commerce customs frameworks",
    "12.6": "customs tariff acts, digital services tax, electronic transmissions, WTO moratorium implementation, software import duties",
    "12.7": "domain name registry rules, ccTLD policies, internet governance frameworks, domain registration requirements for foreign entities",
    "12.8": "companies acts, branch registration requirements, commercial presence rules for digital services, local establishment obligations",
    "12.9": "consumer protection acts, fair trading acts, electronic commerce consumer protections, distance selling regulations, online dispute resolution",
}


# ─── LLM-Enhanced Query Generation ──────────────────────────────────────────

_LLM_QUERY_PROMPT = """You are a legal research search-engine optimizer for the RDTII 2.1 index. Your single task: generate web search queries that will find the legal provisions relevant to this indicator.

COUNTRY: {country}
LEGAL SYSTEM: {legal_system}
LEGISLATION PORTAL: {legislation_portal}

INDICATOR: {indicator_id} — {indicator_title}
RESEARCH QUESTION: {research_question}

SCORING CRITERIA (what this indicator measures — each criteria key maps to a score):
{criteria_table}

WHAT TO SEARCH FOR (legal categories and concepts relevant to this indicator — DO NOT assume specific law names):
{legal_profile}

REGULATORS / AUTHORITIES (reference these to narrow results):
{known_regulators}

--- HOW TO GENERATE QUERIES ---
This indicator measures whether a SPECIFIC TYPE OF LEGAL RESTRICTION or PROTECTION exists. The "What to Search For" field describes the categories of law that typically contain this type of provision. Your job is to generate search queries based on:

1. The indicator's research question — what legal concept is being measured
2. The legal categories described in "What to Search For" (e.g. "data protection acts", "cross-border data transfer provisions")
3. The country context (legal system, legislation portal)

CONSTRAINTS:
- Do NOT guess or infer specific law names, act titles, section numbers, or year references that you are not certain exist
- Base queries on the LEGAL CONCEPT and CATEGORIES, not on assumed law names
- Use the indicator's research question and scoring criteria to determine what to search for
- Cover multiple angles: legal concept broad search, sector-specific variants, regulator relevance

--- OUTPUT RULES ---
- Each query must target the legislation portal: site:{legislation_portal} OR site:.gov.{country_tld}
- Each query must include the country name
- Vary queries: legal concept terms, sector context, regulator guidelines
- Use quotes for exact phrase matches on legal concepts
- Generate 8-12 queries

--- OUTPUT FORMAT ---
{{"queries": [
  {{"query": "search query based on legal concept and categories", "rationale": "what legal provision this targets"}},
  ...
]}}

Generate queries for {country} / {indicator_id}."""


def _llm_generate_queries(
    country: str,
    indicator_id: str,
    meta: IndicatorMeta | None,
    portal: CountryPortalMeta | None,
) -> list[SearchQuery] | None:
    """Call LLM to generate targeted search queries for a country + indicator.
    Returns None if LLM call fails or is disabled."""
    if not settings.llm_enhanced_queries:
        return None

    if not meta or not portal:
        return None

    from app.modules.analysis.agents.ai_client import call_llm_json

    # Get legal profile — describes TYPES of laws relevant to this indicator
    legal_profile = _INDICATOR_LEGAL_PROFILES.get(indicator_id, getattr(meta, "research_question", ""))

    # Build criteria table for context
    from app.modules.analysis.scoring_engine import format_criteria_for_prompt
    criteria_table = format_criteria_for_prompt(indicator_id)

    # Map country to TLD
    country_tld = {"australia": "au", "singapore": "sg", "malaysia": "my"}.get(country.strip().lower(), "com")

    # Combine portal regulators + known regulators for search context
    all_regulators = portal.known_regulators.copy()

    prompt = _LLM_QUERY_PROMPT.format(
        country=country,
        legal_system=getattr(portal, "legal_system", "common"),
        legislation_portal=getattr(portal, "legislation_portal", ""),
        country_tld=country_tld,
        known_regulators=", ".join(all_regulators) if all_regulators else "None specified",
        indicator_id=indicator_id,
        indicator_title=getattr(meta, "title", ""),
        criteria_table=criteria_table,
        research_question=getattr(meta, "research_question", ""),
        legal_profile=legal_profile,
    )

    try:
        result = call_llm_json(
            prompt,
            "You are a legal research search-engine optimizer. Output only valid JSON with a 'queries' array.",
        )
    except Exception as exc:
        logger.warning(f"[QueryGen] LLM query generation failed for {country}/{indicator_id}: {exc}")
        return None

    if not result or not isinstance(result, dict):
        return None

    raw_queries = result.get("queries", [])
    if not raw_queries or not isinstance(raw_queries, list):
        return None

    queries = []
    for i, entry in enumerate(raw_queries):
        if isinstance(entry, dict) and entry.get("query"):
            q = entry["query"].strip()
            if q and len(q) > 10:
                queries.append(SearchQuery(
                    query_string=q,
                    strategy=f"llm_enhanced_{i+1}",
                    priority=i + 1,
                ))

    if queries:
        logger.info(f"[QueryGen] LLM generated {len(queries)} queries for {country}/{indicator_id}")
        if logger.isEnabledFor(logging.DEBUG):
            for q in queries:
                logger.debug(f"  [{q.priority}] {q.query_string}")

    return queries if queries else None


# ─── Query Generator ─────────────────────────────────────────────────────────

def generate_queries(country: str, indicator_id: str) -> list[SearchQuery]:
    """
    Generate ordered list of 5–8 search queries for a given country + indicator.
    Implements the 7-template formula from RDTII spec §6.5.4.

    Args:
        country: One of Malaysia, Singapore, Australia
        indicator_id: RDTII indicator ID (e.g. "6.1", "7.4")

    Returns:
        List of SearchQuery objects sorted by priority (1 = highest).
    """
    meta = INDICATOR_QUESTION_BANK.get(indicator_id)
    if not meta:
        raise ValueError(f"Unknown indicator_id: {indicator_id}")

    portal = COUNTRY_PORTAL_REGISTRY.get(country)
    if not portal:
        raise ValueError(f"Unsupported country: {country}. Supported: {list(COUNTRY_PORTAL_REGISTRY)}")

    seeds = meta.keyword_seeds
    seed1 = seeds[0] if len(seeds) > 0 else ""
    seed2 = seeds[1] if len(seeds) > 1 else ""
    seed3 = seeds[2] if len(seeds) > 2 else ""

    regulator = portal.known_regulators[0] if portal.known_regulators else ""
    from datetime import date
    current_year = date.today().year

    queries: list[SearchQuery] = []

    # ── LLM-enhanced queries (highest priority — displace template queries) ──
    llm_queries = _llm_generate_queries(country, indicator_id, meta, portal)
    if llm_queries:
        queries.extend(llm_queries)
        # LLM queries get priorities 1..N; template queries start after them
        priority_offset = len(llm_queries)
    else:
        priority_offset = 0

    # Q1 — Portal-targeted: keywords + legislation domain
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} {seed2} {portal.legislation_portal}",
        strategy="portal_targeted",
        priority=priority_offset + 1,
    ))

    # Q2 — Keyword + broad PDF search
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} {seed2} act legislation pdf",
        strategy="known_law_pdf",
        priority=priority_offset + 2,
    ))

    # Q3 — Full act PDF download: official legislation portal direct
    queries.append(SearchQuery(
        query_string=f'{country} "{seed1}" act pdf {portal.legislation_portal}',
        strategy="full_act_pdf",
        priority=priority_offset + 3,
    ))

    # Q4 — Amendment / updated version check
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} amendment revised {current_year} {portal.legislation_portal}",
        strategy="amendment_check",
        priority=priority_offset + 4,
    ))

    # Q5 — Keyword + law/regulation combo
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} law regulation {seed2}",
        strategy="law_keyword",
        priority=priority_offset + 5,
    ))

    # Q6 — Gazette targeted
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} gazette {portal.gazette_portal}",
        strategy="gazette_targeted",
        priority=priority_offset + 6,
    ))

    # Q7 — Legislation portal + act pdf
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} act {portal.legislation_portal}",
        strategy="legislation_portal",
        priority=priority_offset + 7,
    ))

    # Q8 — Official government pages
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} {seed2} official government legislation",
        strategy="gov_targeted",
        priority=priority_offset + 8,
    ))

    # Q9 — Regulator / sector fallback
    if regulator:
        queries.append(SearchQuery(
            query_string=f"{country} {seed1} {seed2} {regulator}",
            strategy="sector_fallback",
            priority=priority_offset + 9,
        ))

    # Q10 — Broad law PDF fallback
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} act regulation pdf",
        strategy="broad_law_pdf",
        priority=priority_offset + 10,
    ))

    # Q11 — Keyword-only fallback
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} {seed2} {seed3} {current_year}",
        strategy="keyword_fallback",
        priority=priority_offset + 11,
    ))

    # Q12 — Portal search with seed1 + seed3 (catches sectoral laws like health records acts)
    queries.append(SearchQuery(
        query_string=f"{country} {seed1} {seed3} {portal.legislation_portal}",
        strategy="portal_targeted",
        priority=priority_offset + 12,
    ))

    # Q13 — Portal search with seed3 alone (catches sectoral laws by their own title terms)
    queries.append(SearchQuery(
        query_string=f"{country} {seed3} {portal.legislation_portal}",
        strategy="portal_targeted",
        priority=priority_offset + 13,
    ))

    # Q14 — Direct legislation portal search URL (fetched via web search engine;
    # some engines index the portal's own results page, surfacing act links).
    if portal.portal_search_url:
        search_url = portal.portal_search_url.replace("{query}", f"{seed1} {seed3}")
        queries.append(SearchQuery(
            query_string=search_url,
            strategy="portal_direct",
            priority=priority_offset + 14,
        ))

    return sorted(queries, key=lambda q: q.priority)


def get_all_indicator_ids() -> list[str]:
    """Return all 61 RDTII indicator IDs."""
    return list(INDICATOR_QUESTION_BANK.keys())
