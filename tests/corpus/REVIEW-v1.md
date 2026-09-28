# Relecture du corpus JEV v1 — référence relue par l’agent

Ces 30 annonces sont synthétiques. Tanguy a validé la classe des trois premiers cas ; à sa demande, l’agent a relu les 27 autres, corrigé les incohérences factuelles et vérifié mot pour mot toutes les preuves. Les 27 classes ne sont **pas validées indépendamment par un humain** : les métriques calculées sur ce corpus restent exploratoires et ne sont pas une mesure de généralisation sur des offres réelles.

Chaque cas distingue le corrigé, les faits, les portes annotées et les preuves présentes dans le texte. Une porte « fail » exclut l’offre ; « ambiguë » signifie qu’aucune incompatibilité certaine n’est établie, mais qu’une décision demande une vérification. L’absence de porte annotée n’implique pas que le cas soit compatible : Jev juge aussi la nature des missions.

Répartition : 10 adaptées, 10 incompatibles, 10 ambiguës.

## Cas examinés

### SYNTH-001-C — Junior SOC & Detection Engineer
Classe retenue : **adaptée** | Langue : fr | Lieu : Bruxelles

Annonce :
> CDI au sein d'un SOC à Bruxelles. Poste junior ouvert aux jeunes diplômés avec mentorat quotidien. Vous qualifiez les alertes dans Elastic SIEM, analysez les journaux Linux et le trafic Wireshark, écrivez des règles Sigma et automatisez des contrôles simples en Python. Aucune expérience minimale n'est exigée; une première expérience de stage est appréciée.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI au sein d'un SOC à Bruxelles. » (contrat, lieu).
- « Poste junior ouvert aux jeunes diplômés avec mentorat quotidien. » (junior, mentorat).
- « Vous qualifiez les alertes dans Elastic SIEM, analysez les journaux Linux et le trafic Wireshark, écrivez des règles Sigma et automatisez des contrôles simples en Python. » (technicité et missions).
- « Aucune expérience minimale n'est exigée; une première expérience de stage est appréciée. » (expérience non exigée).
Validation : [x] validé par Tanguy en chat (classe) ; preuves complétées et relues par l’agent.

### SYNTH-002-C — Junior DevSecOps Engineer
Classe retenue : **adaptée** | Langue : fr | Lieu : Sophia Antipolis

Annonce :
> Contrat CDI à Sophia Antipolis. L'équipe DevSecOps recrute un profil débutant pour intégrer la sécurité dans GitHub Actions, lancer SonarQube et Trivy, renforcer les images Docker et automatiser des contrôles Python. Un lead accompagne chaque livraison et une formation Kubernetes est prévue. Moins d'un an d'expérience accepté.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Contrat CDI à Sophia Antipolis. » (contrat, lieu).
- « L'équipe DevSecOps recrute un profil débutant pour intégrer la sécurité dans GitHub Actions, lancer SonarQube et Trivy, renforcer les images Docker et automatiser des contrôles Python. » (junior, missions techniques).
- « Un lead accompagne chaque livraison et une formation Kubernetes est prévue. » (formation, encadrement).
- « Moins d'un an d'expérience accepté. » (expérience acceptée).
Validation : [x] validé par Tanguy en chat (classe) ; preuves complétées et relues par l’agent.

### SYNTH-003-C — Entry-level Cloud Security Engineer
Classe retenue : **adaptée** | Langue : en | Lieu : Genève

Annonce :
> Permanent entry-level cloud security role in Geneva. Recent graduates are welcome. You will assist with AWS IAM reviews, vulnerability scanning, Terraform policy checks, Linux hardening and Python security automation. A senior engineer provides structured training and reviews all production changes. No prior full-time cloud security experience is required.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Permanent entry-level cloud security role in Geneva. » (contrat, lieu, accès junior).
- « Recent graduates are welcome. » (accès junior).
- « You will assist with AWS IAM reviews, vulnerability scanning, Terraform policy checks, Linux hardening and Python security automation. » (missions techniques).
- « A senior engineer provides structured training and reviews all production changes. » (formation, encadrement).
- « No prior full-time cloud security experience is required. » (expérience non exigée).
Validation : [x] validé par Tanguy en chat (classe) ; preuves complétées et relues par l’agent.

### SYNTH-004-C — Junior Network Security Analyst
Classe retenue : **adaptée** | Langue : en | Lieu : Bruxelles

Annonce :
> Junior permanent network security position in Brussels for candidates with zero to two years of experience. Work includes Wireshark traffic analysis, firewall rule reviews, Suricata tuning, TLS certificate operations and small Python automation tasks. The team offers a six-month onboarding programme and pairs each newcomer with an experienced analyst.

Faits annotés : contract="permanent", experience_min=0, experience_max=2, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Junior permanent network security position in Brussels for candidates with zero to two years of experience. » (contrat, lieu, junior, expérience).
- « Work includes Wireshark traffic analysis, firewall rule reviews, Suricata tuning, TLS certificate operations and small Python automation tasks. » (missions techniques).
- « The team offers a six-month onboarding programme and pairs each newcomer with an experienced analyst. » (onboarding, mentorat).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-005-C — Junior IAM Engineer
Classe retenue : **adaptée** | Langue : fr | Lieu : Luxembourg

Annonce :
> CDI junior au Luxembourg, accessible avec zéro à un an d'expérience. Vous configurez le SSO, OAuth2 et OpenID Connect, participez au cycle de vie des comptes dans Entra ID et automatisez des contrôles d'accès avec Python. Formation Okta et PAM prévue; les changements sensibles sont revus par un ingénieur confirmé.

Faits annotés : contract="permanent", experience_min=0, experience_max=1, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI junior au Luxembourg, accessible avec zéro à un an d'expérience. » (contrat, lieu, junior, expérience).
- « Vous configurez le SSO, OAuth2 et OpenID Connect, participez au cycle de vie des comptes dans Entra ID et automatisez des contrôles d'accès avec Python. » (missions techniques).
- « Formation Okta et PAM prévue; les changements sensibles sont revus par un ingénieur confirmé. » (formation et supervision).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-006-C — Junior 5G Security Research Engineer
Classe retenue : **adaptée** | Langue : fr | Lieu : Nice

Annonce :
> CDI de premier emploi en R&D sécurité télécom à Nice. Missions: analyse de paquets 5G avec Wireshark, tests sur Open5GS, durcissement Linux, scripts Python et validation de configurations TLS. Le poste accepte les jeunes diplômés et prévoit un accompagnement sur les normes 3GPP; aucune ancienneté professionnelle minimale n'est demandée.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI de premier emploi en R&D sécurité télécom à Nice. » (contrat, lieu, premier emploi).
- « Missions: analyse de paquets 5G avec Wireshark, tests sur Open5GS, durcissement Linux, scripts Python et validation de configurations TLS. » (missions techniques).
- « Le poste accepte les jeunes diplômés et prévoit un accompagnement sur les normes 3GPP; aucune ancienneté professionnelle minimale n'est demandée. » (junior, formation, expérience non exigée).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-007-C — Junior Application Security Engineer
Classe retenue : **adaptée** | Langue : fr | Lieu : Bordeaux

Annonce :
> Poste CDI junior à Bordeaux, de zéro à deux ans d'expérience. Vous réalisez des revues de code Python, des tests web avec Burp Suite, des contrôles OWASP, du SAST SonarQube et du durcissement d'API dans Docker. Une formation AppSec et un binômage avec un senior sont inclus pendant la première année.

Faits annotés : contract="permanent", experience_min=0, experience_max=2, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Poste CDI junior à Bordeaux, de zéro à deux ans d'expérience. » (contrat, lieu, junior, expérience).
- « Vous réalisez des revues de code Python, des tests web avec Burp Suite, des contrôles OWASP, du SAST SonarQube et du durcissement d'API dans Docker. » (missions techniques).
- « Une formation AppSec et un binômage avec un senior sont inclus pendant la première année. » (formation et binômage).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-008-C — Graduate Security Operations Engineer
Classe retenue : **adaptée** | Langue : en | Lieu : Paris

Annonce :
> Permanent graduate security operations programme in Paris for recent graduates with less than one year of professional experience. Rotations cover SOC monitoring, vulnerability management, cloud security and IAM. Tools include Splunk, Linux, Python, AWS and Docker. Training, technical mentoring and a defined engineering role after the programme are guaranteed.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Permanent graduate security operations programme in Paris for recent graduates with less than one year of professional experience. » (contrat, lieu, junior, expérience).
- « Rotations cover SOC monitoring, vulnerability management, cloud security and IAM. » (rotations techniques).
- « Tools include Splunk, Linux, Python, AWS and Docker. » (outils).
- « Training, technical mentoring and a defined engineering role after the programme are guaranteed. » (formation et rôle défini).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-009-C — Junior Vulnerability Management Engineer
Classe retenue : **adaptée** | Langue : en | Lieu : Lausanne

Annonce :
> Permanent junior vulnerability management role in Lausanne, open to applicants with zero to two years of experience. Responsibilities include Nessus and Trivy scanning, technical triage, Linux remediation validation and Python reporting automation. The role sits in the security engineering team and includes weekly coaching from DevSecOps engineers.

Faits annotés : contract="permanent", experience_min=0, experience_max=2, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Permanent junior vulnerability management role in Lausanne, open to applicants with zero to two years of experience. » (contrat, lieu, junior, expérience).
- « Responsibilities include Nessus and Trivy scanning, technical triage, Linux remediation validation and Python reporting automation. » (missions techniques).
- « The role sits in the security engineering team and includes weekly coaching from DevSecOps engineers. » (équipe, progression).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-010-C — Junior Infrastructure Security Engineer
Classe retenue : **adaptée** | Langue : fr | Lieu : Paris

Annonce :
> CDI d'ingénieur infrastructure sécurité à Paris, débutant accepté. Vous administrez Ubuntu, Proxmox et Docker, automatisez avec Ansible et Shell, configurez WireGuard, TLS et le SSO, puis améliorez la supervision. Le périmètre et l'équipe sont connus avant l'embauche et un parcours de formation de six mois est prévu.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI d'ingénieur infrastructure sécurité à Paris, débutant accepté. » (contrat, lieu, accès junior).
- « Vous administrez Ubuntu, Proxmox et Docker, automatisez avec Ansible et Shell, configurez WireGuard, TLS et le SSO, puis améliorez la supervision. » (missions techniques).
- « Le périmètre et l'équipe sont connus avant l'embauche et un parcours de formation de six mois est prévu. » (équipe et formation définies).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-011-I — Senior GRC Consultant
Classe retenue : **incompatible** | Langue : fr | Lieu : Paris

Annonce :
> CDI senior en gouvernance, risques et conformité. Cinq à huit ans d'expérience en cabinet sont exigés. Les missions portent sur ISO 27001, DORA, NIS2, analyses d'écart, politiques et comités de pilotage. Le poste ne comporte ni exploitation technique, ni détection, ni configuration de systèmes de sécurité.

Faits annotés : contract="permanent", experience_min=5, experience_max=8, junior=false, role_nature="governance".
Portes annotées : experience=fail.
Preuves exactes et faits soutenus :
- « CDI senior en gouvernance, risques et conformité. » (contrat, séniorité, GRC).
- « Cinq à huit ans d'expérience en cabinet sont exigés. » (expérience obligatoire).
- « Les missions portent sur ISO 27001, DORA, NIS2, analyses d'écart, politiques et comités de pilotage. » (missions GRC).
- « Le poste ne comporte ni exploitation technique, ni détection, ni configuration de systèmes de sécurité. » (absence de technique).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-012-I — Stage Analyste Cybersécurité
Classe retenue : **incompatible** | Langue : fr | Lieu : Paris

Annonce :
> Stage de fin d'études de six mois réservé aux étudiants conventionnés. Vous aiderez à exécuter des scans Nessus, documenter des vulnérabilités et préparer des rapports. Bien que les missions soient techniques et utilisent Linux et Python, il ne s'agit pas d'un emploi permanent et une convention d'école est obligatoire.

Faits annotés : contract="internship", experience_min=null, junior=null, role_nature="technical".
Portes annotées : contract_type=fail.
Preuves exactes et faits soutenus :
- « Stage de fin d'études de six mois réservé aux étudiants conventionnés. » (stage et statut étudiant).
- « Vous aiderez à exécuter des scans Nessus, documenter des vulnérabilités et préparer des rapports. » (missions techniques).
- « Bien que les missions soient techniques et utilisent Linux et Python, il ne s'agit pas d'un emploi permanent et une convention d'école est obligatoire. » (contrat étudiant obligatoire).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-013-I — Junior Security Engineer
Classe retenue : **incompatible** | Langue : fr | Lieu : Paris

Annonce :
> Malgré l'intitulé junior, le CDI exige trois à cinq ans d'expérience en sécurité. La personne dirigera les revues d'architecture Kubernetes, définira les standards Jenkins, approuvera les exceptions de risque et encadrera deux alternants. Une expérience démontrée de production à grande échelle est obligatoire.

Faits annotés : contract="permanent", experience_min=3, experience_max=5, junior=false, role_nature="technical_lead".
Portes annotées : experience=fail.
Preuves exactes et faits soutenus :
- « Malgré l'intitulé junior, le CDI exige trois à cinq ans d'expérience en sécurité. » (contradiction junior, CDI, expérience obligatoire).
- « La personne dirigera les revues d'architecture Kubernetes, définira les standards Jenkins, approuvera les exceptions de risque et encadrera deux alternants. » (rôle de lead).
- « Une expérience démontrée de production à grande échelle est obligatoire. » (expérience confirmée obligatoire).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-014-I — IT Support Engineer Level 1
Classe retenue : **incompatible** | Langue : en | Lieu : Bruxelles

Annonce :
> Permanent first-line IT support role in Brussels. Work consists of Windows workstation troubleshooting, printer incidents, password resets, Microsoft Office assistance and basic network connectivity tickets. There are no cybersecurity, infrastructure engineering, detection, vulnerability management or security automation responsibilities in this position.

Faits annotés : contract="permanent", experience_min=null, experience_max=null, junior=null, role_nature="support".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Permanent first-line IT support role in Brussels. » (contrat, lieu, support).
- « Work consists of Windows workstation troubleshooting, printer incidents, password resets, Microsoft Office assistance and basic network connectivity tickets. » (missions de support).
- « There are no cybersecurity, infrastructure engineering, detection, vulnerability management or security automation responsibilities in this position. » (absence de mission cyber).
Doit rester inconnu : experience_min, experience_max, junior.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-015-I — Alternance Sécurité Cloud
Classe retenue : **incompatible** | Langue : fr | Lieu : Lyon

Annonce :
> Contrat d'alternance de vingt-quatre mois réservé aux étudiants inscrits dans l'école partenaire. Les missions couvrent AWS, IAM, Docker, Terraform et Python. Le contenu est technique mais le statut étudiant et le rythme école-entreprise sont obligatoires; aucune embauche directe en CDI n'est proposée dans cette annonce.

Faits annotés : contract="apprenticeship", experience_min=null, junior=null, role_nature="technical".
Portes annotées : contract_type=fail.
Preuves exactes et faits soutenus :
- « Contrat d'alternance de vingt-quatre mois réservé aux étudiants inscrits dans l'école partenaire. » (alternance, statut étudiant).
- « Les missions couvrent AWS, IAM, Docker, Terraform et Python. » (missions techniques).
- « Le contenu est technique mais le statut étudiant et le rythme école-entreprise sont obligatoires; aucune embauche directe en CDI n'est proposée dans cette annonce. » (alternance obligatoire, pas de CDI).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-016-I — Full-stack JavaScript Developer
Classe retenue : **incompatible** | Langue : fr | Lieu : Remote France

Annonce :
> CDI de développeur full-stack demandant une à trois années d'expérience. Les missions concernent React, Node.js, PostgreSQL, interfaces produit et optimisation des performances web. L'annonce ne prévoit aucune responsabilité de sécurité, réseau, infrastructure, cloud security ou DevSecOps au-delà du déploiement classique de l'application.

Faits annotés : contract="permanent", experience_min=1, experience_max=3, junior=null, role_nature="development".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI de développeur full-stack demandant une à trois années d'expérience. » (contrat et expérience).
- « Les missions concernent React, Node.js, PostgreSQL, interfaces produit et optimisation des performances web. » (développement hors cybersécurité).
- « L'annonce ne prévoit aucune responsabilité de sécurité, réseau, infrastructure, cloud security ou DevSecOps au-delà du déploiement classique de l'application. » (absence de sécurité technique).
Doit rester inconnu : junior.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-017-I — Consultant Cybersécurité Banque
Classe retenue : **incompatible** | Langue : fr | Lieu : Paris

Annonce :
> Cabinet de conseil recherchant un consultant avec deux à quatre ans d'expérience. Les futures missions dépendront des besoins des clients. Les exemples cités sont analyses de maturité, feuilles de route, présentations de comités et conformité ISO 27001. Aucun premier client, outil technique, environnement ou responsable de progression n'est identifié.

Faits annotés : contract="permanent", experience_min=2, experience_max=4, junior=false, role_nature="vague_consulting".
Portes annotées : experience=fail.
Preuves exactes et faits soutenus :
- « Cabinet de conseil recherchant un consultant avec deux à quatre ans d'expérience. » (expérience en conseil).
- « Les futures missions dépendront des besoins des clients. » (affectation inconnue).
- « Les exemples cités sont analyses de maturité, feuilles de route, présentations de comités et conformité ISO 27001. » (exemples GRC).
- « Aucun premier client, outil technique, environnement ou responsable de progression n'est identifié. » (client, outils et mentor inconnus).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-018-A — Cloud Security Engineer
Classe retenue : **ambiguë / à vérifier** | Langue : en | Lieu : Genève

Annonce :
> Permanent cloud security engineer position in Geneva. Three years of experience is preferred but not mandatory; recent graduates with relevant projects may apply. The advert mentions possible work on AWS IAM, Terraform reviews and Python automation, but says the first assignment will be decided after joining according to client demand. It does not name a confirmed team, mentor or specific first mission. The junior accessibility and technical content of the actual assignment therefore remain uncertain.

Faits annotés : contract="permanent", experience_min=null, experience_preferred=3, junior=true, role_nature="vague_consulting".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Permanent cloud security engineer position in Geneva. » (contrat, lieu).
- « Three years of experience is preferred but not mandatory; recent graduates with relevant projects may apply. » (expérience préférée, accès junior).
- « The advert mentions possible work on AWS IAM, Terraform reviews and Python automation, but says the first assignment will be decided after joining according to client demand. » (missions possibles et affectation inconnue).
- « It does not name a confirmed team, mentor or specific first mission. » (équipe et mentor inconnus).
- « The junior accessibility and technical content of the actual assignment therefore remain uncertain. » (incertitude explicite).
Doit rester inconnu : first_assignment, mentor, confirmed_team.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-019-I — Responsable Sensibilisation Cybersécurité
Classe retenue : **incompatible** | Langue : fr | Lieu : Luxembourg

Annonce :
> CDI de responsable de programme. Une expérience professionnelle confirmée est indispensable pour piloter les campagnes de sensibilisation, organiser les formations obligatoires, produire les indicateurs de conformité et présenter les résultats à la direction. Le rôle ne comprend pas d'analyse technique, de configuration ou d'ingénierie sécurité.

Faits annotés : contract="permanent", experience_min=null, junior=false, role_nature="awareness".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI de responsable de programme. » (contrat et gestion de programme).
- « Une expérience professionnelle confirmée est indispensable pour piloter les campagnes de sensibilisation, organiser les formations obligatoires, produire les indicateurs de conformité et présenter les résultats à la direction. » (senior et missions de sensibilisation).
- « Le rôle ne comprend pas d'analyse technique, de configuration ou d'ingénierie sécurité. » (absence de technique).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-020-I — Remote Security Lead
Classe retenue : **incompatible** | Langue : en | Lieu : Worldwide remote

Annonce :
> Remote security lead contract advertised worldwide, but applicants must already hold work authorization in the United States. Four years of professional experience are required. The role owns incident response, cloud security architecture, vendor risk and management reporting, and supervises a distributed team of analysts.

Faits annotés : contract=null, experience_min=4, junior=false, role_nature="management".
Portes annotées : experience=fail.
Preuves exactes et faits soutenus :
- « Remote security lead contract advertised worldwide, but applicants must already hold work authorization in the United States. » (type exact de contrat indéterminé, autorisation US).
- « Four years of professional experience are required. » (expérience obligatoire).
- « The role owns incident response, cloud security architecture, vendor risk and management reporting, and supervises a distributed team of analysts. » (direction, management).
Doit rester inconnu : contract_type.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-021-A — Cybersecurity Engineer
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Bruxelles

Annonce :
> CDI d'ingénieur cybersécurité à Bruxelles. L'annonce demande une à trois années d'expérience mais précise que les candidatures de jeunes diplômés ayant réalisé des stages significatifs seront étudiées. Missions techniques: Linux hardening, analyse réseau, Python et gestion de vulnérabilités. Le niveau réel attendu et la façon de compter les stages restent ambigus.

Faits annotés : contract="permanent", experience_min=1, experience_max=3, junior=true, role_nature="technical".
Portes annotées : experience=warn.
Preuves exactes et faits soutenus :
- « CDI d'ingénieur cybersécurité à Bruxelles. » (contrat, lieu).
- « L'annonce demande une à trois années d'expérience mais précise que les candidatures de jeunes diplômés ayant réalisé des stages significatifs seront étudiées. » (expérience et dérogation junior).
- « Missions techniques: Linux hardening, analyse réseau, Python et gestion de vulnérabilités. » (technicité).
- « Le niveau réel attendu et la façon de compter les stages restent ambigus. » (niveau attendu incertain).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-022-A — Security Operations Analyst
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Paris

Annonce :
> CDI en opérations de sécurité à Paris. Missions: analyse d'alertes SIEM, investigation Linux et amélioration de règles de détection. L'annonce ne donne aucun nombre d'années, ne mentionne ni junior ni senior et indique seulement que la personne doit être autonome rapidement. Une formation produit est prévue mais le niveau d'accompagnement n'est pas décrit.

Faits annotés : contract="permanent", experience_min=null, junior=null, role_nature="technical".
Portes annotées : experience=unknown.
Preuves exactes et faits soutenus :
- « CDI en opérations de sécurité à Paris. » (contrat, lieu).
- « Missions: analyse d'alertes SIEM, investigation Linux et amélioration de règles de détection. » (missions techniques).
- « L'annonce ne donne aucun nombre d'années, ne mentionne ni junior ni senior et indique seulement que la personne doit être autonome rapidement. » (niveau junior et années inconnus).
- « Une formation produit est prévue mais le niveau d'accompagnement n'est pas décrit. » (formation, mentorat inconnu).
Doit rester inconnu : experience_min, junior, mentoring_level.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-023-A — Junior Platform Security Engineer
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Lausanne

Annonce :
> Titre junior et débutant accepté, mais le poste demande de définir seul l'architecture Kubernetes de production, d'approuver les exceptions de sécurité, d'assurer une astreinte critique et de conseiller les équipes seniors. Les outils Linux, Terraform et Python correspondent au profil, pourtant l'autonomie et l'impact attendus ressemblent à un rôle confirmé.

Faits annotés : contract=null, experience_min=0, junior=true, role_nature="technical_lead".
Portes annotées : experience=warn.
Preuves exactes et faits soutenus :
- « Titre junior et débutant accepté, mais le poste demande de définir seul l'architecture Kubernetes de production, d'approuver les exceptions de sécurité, d'assurer une astreinte critique et de conseiller les équipes seniors. » (accès junior affiché et autonomie de lead).
- « Les outils Linux, Terraform et Python correspondent au profil, pourtant l'autonomie et l'impact attendus ressemblent à un rôle confirmé. » (outils et niveau attendu confirmé).
Doit rester inconnu : contract_type, actual_seniority.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-024-A — Cybersecurity Consultant – Technical Missions
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Paris

Annonce :
> Cabinet recrutant en CDI des profils de zéro à deux ans. L'annonce promet des missions techniques possibles en SOC, cloud security ou pentest, mais le premier client, les outils, le manager et la durée de mission ne sont pas connus. Une période d'intercontrat et des activités de veille ou de présentation commerciale sont également mentionnées.

Faits annotés : contract="permanent", experience_min=0, experience_max=2, junior=true, role_nature="vague_consulting".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Cabinet recrutant en CDI des profils de zéro à deux ans. » (CDI, plage junior).
- « L'annonce promet des missions techniques possibles en SOC, cloud security ou pentest, mais le premier client, les outils, le manager et la durée de mission ne sont pas connus. » (missions possibles, client et outils inconnus).
- « Une période d'intercontrat et des activités de veille ou de présentation commerciale sont également mentionnées. » (intercontrat et commercial).
Doit rester inconnu : first_client, tools, manager, mission_duration.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-025-A — Cloud Security Engineer – Remote Europe
Classe retenue : **ambiguë / à vérifier** | Langue : en | Lieu : Remote Europe

Annonce :
> Entry-level permanent cloud security role described as remote Europe. Tasks include AWS IAM reviews, Terraform checks and Python automation, with good mentoring. The advertisement does not identify the employing country, payroll entity, permitted countries or whether applicants living in Belgium, France or Switzerland can legally be hired.

Faits annotés : contract="permanent", experience_min=0, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Entry-level permanent cloud security role described as remote Europe. » (accès junior, contrat, télétravail).
- « Tasks include AWS IAM reviews, Terraform checks and Python automation, with good mentoring. » (technique et mentorat).
- « The advertisement does not identify the employing country, payroll entity, permitted countries or whether applicants living in Belgium, France or Switzerland can legally be hired. » (pays employeur, pays admissibles inconnus).
Doit rester inconnu : employing_country, payroll_entity, eligible_countries.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-026-A — VIE Security Engineer
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Luxembourg

Annonce :
> Mission VIE de vingt-quatre mois au Luxembourg pour un profil de zéro à un an d'expérience. Le travail est technique: sécurité réseau, Linux, Python, durcissement cloud et gestion de vulnérabilités. Le statut VIE n'est ni un stage ni un CDI classique; son acceptabilité dépend des contraintes personnelles et administratives du candidat.

Faits annotés : contract="vie", experience_min=0, experience_max=1, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Mission VIE de vingt-quatre mois au Luxembourg pour un profil de zéro à un an d'expérience. » (VIE, expérience, lieu).
- « Le travail est technique: sécurité réseau, Linux, Python, durcissement cloud et gestion de vulnérabilités. » (missions techniques).
- « Le statut VIE n'est ni un stage ni un CDI classique; son acceptabilité dépend des contraintes personnelles et administratives du candidat. » (contraintes administratives inconnues).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-027-A — OT Cybersecurity Junior Engineer
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Bordeaux

Annonce :
> CDI junior en cybersécurité industrielle. Les missions couvrent segmentation réseau, inventaire d'actifs, durcissement Windows et Linux et analyses de risques techniques. Une première expérience est souhaitée sans durée minimale. Des déplacements fréquents sur sites industriels et des astreintes sont exigés, mais leur volume exact n'est pas indiqué.

Faits annotés : contract="permanent", experience_min=null, junior=true, role_nature="technical".
Portes annotées : experience=pass.
Preuves exactes et faits soutenus :
- « CDI junior en cybersécurité industrielle. » (contrat, junior).
- « Les missions couvrent segmentation réseau, inventaire d'actifs, durcissement Windows et Linux et analyses de risques techniques. » (missions techniques).
- « Une première expérience est souhaitée sans durée minimale. » (expérience souhaitée sans minimum).
- « Des déplacements fréquents sur sites industriels et des astreintes sont exigés, mais leur volume exact n'est pas indiqué. » (déplacements et astreintes sans volume).
Doit rester inconnu : travel_volume, on_call_volume.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-028-I — Security Analyst
Classe retenue : **incompatible** | Langue : en | Lieu : Genève

Annonce :
> The visible description presents hands-on security monitoring, Linux investigations, network traffic analysis and Python automation in Geneva. The title does not disclose the contract type or experience level. The source metadata labels the position as an internship requiring student status, despite the generic technical description.

Faits annotés : contract="internship", experience_min=null, junior=null, role_nature="technical".
Portes annotées : contract_type=fail.
Preuves exactes et faits soutenus :
- « The visible description presents hands-on security monitoring, Linux investigations, network traffic analysis and Python automation in Geneva. » (missions techniques, lieu).
- « The title does not disclose the contract type or experience level. » (titre sans type de contrat).
- « The source metadata labels the position as an internship requiring student status, despite the generic technical description. » (métadonnée stage, statut étudiant).
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-029-A — Network Security Analyst
Classe retenue : **ambiguë / à vérifier** | Langue : en | Lieu : Bruxelles

Annonce :
> Junior permanent network security position in Brussels for zero to two years of experience. Tasks include Check Point and Fortinet firewall administration, IDS tuning, segmentation and DDoS mitigation. The role has an on-call rotation every three weeks, but the advertisement does not state compensation, night frequency or the level of autonomy expected during incidents.

Faits annotés : contract="permanent", experience_min=0, experience_max=2, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « Junior permanent network security position in Brussels for zero to two years of experience. » (contrat, junior, lieu, expérience).
- « Tasks include Check Point and Fortinet firewall administration, IDS tuning, segmentation and DDoS mitigation. » (missions techniques).
- « The role has an on-call rotation every three weeks, but the advertisement does not state compensation, night frequency or the level of autonomy expected during incidents. » (astreinte et conditions inconnues).
Doit rester inconnu : on_call_compensation, night_frequency, incident_autonomy.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

### SYNTH-030-A — Junior SOC Analyst – English Team
Classe retenue : **ambiguë / à vérifier** | Langue : fr | Lieu : Bruxelles

Annonce :
> CDI junior à Bruxelles, ouvert aux débutants avec zéro à deux ans d'expérience. Analyse d'alertes Elastic, investigations Linux, Wireshark et règles de détection Python. L'équipe et tous les clients travaillent exclusivement en anglais. L'annonce exige un niveau professionnel courant mais ne précise aucun test ni niveau CECRL.

Faits annotés : contract="permanent", experience_min=0, experience_max=2, junior=true, role_nature="technical".
Portes annotées : aucune (hors portes annotées).
Preuves exactes et faits soutenus :
- « CDI junior à Bruxelles, ouvert aux débutants avec zéro à deux ans d'expérience. » (contrat, junior, lieu, expérience).
- « Analyse d'alertes Elastic, investigations Linux, Wireshark et règles de détection Python. » (missions techniques).
- « L'équipe et tous les clients travaillent exclusivement en anglais. » (anglais exclusif).
- « L'annonce exige un niveau professionnel courant mais ne précise aucun test ni niveau CECRL. » (niveau linguistique non vérifiable).
Doit rester inconnu : candidate_english_level, required_CEFR_level.
Validation : [x] relu par l’agent à la demande de Tanguy ; non validé indépendamment.

## Après cette relecture

Le corpus reste synthétique et sa relecture par l’agent n’est pas une validation indépendante. Les changements de corrigé et de texte rendent les anciens rapports de benchmark non comparables. Recalculer les mesures v2.5 et v2.6 sur **cette même révision** avant d’attribuer un écart au moteur ; garder les rapports et leurs révisions de corpus. Une offre réelle en désaccord mérite une nouvelle annotation, pas une modification opportuniste du corrigé pour améliorer la métrique.
