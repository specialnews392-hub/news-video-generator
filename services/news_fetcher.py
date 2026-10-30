"""
News Fetcher - Searches for fresh, non-repeating news using Direct Agency Feeds (Interfax, Kommersant, Vedomosti, Rambler, Lenta),
Google News RSS with URL decoding, DuckDuckGo news search, and NewsAPI.
Tracks history of used articles, sub-angles, and video titles to guarantee 100% variety.
Includes an intelligent Acute Topic Expander with pools of sharp investigative angles for broad topics.
"""
import asyncio
import re
import json
import random
import logging
import base64
import email.utils
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, parse_qs, urlparse
from pathlib import Path

import httpx
import feedparser
from bs4 import BeautifulSoup
import trafilatura

import config

logger = logging.getLogger(__name__)

HISTORY_FILE = config.OUTPUT_DIR / "news_history.json"


# =====================================================================
# ACUTE TOPIC CATALOG: Deep pool of sharp, investigative angles
# =====================================================================
ACUTE_TOPIC_CATALOG = {
    "migration_de": {
        "name": "Migration & Asylpolitik Deutschland",
        "patterns": ["migration", "asyl", "flücht", "abschieb", "grenzkontroll", "grenze", "grenzen", "einwander", "zuwander", "geas", "bamf"],
        "sub_angles": [
            {
                "id": "bezahlkarte",
                "title": "Bezahlkarte für Asylbewerber & Bargeld-Stopp",
                "title_ru": "Безналичные карты для беженцев и отмена выплат наличными",
                "desc_ru": "Ограничение снятия наличных в землях, переход на безналичные выплаты и споры о расходах.",
                "queries": ["Bezahlkarte Asylbewerber Bargeldstopp Länder", "Bezahlkarte Sachleistungen Flüchtlinge"],
                "badge": "💳 Bezahlkarte",
                "hook_ideas": ["BEZAHLKARTE-BESCHLUSS", "BARGELD-STOPP", "BEZAHLKARTE-BEBEN"],
                "hook_ideas_ru": {"BEZAHLKARTE-BESCHLUSS": "РЕШЕНИЕ О БЕЗНАЛИЧНЫХ КАРТАХ", "BARGELD-STOPP": "ОТМЕНА НАЛИЧНЫХ ВЫПЛАТ", "BEZAHLKARTE-BEBEN": "КАРТОЧНЫЙ РЕЖИМ"},
            },
            {
                "id": "grenzkontrollen",
                "title": "Stationäre Grenzkontrollen & Zurückweisungen",
                "title_ru": "Стационарный контроль на границах и развороты въезжающих",
                "desc_ru": "Операции Федеральной полиции на границах с Польшей, Чехией и Австрией: рекордное число отказов во въезде.",
                "queries": ["Bundespolizei Grenzkontrollen Zurückweisungen Polen Tschechien", "Grenzkontrollen Deutschland Zahlen Faeser"],
                "badge": "🛂 Grenzen",
                "hook_ideas": ["GRENZ-ALARM", "ZURÜCKWEISUNGS-REKORD", "BUNDESPOLIZEI GREIFT DURCH"],
                "hook_ideas_ru": {"GRENZ-ALARM": "ТРЕВОГА НА ГРАНИЦАХ", "ZURÜCKWEISUNGS-REKORD": "РЕКОРД РАЗВОРОТОВ НА ВЪЕЗДЕ", "BUNDESPOLIZEI GREIFT DURCH": "ПОЛИЦИЯ БЕРЕТ ПОД КОНТРОЛЬ"},
            },
            {
                "id": "abschiebungen_dublin",
                "title": "Abschiebungen & Dublin-Blockaden in Europa",
                "title_ru": "Высылка преступников и блокада Дублинских соглашений в ЕС",
                "desc_ru": "Спецрейсы в Афганистан и Сирию, отказ Италии и Греции принимать беженцев обратно по Дублину.",
                "queries": ["Abschiebungen Afghanistan Syrien Straftäter Flug", "Dublin Überstellung Italien Griechenland Blockade"],
                "badge": "✈️ Abschiebungen",
                "hook_ideas": ["ABSCHIEBE-KONFLIKT", "DUBLIN-KOLLAPS", "ABSCHIEBE-FLUG"],
                "hook_ideas_ru": {"ABSCHIEBE-KONFLIKT": "КОНФЛИКТ ВОКРУГ ДЕПОРТАЦИЙ", "DUBLIN-KOLLAPS": "КРАХ ДУБЛИНСКИХ ПРАВИЛ", "ABSCHIEBE-FLUG": "СПЕЦРЕЙС ПО ВЫСЫЛКЕ"},
            },
            {
                "id": "kommunen_notstand",
                "title": "Überlastung der Kommunen & Brandbriefe der Landräte",
                "title_ru": "Перегрузка муниципалитетов и тревожные письма мэров в Берлин",
                "desc_ru": "Переполненные приюты и спортзалы, дефицит местных бюджетов и требования прекратить приём.",
                "queries": ["Kommunen Asyl Notunterkünfte Überlastung Landräte", "Brandbrief Landkreise Flüchtlinge Hallen"],
                "badge": "🏛️ Kommunen",
                "hook_ideas": ["KOMMUNEN-NOTSTAND", "BRANDBRIEF AN BERLIN", "AUFNAHME-STOPP"],
                "hook_ideas_ru": {"KOMMUNEN-NOTSTAND": "КРИЗИС В МУНИЦИПАЛИТЕТАХ", "BRANDBRIEF AN BERLIN": "УЛЬТИМАТУМ МЭРОВ БЕРЛИНУ", "AUFNAHME-STOPP": "ПРЕДЕЛ ПРИЁМА ИСЧЕРПАН"},
            },
            {
                "id": "geas_drittstaaten",
                "title": "EU-Asylreform (GEAS) & Drittstaaten-Modell",
                "title_ru": "Реформа убежища в ЕС (GEAS) и лагеря в третьих странах",
                "desc_ru": "Рассмотрение заявок на убежище за пределами ЕС по итальянской модели в Албании и схеме Руанды.",
                "queries": ["GEAS Reform EU Drittstaaten Albanien Modell", "Asylverfahren außerhalb Europas Drittstaaten"],
                "badge": "🇪🇺 EU-Reform",
                "hook_ideas": ["GEAS-BEBEN", "DRITTSTAATEN-PLAN", "EU-ASYLKOMPROMISS"],
                "hook_ideas_ru": {"GEAS-BEBEN": "РЕФОРМА УБЕЖИЩА В ЕС", "DRITTSTAATEN-PLAN": "ПЛАН ЛАГЕРЕЙ ВНЕ ЕС", "EU-ASYLKOMPROMISS": "НОВЫЙ КОМПРОМИСС ЕВРОСОЮЗА"},
            },
            {
                "id": "sicherheit_waffenrecht",
                "title": "Sicherheitsdebatte, Messerverbote & Haftbefehle",
                "title_ru": "Дебаты о безопасности, запрет холодного оружия и ордера на арест",
                "desc_ru": "Ужесточение правил ношения ножей после атак, статистика тяжких преступлений и неисполненные ордера.",
                "queries": ["Messerverbot Asylunterkünfte Sicherheitsdebatte BKA", "Offene Haftbefehle Asyl Kriminalstatistik"],
                "badge": "🚨 Sicherheit",
                "hook_ideas": ["SICHERHEITS-SCHOCK", "MESSERVERBOT-BESCHLUSS", "BKA-LAGEBERICHT"],
                "hook_ideas_ru": {"SICHERHEITS-SCHOCK": "ШОК В СФЕРЕ БЕЗОПАСНОСТИ", "MESSERVERBOT-BESCHLUSS": "ЖЕСТКИЙ ЗАПРЕТ ОРУЖИЯ", "BKA-LAGEBERICHT": "ОТЧЕТ КРИМИНАЛЬНОЙ ПОЛИЦИИ"},
            },
            {
                "id": "bamf_justiz",
                "title": "BAMF-Statistik & Klageflut an Verwaltungsgerichten",
                "title_ru": "Статистика ведомства BAMF и лавина судебных исков",
                "desc_ru": "Перегрузка административных судов Германии исками об отказе в убежище, многолетние процессы.",
                "queries": ["BAMF Asylanträge Zahlen Verwaltungsgerichte Klagen", "BAMF Asylverfahren Dauer Gerichte Überlastung"],
                "badge": "⚖️ BAMF & Justiz",
                "hook_ideas": ["BAMF-ZAHLEN", "KLAGE-FLUT AN GERICHTEN", "ASYL-KOLLAPS"],
                "hook_ideas_ru": {"BAMF-ZAHLEN": "ЦИФРЫ ВЕДОМСТВА BAMF", "KLAGE-FLUT AN GERICHTEN": "ЗАВАЛ СУДОВ ИСКАМИ", "ASYL-KOLLAPS": "КОЛЛАПС РАССМОТРЕНИЯ ДЕЛ"},
            },
            {
                "id": "merz_ultimatum",
                "title": "Friedrich Merz / Union Ultimatum an die Bundesregierung",
                "title_ru": "Ультиматум Фридриха Мерца (ХДС) правительству Шольца",
                "desc_ru": "Требование объявить режим ЧС по статье 72 договора ЕС и разворачивать беженцев на границе.",
                "queries": ["Friedrich Merz Asyl Notlage Zurückweisung Union", "Merz Faeser Asylgipfel Ultimatum"],
                "badge": "⚡ Merz & Union",
                "hook_ideas": ["MERZ-ULTIMATUM", "UNIONS-HAMMER", "ASYL-BRUCH IN BERLIN"],
                "hook_ideas_ru": {"MERZ-ULTIMATUM": "УЛЬТИМАТУМ МЕРЦА ПРАВИТЕЛЬСТВУ", "UNIONS-HAMMER": "АТАКА ОППОЗИЦИИ ХДС", "ASYL-BRUCH IN BERLIN": "РАЗРЫВ ПЕРЕГОВОРОВ ПО МИГРАЦИИ"},
            },
            {
                "id": "schleuser",
                "title": "Schleuserkriminalität & Razzien der Bundespolizei",
                "title_ru": "Контрабанда людей и масштабные рейды Федеральной полиции",
                "desc_ru": "Балканский транзит, аресты организаторов нелегальных перевозок и ликвидация теневых схем.",
                "queries": ["Schleuser Bundespolizei Razzia Festnahmen Schlepper", "Balkanroute Schleuserbanden Ermittlungen"],
                "badge": "⛓️ Schleuser",
                "hook_ideas": ["SCHLEUSER-RAZZIA", "BUNDESPOLIZEI-SCHLAG", "SCHLEPPER-NETZWERK"],
                "hook_ideas_ru": {"SCHLEUSER-RAZZIA": "ОБЛАВА НА ПЕРЕВОЗЧИКОВ", "BUNDESPOLIZEI-SCHLAG": "СПЕЦОПЕРАЦИЯ ПОЛИЦИИ", "SCHLEPPER-NETZWERK": "РАЗГРОМ СЕТИ КОНТРАБАНДИСТОВ"},
            },
            {
                "id": "staatsbuergerschaft",
                "title": "Turbo-Einbürgerung & Doppelpass-Streit",
                "title_ru": "Споры вокруг ускоренного гражданства и двойного паспорта",
                "desc_ru": "Снижение срока получения гражданства ФРГ до 3–5 лет, критерии интеграции и лишение паспортов за экстремизм.",
                "queries": ["Staatsangehörigkeitsrecht Einbürgerung Doppelpass Reform", "Einbürgerung Kriterien Passentzug Debatte"],
                "badge": "📜 Einbürgerung",
                "hook_ideas": ["DOPPELPASS-STREIT", "EINBÜRGERUNGS-DEBATTE", "PASS-REFORM"],
                "hook_ideas_ru": {"DOPPELPASS-STREIT": "БИТВА ЗА ДВОЙНОЙ ПАСПОРТ", "EINBÜRGERUNGS-DEBATTE": "ДЕБАТЫ О НОВОМ ГРАЖДАНСТВЕ", "PASS-REFORM": "ПАСПОРТНАЯ РЕФОРМА"},
            },
            {
                "id": "ukraine_buergergeld",
                "title": "Bürgergeld-Debatte für Ukraine-Geflüchtete",
                "title_ru": "Дебаты о лишении выплат Bürgergeld беженцев из Украины",
                "desc_ru": "Требования оппозиции и коалиции перевести украинцев на базовые пособия AsylbLG из-за низкой занятости.",
                "queries": ["Bürgergeld Ukraine Flüchtlinge AsylbLG Debatte", "Kritik Bürgergeld Ukrainer Arbeitsquote"],
                "badge": "🇺🇦 Ukraine & Hilfen",
                "hook_ideas": ["BÜRGERGELD-STOPP UKRAINE", "ASYLBLG-WENDE", "HILFEN-KÜRZUNG"],
                "hook_ideas_ru": {"BÜRGERGELD-STOPP UKRAINE": "ОТМЕНА BÜRGERGELD ДЛЯ УКРАИНЦЕВ", "ASYLBLG-WENDE": "ПЕРЕВОД НА СТАНДАРТНЫЕ ПОСОБИЯ", "HILFEN-KÜRZUNG": "УРЕЗАНИЕ ВЫПЛАТ БЕЖЕНЦАМ"},
            },
            {
                "id": "fachkraefte_chancenkarte",
                "title": "Chancenkarte & Fachkräfte-Paradoxon",
                "title_ru": "Карта возможностей (Chancenkarte) и парадокс нехватки кадров",
                "desc_ru": "Балльная система въезда для специалистов из третьих стран на фоне огромных очередей в консульствах ФРГ.",
                "queries": ["Chancenkarte Fachkräfteeinwanderung Punktesystem Visa", "Fachkräftemangel Bürokratie Visa Ausländerbehörde"],
                "badge": "💼 Chancenkarte",
                "hook_ideas": ["CHANCENKARTE-CHAOS", "FACHKRÄFTE-HAMMER", "VISA-SKANDAL"],
                "hook_ideas_ru": {"CHANCENKARTE-CHAOS": "ХАОС С КАРТАМИ ВОЗМОЖНОСТЕЙ", "FACHKRÄFTE-HAMMER": "ПАРАДОКС ДЕФИЦИТА СПЕЦИАЛИСТОВ", "VISA-SKANDAL": "ВИЗОВЫЕ ОЧЕРЕДИ В ФРГ"},
            },
            {
                "id": "familiennachzug",
                "title": "Familiennachzug & subsidiärer Schutz",
                "title_ru": "Ограничение воссоединения семей для лиц с субсидиарной защитой",
                "desc_ru": "Спор в Бундестаге об отмене квоты в 1000 человек в месяц и нагрузке на школы и детсады.",
                "queries": ["Familiennachzug subsidiärer Schutz Asylbewerber Aussetzung", "Familiennachzug Kontingent Streit Koalition"],
                "badge": "👨‍👩‍👧 Familiennachzug",
                "hook_ideas": ["FAMILIENNACHZUG-STOPP", "SUBSIDIÄRER SCHUTZ STREIT", "ASYLGIPFEL-BESCHLUSS"],
                "hook_ideas_ru": {"FAMILIENNACHZUG-STOPP": "ЗАПРЕТ ВОССОЕДИНЕНИЯ СЕМЕЙ", "SUBSIDIÄRER SCHUTZ STREIT": "БИТВА ЗА СУБСИДИАРНУЮ ЗАЩИТУ", "ASYLGIPFEL-BESCHLUSS": "РЕШЕНИЕ ПО СЕМЕЙНЫМ ВИЗАМ"},
            },
            {
                "id": "asylgipfel_finanzen",
                "title": "Milliarden-Streit: Bund vs. Länder über Flüchtlingskosten",
                "title_ru": "Битва за миллиарды: Земли требуют денег на мигрантов у Берлина",
                "desc_ru": "Конференция премьер-министров Земель (MPK) и конфликт с Минфином из-за подушевого финансирования 7500 евро.",
                "queries": ["Flüchtlingskosten Bund Länder MPK Streit Milliarden", "Asylkosten Bund Länder Pauschale Finanzen"],
                "badge": "💰 Kosten & Länder",
                "hook_ideas": ["MILLIARDEN-STREIT", "BUND-LÄNDER-BRUCH", "ASYL-KOSTEN-SCHOCK"],
                "hook_ideas_ru": {"MILLIARDEN-STREIT": "СПОР ИЗ-ЗА МИЛЛИАРДОВ НА БЕЖЕНЦЕВ", "BUND-LÄNDER-BRUCH": "РАЗРЫВ ЗЕМЕЛЬ И БЕРЛИНА", "ASYL-KOSTEN-SCHOCK": "ШОКОВЫЕ РАСХОДЫ НА ПРИЁМ"},
            },
            {
                "id": "rueckfuehrung_abkommen",
                "title": "Migrationsabkommen mit der Türkei, Usbekistan & Kenia",
                "title_ru": "Миграционные сделки со спецпредставителем Штампом",
                "desc_ru": "Двусторонние договоры: легальный наём рабочих в обмен на беспрепятственную депортацию нелегалов.",
                "queries": ["Migrationsabkommen Joachim Stamp Kenia Usbekistan", "Rückführung Abkommen Türkei Abschiebungen"],
                "badge": "🤝 Abkommen",
                "hook_ideas": ["MIGRATIONS-DEAL", "STAMP-ABKOMMEN", "RÜCKFÜHRUNGS-PAKT"],
                "hook_ideas_ru": {"MIGRATIONS-DEAL": "ТАЙНЫЕ МИГРАЦИОННЫЕ СДЕЛКИ", "STAMP-ABKOMMEN": "ДОГОВОР О ВОЗВРАТЕ НЕИЗВЕСТНЫХ", "RÜCKFÜHRUNGS-PAKT": "ПАКТ О ВЫСЫЛКЕ НЕКУДА"},
            },
            {
                "id": "bka_kriminalitaet",
                "title": "BKA-Lagebild: Ausländerkriminalität & Mehrfachtäter",
                "title_ru": "Спецотчет BKA: статистика преступности и рецидивисты",
                "desc_ru": "Данные Федерального ведомства криминальной полиции о доле подозреваемых иностранцев и споры о высылке.",
                "queries": ["BKA Kriminalstatistik Ausländeranteil Straftaten Mehrfachtäter", "Kriminalitätslage BKA Asylbewerber Statistik"],
                "badge": "📊 BKA-Zahlen",
                "hook_ideas": ["BKA-BERICHT", "KRIMINALITÄTS-SCHOCK", "MEHRFACHTÄTER-ALARM"],
                "hook_ideas_ru": {"BKA-BERICHT": "ГРОМКИЙ ОТЧЕТ BKA", "KRIMINALITÄTS-SCHOCK": "ШОК КРИМИНАЛЬНОЙ СТАТИСТИКИ", "MEHRFACHTÄTER-ALARM": "УДАР ПО ОПАСНЫМ РЕЦИДИВИСТАМ"},
            },
            {
                "id": "schengen_krise",
                "title": "Schengen-Krise: Streit mit Polen & Österreich über Grenzkontrollen",
                "title_ru": "Кризис Шенгена: протесты Польши и Австрии против проверок ФРГ",
                "desc_ru": "Дональд Туск обвиняет Берлин в нарушении европейского права из-за отказов на германо-польской границе.",
                "queries": ["Donald Tusk Deutschland Grenzkontrollen Kritik Polen", "Österreich Grenzkontrollen Zurückweisung Nehammer"],
                "badge": "🇪🇺 Schengen-Streit",
                "hook_ideas": ["SCHENGEN-KRISE", "TUSK-KRITIK AN BERLIN", "GRENZ-STREIT EUROPA"],
                "hook_ideas_ru": {"SCHENGEN-KRISE": "КРИЗИС ШЕНГЕНСКОЙ ЗОНЫ", "TUSK-KRITIK AN BERLIN": "ПРОТЕСТ ПОЛЬШИ БЕРЛИНУ", "GRENZ-STREIT EUROPA": "СКАНДАЛ НА ГРАНИЦАХ ЕС"}
            },
            {
                "id": "notunterkuenfte_zelte",
                "title": "Zeltstädte, Turnhallen & Hotels für Asylbewerber",
                "title_ru": "Палаточные лагеря, спортзалы и аренда отелей под приюты",
                "desc_ru": "Критическая нехватка жилья в городах: миллионные расходы муниципалитетов на временные контейнеры.",
                "queries": ["Notunterkünfte Zelte Flüchtlinge Turnhallen Kommunen", "Containerdörfer Asylbewerber Kosten Städte"],
                "badge": "⛺ Notunterkünfte",
                "hook_ideas": ["ZELTSTADT-NOTSTAND", "TURNHALLEN-BELEGUNG", "WOHN-KRISE ASYL"],
                "hook_ideas_ru": {"ZELTSTADT-NOTSTAND": "ПАЛАТОЧНЫЕ ГОРОДКИ В ФРГ", "TURNHALLEN-BELEGUNG": "ЗАНЯТЫЕ СПОРТЗАЛЫ ШКОЛ", "WOHN-KRISE ASYL": "ЖИЛИЩНЫЙ КОЛЛАПС ПРИЮТОВ"},
            },
            {
                "id": "job_turbo",
                "title": "Job-Turbo für Geflüchtete: Zwischenbilanz & Kritik",
                "title_ru": "Программа «Job-Turbo»: проверка результатов и критика",
                "desc_ru": "Инициатива министра труда Хубертуса Хайля по скорейшему трудоустройству беженцев: барьеры языка и бюрократия.",
                "queries": ["Job-Turbo Hubertus Heil Geflüchtete Arbeitsmarkt Bilanz", "Job-Turbo Kritik Jobcenter Vermittlung"],
                "badge": "💼 Job-Turbo",
                "hook_ideas": ["JOB-TURBO-BILANZ", "ARBEITSMARKT-BREMSE", "HEIL-OFFENSIVE"],
                "hook_ideas_ru": {"JOB-TURBO-BILANZ": "ИТОГИ ПРОГРАММЫ JOB-TURBO", "ARBEITSMARKT-BREMSE": "ТОРМОЖЕНИЕ ИНТЕГРАЦИИ", "HEIL-OFFENSIVE": "ТРЕБОВАНИЯ МИНТРУДА ФРГ"},
            },
            {
                "id": "abschiebegewahrsam",
                "title": "Fehlende Abschiebehaftplätze & Untertauchen vor Flügen",
                "title_ru": "Дефицит мест в депортационных изоляторах и побеги от высылки",
                "desc_ru": "Тысячи депортаций срываются в последний момент из-за неявки и отсутствия мест в изоляторах высылки (Abschiebehaft).",
                "queries": ["Abschiebehaft Plätze Mangel Ausreisepflichtige", "Abschiebungen scheitern untergetaucht Zahlen"],
                "badge": "🏢 Abschiebehaft",
                "hook_ideas": ["ABSCHIEBEHAFT-MANGEL", "UNTERTAUCH-SKANDAL", "FLUCHT VOR ABSCHIEBUNG"],
                "hook_ideas_ru": {"ABSCHIEBEHAFT-MANGEL": "НЕХВАТКА ИЗОЛЯТОРОВ ВЫСЫЛКИ", "UNTERTAUCH-SKANDAL": "СРЫВ СПЕЦРЕЙСОВ ДЕПОРТАЦИИ", "FLUCHT VOR ABSCHIEBUNG": "ПОБЕГИ ОТ ВЫСЫЛКИ ИЗ ФРГ"},
            },
            {
                "id": "scholz_grosser_stil",
                "title": "Olaf Scholz: 'Im großen Stil abschieben' – Anspruch vs. Realität",
                "title_ru": "Курс Шольца: «Высылать в крупных масштабах» — слова и реальность",
                "desc_ru": "Анализ исполнения громкого обещания канцлера в журнале Spiegel и реальные цифры фактических высылок.",
                "queries": ["Olaf Scholz im großen Stil abschieben Realität Spiegel", "Kanzler Scholz Asylkurs Abschiebegesetz"],
                "badge": "🏛️ Scholz-Kurs",
                "hook_ideas": ["SCHOLZ-VERSPRECHEN", "ABSCHIEBE-REALITÄT", "KANZLER-KURS ASYL"],
                "hook_ideas_ru": {"SCHOLZ-VERSPRECHEN": "ОБЕЩАНИЕ ОЛАФА ШОЛЬЦА", "ABSCHIEBE-REALITÄT": "РЕАЛЬНОСТЬ ДЕПОРТАЦИЙ В ФРГ", "KANZLER-KURS ASYL": "МИГРАЦИОННАЯ ЛИНИЯ КАНЦЛЕРА"},
            },
            {
                "id": "jugendliche_umf",
                "title": "Unbegleitete minderjährige Flüchtlinge (UMF) & Jugendämter",
                "title_ru": "Несовершеннолетние беженцы без опеки (UMF) и перегрузка Jugendamt",
                "desc_ru": "Колоссальные расходы муниципалитетов (до 5000 евро в месяц на подростка) и нехватка опекунов и педагогов.",
                "queries": ["Unbegleitete minderjährige Flüchtlinge UMF Jugendamt Überlastung", "UMF Asyl Kosten Jugendhilfe Betreuung"],
                "badge": "🧒 UMF & Jugend",
                "hook_ideas": ["JUGENDAMT-KOLLAPS", "UMF-KOSTEN-SCHOCK", "MINDERJÄHRIGE ASYL"],
                "hook_ideas_ru": {"JUGENDAMT-KOLLAPS": "ПЕРЕГРУЗКА ДЕТСКИХ ВЕДОМСТВ", "UMF-KOSTEN-SCHOCK": "ШОК РАСХОДОВ НА ОПЕКУ", "MINDERJÄHRIGE ASYL": "ПОДРОСТКИ БЕЗ ОПЕКУНОВ В ФРГ"},
            },
        ],
    },
    "rente_soziales_de": {
        "name": "Rente, Bürgergeld & Sozialreformen",
        "patterns": ["rente", "bürgergeld", "buergergeld", "sozial", "rentenpaket", "heil", "lindner", "arbeitslos"],
        "sub_angles": [
            {
                "id": "buergergeld_sanktionen",
                "title": "Bürgergeld-Sanktionen & Nullrunde für Verweigerer",
                "title_ru": "Санкции по Bürgergeld и нулевая индексация для отказников",
                "desc_ru": "Ужесточение правил Jobcenter, лишение выплат за отказ от работы и проверка скрытого имущества.",
                "queries": ["Bürgergeld Sanktionen Arbeitsverweigerer Jobcenter", "Bürgergeld Reform Verschärfung Vermögensprüfung"],
                "badge": "💶 Bürgergeld",
                "hook_ideas": ["BÜRGERGELD-BEBEN", "NULLRUNDE-BESCHLUSS", "JOBCENTER-VERSCHÄRFUNG"],
                "hook_ideas_ru": {"BÜRGERGELD-BEBEN": "УЖЕСТОЧЕНИЕ ВЫПЛАТ BÜRGERGELD", "NULLRUNDE-BESCHLUSS": "НУЛЕВАЯ ИНДЕКСАЦИЯ", "JOBCENTER-VERSCHÄRFUNG": "ЖЕСТКИЕ САНКЦИИ ДЛЯ ОТКАЗНИКОВ"},
            },
            {
                "id": "rentenpaket_zwei",
                "title": "Rentenpaket II & Generationenkapital",
                "title_ru": "Пакет пенсионных реформ II и конфликт поколений",
                "desc_ru": "Рост страховых взносов, инвестирование пенсионных средств в акции и критика экономистов.",
                "queries": ["Rentenpaket II Generationenkapital Kritik Ökonomen", "Rentenbeitrag Anstieg Generationenkapital Streit"],
                "badge": "📈 Rentenpaket",
                "hook_ideas": ["RENTEN-BEBEN", "GENERATIONEN-KONFLIKT", "RENTEN-SCHOCK"],
                "hook_ideas_ru": {"RENTEN-BEBEN": "ПЕНСИОННАЯ РЕФОРМА В ФРГ", "GENERATIONEN-KONFLIKT": "КОНФЛИКТ ПОКОЛЕНИЙ И ВЗНОСОВ", "RENTEN-SCHOCK": "ШОКОВЫЙ РОСТ ВЗНОСОВ"},
            },
            {
                "id": "renteneintrittsalter",
                "title": "Debatte um Renteneintrittsalter (Rente mit 68 / 70)",
                "title_ru": "Повышение пенсионного возраста (выход на пенсию в 68–70 лет)",
                "desc_ru": "Требования бизнеса отменить досрочный выход на пенсию в 63 года из-за острого дефицита кадров.",
                "queries": ["Rentenalter Anstieg Rente mit 70 Wirtschaft", "Rente mit 63 Abschaffung Fachkräftemangel"],
                "badge": "⏳ Rentenalter",
                "hook_ideas": ["RENTENALTER-HAMMER", "RENTE MIT 70", "BEITRAGS-ALARM"],
                "hook_ideas_ru": {"RENTENALTER-HAMMER": "ПЕНСИЯ В 70 ЛЕТ", "RENTE MIT 70": "ПОВЫШЕНИЕ ПЕНСИОННОГО ВОЗРАСТА", "BEITRAGS-ALARM": "УГРОЗА ДЕФИЦИТА ПЕНСИОННОГО ФОНДА"},
            },
            {
                "id": "schwarzarbeit",
                "title": "Schwarzarbeit & Missbrauch von Sozialleistungen",
                "title_ru": "Нелегальная занятость и злоупотребления соцпособиями",
                "desc_ru": "Масштабные рейды таможни (Zoll) по проверке получателей пособий, занятых на теневом рынке.",
                "queries": ["Schwarzarbeit Finanzkontrolle Razzia Sozialbetrug", "Bürgergeld Missbrauch Kontrollen Zoll"],
                "badge": "🔍 Kontrollen",
                "hook_ideas": ["ZOLL-RAZZIA", "SCHWARZARBEIT-SCHLAG", "SOZIALBETRUG-ENDE"],
                "hook_ideas_ru": {"ZOLL-RAZZIA": "РЕЙДЫ ТАМОЖНИ ПО ПОСОБИЯМ", "SCHWARZARBEIT-SCHLAG": "УДАР ПО ТЕНЕВОЙ ЗАНЯТОСТИ", "SOZIALBETRUG-ENDE": "КОНЕЦ ПОСОБИЙ ВКОНВЕРТАХ"},
            },
            {
                "id": "pflegeversicherung_kollaps",
                "title": "Pflegeversicherung: Milliarden-Defizit & Beitragsschock",
                "title_ru": "Страхование по уходу (Pflege): дефицит миллиардов и скачок взносов",
                "desc_ru": "Угроза неплатежеспособности фонда ухода за больными и неизбежный рост отчислений с зарплат немцев.",
                "queries": ["Pflegeversicherung Defizit Beitragserhöhung Lauterbach", "Pflegeversicherung Milliardenloch Pleite"],
                "badge": "🏥 Pflege-Alarm",
                "hook_ideas": ["PFLEGE-BEBEN", "BEITRAGS-SCHOCK", "MILLIARDEN-LOCH PFLEGE"],
                "hook_ideas_ru": {"PFLEGE-BEBEN": "КРИЗИС СТРАХОВАНИЯ УХОДА", "BEITRAGS-SCHOCK": "ШОКОВЫЙ РОСТ ВЗНОСОВ", "MILLIARDEN-LOCH PFLEGE": "ДЫРА В МИЛЛИАРДЫ В МЕДСТРАХЕ"},
            },
            {
                "id": "rentenbesteuerung",
                "title": "Doppelbesteuerung der Renten vor Gericht",
                "title_ru": "Двойное налогообложение пенсий: иски пенсионеров в судах",
                "desc_ru": "Рост налоговой нагрузки на пожилых людей в ФРГ и требования отменить несправедливые вычеты.",
                "queries": ["Doppelbesteuerung Renten Bundesfinanzhof Klage", "Renten Besteuerung Urteil Rentner"],
                "badge": "⚖️ Renten-Steuer",
                "hook_ideas": ["RENTEN-STEUER-URTEIL", "DOPPELBESTEUERUNG", "RENTNER-REVOLTE"],
                "hook_ideas_ru": {"RENTEN-STEUER-URTEIL": "СУДЕБНЫЙ ВЕРДИКТ ПО ПЕНСИЯМ", "DOPPELBESTEUERUNG": "ДВОЙНОЙ НАЛОГ НА ПЕНСИИ", "RENTNER-REVOLTE": "БУНТ ПЕНСИОНЕРОВ ПРОТИВ НАЛОГА"},
            },
        ],
    },
        "pflege_gesundheit_de": {
        "name": "Pflege, Gesundheit & Senioren-Rechte (Pflege-Kompass)",
        "patterns": [
            "pflege", "pflegegrad", "pflegegeld", "pflegekasse", "pflegereform", "pflegeheim",
            "krankenkasse", "zusatzbeitrag", "gesundheit", "mdk", "medizinischer dienst",
            "entlastungsbetrag", "heimkosten", "senioren", "patientenverfügung", "vorsorgevollmacht",
            "hausarzt", "schonvermögen", "verhinderungspflege", "kurzzeitpflege"
        ],
        "sub_angles": [
            {
                "id": "pflegegrad_einstufung",
                "title": "Pflegegrad-Einstufung & Höherstufung: MDK-Gutachten & Fehler",
                "title_ru": "Получение и повышение Pflegegrad: как избежать занижения баллов",
                "desc_ru": "Ошибки экспертов службы MD (бывший MDK), практические правила подготовки к визиту комиссии и обжалование отказа.",
                "queries": ["Pflegegrad Einstufung Medizinischer Dienst Gutachten Fehler", "Pflegegrad Höherstufung Widerspruch Tipps"],
                "badge": "📋 Pflegegrad",
                "hook_ideas": ["PFLEGEGRAD-TRICKS", "MDK-GUTACHTEN FEHLER", "HÖHERSTUFUNG JETZT"],
                "hook_ideas_ru": {"PFLEGEGRAD-TRICKS": "ПРАВИЛА PFLEGEGRAD", "MDK-GUTACHTEN FEHLER": "ОШИБКИ КОМИССИИ MD", "HÖHERSTUFUNG JETZT": "ПОВЫШЕНИЕ СТЕПЕНИ УХОДА"},
            },
            {
                "id": "pflegegeld_erhoehung",
                "title": "Pflegegeld-Erhöhung & Auszahlungstermine",
                "title_ru": "Повышение выплат по уходу Pflegegeld и график перечислений",
                "desc_ru": "Индексация сумм Pflegegeld, комбинированные выплаты (Kombinationsleistung) и задержки от касс.",
                "queries": ["Pflegegeld Erhöhung Tabelle Auszahlung Pflegekasse", "Pflegegeld Pflegereform Beträge Erhöhung"],
                "badge": "💶 Pflegegeld",
                "hook_ideas": ["PFLEGEGELD-PLUS", "AUSZAHLUNG-TABELLE", "MEHR GELD FÜR PFLEGE"],
                "hook_ideas_ru": {"PFLEGEGELD-PLUS": "ПРИБАВКА К PFLEGEGELD", "AUSZAHLUNG-TABELLE": "ТАБЛИЦА ВЫПЛАТ ПО УХОДУ", "MEHR GELD FÜR PFLEGE": "БОЛЬШЕ ДЕНЕГ НА УХОД"},
            },
            {
                "id": "entlastungsbetrag_125",
                "title": "125 Euro Entlastungsbetrag: Verfallene Gelder retten",
                "title_ru": "125 евро ежемесячно: как спасти сгорающие деньги на помощь по дому",
                "desc_ru": "Право на Entlastungsbetrag с 1 степени ухода: оплата уборки, покупок и сопровождающих, сроки сгорания выплат.",
                "queries": ["Entlastungsbetrag 125 Euro Pflegekasse Verfall Frist", "Entlastungsbetrag Haushaltshilfe Einkaufen Abrechnung"],
                "badge": "🧹 125 € Entlastung",
                "hook_ideas": ["125-EURO-VORTEIL", "GELDER NICHT VERSCHENKEN", "PFLEGE-ZUSCHUSS"],
                "hook_ideas_ru": {"125-EURO-VORTEIL": "125 ЕВРО В МЕСЯЦ", "GELDER NICHT VERSCHENKEN": "НЕ ТЕРЯЙТЕ ДЕНЬГИ КАССЫ", "PFLEGE-ZUSCHUSS": "ДОПЛАТА НА ПОМОЩЬ ПО ДОМУ"},
            },
            {
                "id": "heimkosten_eigenanteil",
                "title": "Explodierende Heimkosten & Eigenanteil im Pflegeheim",
                "title_ru": "Взрывной рост цен на дома престарелых: собственный взнос (Eigenanteil)",
                "desc_ru": "Ежемесячный Eigenanteil превысил 2800 евро: надбавки за длительность пребывания и помощь Sozialamt (Hilfe zur Pflege).",
                "queries": ["Pflegeheim Kosten Eigenanteil Rekord Zuzahlung", "Hilfe zur Pflege Sozialamt Heimkosten Schonvermögen"],
                "badge": "🏥 Heimkosten",
                "hook_ideas": ["HEIMKOSTEN-SCHOCK", "EIGENANTEIL-EXPLOSION", "SOZIALAMT-HILFE"],
                "hook_ideas_ru": {"HEIMKOSTEN-SCHOCK": "ШОК СТОИМОСТИ ДОМА ПРЕСТАРЕЛЫХ", "EIGENANTEIL-EXPLOSION": "РОСТ СОБСТВЕННОГО ВЗНОСА", "SOZIALAMT-HILFE": "ПОМОЩЬ СОЦИАЛА НА УХОД"},
            },
            {
                "id": "schonvermoegen_immobilie",
                "title": "Schonvermögen: Darf das Sozialamt das Eigenheim pfänden?",
                "title_ru": "Защита имущества (Schonvermögen): может ли ведомство отобрать дом?",
                "desc_ru": "Границы неприкосновенного имущества (10 000 евро на человека), защита собственного жилья и правило 10 лет при дарении.",
                "queries": ["Schonvermögen Pflegeheim Elternunterhalt Haus Schutz", "Sozialamt Rückforderung Schenkung 10 Jahre Pflege"],
                "badge": "🏡 Haus & Schonvermögen",
                "hook_ideas": ["EIGENHEIM-SCHUTZ", "SCHONVERMÖGEN-FALLE", "HAUS VOR SOZIALAMT RETTEN"],
                "hook_ideas_ru": {"EIGENHEIM-SCHUTZ": "ЗАЩИТА СВОЕГО ДОМА", "SCHONVERMÖGEN-FALLE": "ЛОВУШКИ ИМУЩЕСТВА", "HAUS VOR SOZIALAMT RETTEN": "КАК ЗАЩИТИТЬ ЖИЛЬЁ"},
            },
            {
                "id": "krankenkasse_zusatzbeitrag",
                "title": "Krankenkassen-Zusatzbeitrag: Beitragsanstieg für Rentner",
                "title_ru": "Рост взносов в больничные кассы: удар по кошелькам пенсионеров",
                "desc_ru": "Рекордный дефицит больничных касс, повышение Zusatzbeitrag и автоматическое удержание половины с пенсии.",
                "queries": ["Krankenkassen Zusatzbeitrag Erhöhung Rentner GKV", "Krankenkassenwechsel Sonderkündigungsrecht Beitrag"],
                "badge": "🩺 Krankenkassen",
                "hook_ideas": ["BEITRAGS-SCHOCK", "KRANKENKASSEN-ABZUG", "SONDERKÜNDIGUNG NUTZEN"],
                "hook_ideas_ru": {"BEITRAGS-SCHOCK": "ШОК РОСТА ВЗНОСОВ В КАССУ", "KRANKENKASSEN-ABZUG": "УДЕРЖАНИЯ ИЗ ПЕНСИИ", "SONDERKÜNDIGUNG NUTZEN": "КАК СМЕНИТЬ КАССУ И СПАСТИ ДЕНЬГИ"},
            },
            {
                "id": "vorsorge_vollmacht_patientenverfuegung",
                "title": "Vorsorgevollmacht & Patientenverfügung: Schutz vor Berufsbetreuern",
                "title_ru": "Доверенность и воля пациента: как не попасть под опеку чужого человека",
                "desc_ru": "Почему без Vorsorgevollmacht суд назначает чужого государственного опекуна, правильное оформление без нотариуса.",
                "queries": ["Vorsorgevollmacht Patientenverfügung Betreuungsgericht Fehler", "Vorsorgevollmacht Muster Notar Pflicht Gültigkeit"],
                "badge": "📜 Vorsorge & Vollmacht",
                "hook_ideas": ["VORSORGE-PFLICHT", "KEINE ZWANGSBETREUUNG", "WICHTIGE DOKUMENTE"],
                "hook_ideas_ru": {"VORSORGE-PFLICHT": "ГЛАВНЫЙ ДОКУМЕНТ В СТАРОСТИ", "KEINE ZWANGSBETREUUNG": "ЗАЩИТА ОТ ЧУЖОГО ОПЕКУНА", "WICHTIGE DOKUMENTE": "РАСПОРЯЖЕНИЕ О ЛЕЧЕНИИ"},
            },
            {
                "id": "wohnumfeld_zuschuss_4000",
                "title": "4.000 Euro Zuschuss: Umbau für Bad & barrierefreies Wohnen",
                "title_ru": "До 4 000 евро от Pflegekasse: субсидия на переделку ванной и безбарьерный дом",
                "desc_ru": "Zuschuss zur Wohnumfeldverbesserung: замена ванны на душ, расширение проемов и пандусы без возврата средств.",
                "queries": ["Zuschuss Wohnumfeldverbesserung 4000 Euro Badumbau", "Pflegekasse Umbau barrierefrei Dusche Zuschuss"],
                "badge": "🚿 4.000 € Umbau",
                "hook_ideas": ["4000-EURO-GESCHENK", "BADUMBAU KOSTENLOS", "BARRIEREFREI-ZUSCHUSS"],
                "hook_ideas_ru": {"4000-EURO-GESCHENK": "4000 ЕВРО НА ПЕРЕДЕЛКУ", "BADUMBAU KOSTENLOS": "ДУШ ВМЕСТО ВАННЫ БЕСПЛАТНО", "BARRIEREFREI-ZUSCHUSS": "СУБСИДИЯ НА РЕМОНТ ОТ КАССЫ"},
            },
            {
                "id": "verhinderungspflege_kurzzeitpflege",
                "title": "Verhinderungspflege & Kurzzeitpflege: Bis zu 3.539 Euro Budget",
                "title_ru": "Подмена ухаживающего: до 3 539 евро в год на отпуск и отдых",
                "desc_ru": "Объединение бюджетов Verhinderungspflege и Kurzzeitpflege (Gemeinsamer Jahresbetrag): компенсация отдыха родственников.",
                "queries": ["Gemeinsamer Jahresbetrag Verhinderungspflege Kurzzeitpflege", "Verhinderungspflege Antrag Stundensatz Angehörige"],
                "badge": "🏖️ Verhinderungspflege",
                "hook_ideas": ["PFLEGE-URLAUB", "3500-EURO-BUDGET", "ENTLASTUNG FÜR ANGEHÖRIGE"],
                "hook_ideas_ru": {"PFLEGE-URLAUB": "ОТПУСК ОТ УХОДА", "3500-EURO-BUDGET": "БЮДЖЕТ ДО 3539 ЕВРО", "ENTLASTUNG FÜR ANGEHÖRIGE": "ДЕНЬГИ НА ПОДМЕНУ РОДСТВЕННИКА"},
            },
        ],
    },
    "wirtschaft_de": {
        "name": "Wirtschaft & Industrie Deutschland",
        "patterns": ["wirtschaft", "industrie", "vw", "volkswagen", "insolvenz", "habeck", "standort", "energie"],
        "sub_angles": [
            {
                "id": "industrie_krise",
                "title": "Autokrise, VW-Werksschließungen & Deindustrialisierung",
                "title_ru": "Кризис автопрома, закрытие заводов VW и деиндустриализация",
                "desc_ru": "Планы сокращения десятков тысяч рабочих мест на заводах Volkswagen и падение заказов у поставщиков.",
                "queries": ["VW Werksschließung Stellenabbau Betriebsrat Krise", "Autoindustrie Deutschland Krise Zulieferer"],
                "badge": "🏭 Auto & VW",
                "hook_ideas": ["VW-SCHOCK", "WERKSSCHLIESSUNGS-HAMMER", "INDUSTRIE-ALARM"],
                "hook_ideas_ru": {"VW-SCHOCK": "ШОК В АВТОПРОМЕ VW", "WERKSSCHLIESSUNGS-HAMMER": "ЗАКРЫТИЕ ЗАВОДОВ В ФРГ", "INDUSTRIE-ALARM": "УГРОЗА ДЕИНДУСТРИАЛИЗАЦИИ"},
            },
            {
                "id": "energie_strompreis",
                "title": "Industriestrompreis & Energiekosten-Krise",
                "title_ru": "Цены на электроэнергию для промышленности и утечка производств",
                "desc_ru": "Высокие тарифы на энергию вынуждают немецкие химические и сталелитейные концерны уходить в США и Азию.",
                "queries": ["Industriestrompreis Deutschland Abwanderung Betriebe", "Strompreise Wirtschaft Standortnachteil Habeck"],
                "badge": "⚡ Energie",
                "hook_ideas": ["STROM-SCHOCK", "ABWANDERUNGS-ALARM", "STANDORT-KRISE"],
                "hook_ideas_ru": {"STROM-SCHOCK": "ЭНЕРГЕТИЧЕСКИЙ ТУПИК", "ABWANDERUNGS-ALARM": "БЕГСТВО ПРЕДПРИЯТИЙ ИЗ ФРГ", "STANDORT-KRISE": "КРИЗИС СТОИМОСТИ ЭНЕРГИИ"},
            },
            {
                "id": "insolvenzen",
                "title": "Insolvenzwelle & Firmenpleiten",
                "title_ru": "Волна банкротств и закрытие предприятий среднего бизнеса",
                "desc_ru": "Рекордные показатели неплатежеспособности по данным институтов IWH и Creditreform за последние годы.",
                "queries": ["Insolvenzen Deutschland Rekord Pleiten IWH", "Firmenpleiten Mittelstand Insolvenzwelle"],
                "badge": "📉 Pleiten",
                "hook_ideas": ["PLEITE-WELLE", "INSOLVENZ-REKORD", "MITTELSTAND-NOTSTAND"],
                "hook_ideas_ru": {"PLEITE-WELLE": "РЕКОРДНАЯ ВОЛНА БАНКРОТСТВ", "INSOLVENZ-REKORD": "ПИКИ ЗАКРЫТИЙ КОМПАНИЙ", "MITTELSTAND-NOTSTAND": "УДАР ПО СРЕДНЕМУ БИЗНЕСУ"},
            },
            {
                "id": "chemie_basf",
                "title": "Chemie-Krise & BASF-Produktionsstopp in Deutschland",
                "title_ru": "Кризис химической отрасли и закрытие линий BASF",
                "desc_ru": "Флагман немецкой химии сворачивает мощности в Людвигсхафене и переносит 10 млрд евро инвестиций в Китай.",
                "queries": ["BASF Stellenabbau Ludwigshafen Chemiekrise", "Chemieindustrie Deutschland Krise Abwanderung"],
                "badge": "🧪 Chemie & BASF",
                "hook_ideas": ["BASF-SCHOCK", "CHEMIE-ALARM", "STANDORT-EXODUS"],
                "hook_ideas_ru": {"BASF-SCHOCK": "ШОК КОНЦЕРНА BASF", "CHEMIE-ALARM": "КРИЗИС НЕМЕЦКОЙ ХИМИИ", "STANDORT-EXODUS": "БЕГСТВО ХИМПРОМА ИЗ ФРГ"},
            },
            {
                "id": "baukrise_wohnungsnot",
                "title": "Baukrise & Wohnungsnot: Rekordtief bei Neubauten",
                "title_ru": "Строительный коллапс: рекордный провал ввода жилья",
                "desc_ru": "Рост ставок по ипотеке и дорогие стройматериалы заморозили стройки по всей Германии, дефицит 800 тыс. квартир.",
                "queries": ["Baukrise Deutschland Neubau Einbruch Wohnungsnot", "Wohnungsbau Krise Insolvenzen Bauträger"],
                "badge": "🏗️ Bau & Wohnen",
                "hook_ideas": ["BAU-KOLLAPS", "WOHNUNGSNOT-ALARM", "MIET-SCHOCK"],
                "hook_ideas_ru": {"BAU-KOLLAPS": "КРАХ СТРОЙИНДУСТРИИ", "WOHNUNGSNOT-ALARM": "ДЕФИЦИТ КВАРТИР В ГОРОДАХ", "MIET-SCHOCK": "ВЗРЫВНОЙ РОСТ АРЕНДЫ"},
            },
        ],
    },
    "ru_politics": {
        "name": "Внутренняя политика России",
        "patterns": ["белоусов", "минобороны", "госдума", "правительство", "внутренняя политика", "армия", "налоги"],
        "sub_angles": [
            {
                "id": "belousov_audit",
                "title": "Андрей Белоусов: аудит расходов и реформа Минобороны",
                "title_ru": "Андрей Белоусов: аудит военных расходов и наведение порядка",
                "desc_ru": "Проверка исполнения контрактов, повышение прозрачности поставок и перенастройка тыла армии.",
                "queries": ["Андрей Белоусов Минобороны аудит расходы", "Белоусов армия обеспечение поставки"],
                "badge": "🛡️ Белоусов & МО",
                "hook_ideas": ["АУДИТ БЕЛОУСОВА", "ПОРЯДОК В МИНОБОРОНЫ", "РЕШЕНИЯ БЕЛОУСОВА"],
                "hook_ideas_ru": {"АУДИТ БЕЛОУСОВА": "АУДИТ БЕЛОУСОВА", "ПОРЯДОК В МИНОБОРОНЫ": "ПОРЯДОК В МИНОБОРОНЫ", "РЕШЕНИЯ БЕЛОУСОВА": "РЕШЕНИЯ БЕЛОУСОВА"},
            },
            {
                "id": "gosoboronzakaz",
                "title": "Гособоронзаказ и военная промышленность",
                "title_ru": "Гособоронзаказ и круглосуточная работа предприятий ВПК",
                "desc_ru": "Выпуск новейших систем, импортозамещение компонентов и наращивание выпуска техники.",
                "queries": ["Гособоронзаказ ВПК выпуск вооружений заводы", "Оборонные предприятия Россия темпы выпуска"],
                "badge": "🏭 ВПК РФ",
                "hook_ideas": ["ПРОРЫВ ВПК", "РЕКОРД ГОСОБОРОНЗАКАЗА", "ЗАВОДЫ ОБОРОНКИ"],
                "hook_ideas_ru": {"ПРОРЫВ ВПК": "ПРОРЫВ ВПК", "РЕКОРД ГОСОБОРОНЗАКАЗА": "РЕКОРД ГОСОБОРОНЗАКАЗА", "ЗАВОДЫ ОБОРОНКИ": "ЗАВОДЫ ОБОРОНКИ"},
            },
            {
                "id": "nalogi_byudzhet",
                "title": "Налоговая реформа и распределение бюджета",
                "title_ru": "Налоговая реформа и приоритеты расходов федерального бюджета",
                "desc_ru": "Прогрессивная шкала НДФЛ, налог на прибыль и финансирование социальных и оборонных программ.",
                "queries": ["Налоговая реформа Госдума бюджет доходы", "Прогрессивная шкала налоги изменения"],
                "badge": "📊 Налоги & Бюджет",
                "hook_ideas": ["НАЛОГОВЫЙ БЮДЖЕТ", "РЕФОРМА ДОХОДОВ", "БЮДЖЕТНЫЙ ПЛАН"],
                "hook_ideas_ru": {"НАЛОГОВЫЙ БЮДЖЕТ": "НАЛОГОВЫЙ БЮДЖЕТ", "РЕФОРМА ДОХОДОВ": "РЕФОРМА ДОХОДОВ", "БЮДЖЕТНЫЙ ПЛАН": "БЮДЖЕТНЫЙ ПЛАН"},
            },
            {
                "id": "migracionnaya_politika_rf",
                "title": "Ужесточение миграционной политики в РФ",
                "title_ru": "Ужесточение миграционного контроля и новый реестр лиц",
                "desc_ru": "Новые законы Госдумы, реестр контролируемых лиц, режим высылки и проверки документов.",
                "queries": ["Миграционная политика ужесточение Госдума рейды", "Реестр контролируемых лиц мигранты законы"],
                "badge": "⚖️ Контроль миграции",
                "hook_ideas": ["НОВЫЕ ПРАВИЛА МИГРАЦИИ", "РЕЙДЫ И РЕЕСТР", "ЖЕСТКИЙ КОНТРОЛЬ"],
                "hook_ideas_ru": {"НОВЫЕ ПРАВИЛА МИГРАЦИИ": "НОВЫЕ ПРАВИЛА МИГРАЦИИ", "РЕЙДЫ И РЕЕСТР": "РЕЙДЫ И РЕЕСТР", "ЖЕСТКИЙ КОНТРОЛЬ": "ЖЕСТКИЙ КОНТРОЛЬ"},
            },
        ],
    },
}


def decode_google_news_token(url: str) -> str:
    """Offline extraction of direct publisher URL from Google News redirect tokens."""
    if not url or "news.google.com" not in url:
        return url
        
    match = re.search(r'(?:articles|read)/([A-Za-z0-9_-]+)', url)
    if not match:
        return url
        
    token = match.group(1)
    try:
        padded = token + "=" * ((4 - len(token) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        urls = re.findall(rb'https?://[^\x00-\x1f\x7f-\xff\s"\'<>]+', decoded)
        for u in urls:
            cand = u.decode('utf-8', errors='ignore')
            if "google.com" not in cand and "." in cand and len(cand) > 12:
                return cand
    except Exception:
        pass
        
    return url


def load_news_history() -> dict:
    """Load history of used articles, sub-angles, and video titles from disk."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading news history: {e}")
            
    initial_titles = []
    try:
        import glob
        for p in glob.glob(str(config.OUTPUT_DIR / "*/script.txt")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    first = f.readline().strip()
                    if first.startswith("Title:"):
                        title = first.replace("Title:", "").strip()
                        if title and title not in initial_titles:
                            initial_titles.append(title)
            except:
                pass
    except:
        pass

    return {
        "used_links": [],
        "used_titles": [],
        "previous_video_titles": initial_titles,
        "used_sub_angles": [],
    }


def get_article_age_days(pub_str: str) -> float:
    """Return age in days of an article pub_date string, or 999.0 if missing/unparseable."""
    if not pub_str or not str(pub_str).strip():
        return 999.0
    try:
        dt = email.utils.parsedate_to_datetime(pub_str)
        now = datetime.now(dt.tzinfo or timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except Exception:
        try:
            dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo or timezone.utc)
            return max(0.0, (now - dt).total_seconds() / 86400.0)
        except Exception:
            return 999.0


def format_pub_date(pub_str: str) -> str:
    """Format RFC-2822 or ISO date string into friendly Russian relative date (e.g. '2 ч назад (17:34)' or 'Сегодня, 18:20')."""
    if not pub_str or not str(pub_str).strip():
        now = datetime.now()
        return f"Сегодня, {now.strftime('%H:%M')}"
    try:
        dt = email.utils.parsedate_to_datetime(pub_str)
        now = datetime.now(dt.tzinfo or timezone.utc)
        diff = now - dt
        total_seconds = int(diff.total_seconds())
        if total_seconds < 0:
            total_seconds = 0
            
        time_hm = dt.strftime("%H:%M")
        if total_seconds < 3600:
            minutes = max(1, total_seconds // 60)
            return f"{minutes} мин назад ({time_hm})"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            if hours <= 3:
                return f"{hours} ч назад ({time_hm})"
            return f"Сегодня, {time_hm}"
        elif total_seconds < 172800:
            return f"Вчера, {time_hm}"
        elif total_seconds < 86400 * 3:
            return f"2 дня назад, {time_hm}"
        elif total_seconds < 86400 * 4:
            return f"3 дня назад, {time_hm}"
        else:
            months_ru = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
            m_str = months_ru[dt.month] if 1 <= dt.month <= 12 else str(dt.month)
            if dt.year != now.year:
                return f"{dt.day} {m_str} {dt.year}, {time_hm}"
            return f"{dt.day} {m_str}, {time_hm}"
    except Exception:
        try:
            dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y, %H:%M")
        except Exception:
            return str(pub_str)[:16]


def mark_acute_angle_used(angle_id: str):
    """Mark a specific acute sub-angle ID as used so it won't be shown repeatedly."""
    if not angle_id:
        return
    hist = load_news_history()
    used_angles = hist.get("used_sub_angles", [])
    if angle_id not in used_angles:
        used_angles.append(angle_id)
        hist["used_sub_angles"] = used_angles[-120:]
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False, indent=2)
            logger.info(f"📌 Тема [{angle_id}] отмечена как использованная в истории.")
        except Exception as e:
            logger.warning(f"Failed to update used_sub_angles: {e}")


def mark_acute_angles_dismissed(angle_ids: list[str]):
    """Mark multiple acute sub-angle IDs as dismissed/skipped by user."""
    if not angle_ids:
        return
    hist = load_news_history()
    used_angles = hist.get("used_sub_angles", [])
    added = False
    for aid in angle_ids:
        if aid and aid not in used_angles:
            used_angles.append(aid)
            added = True
    if added:
        hist["used_sub_angles"] = used_angles[-150:]
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False, indent=2)
            logger.info(f"📌 Темы {angle_ids} скрыты/отмечены как просмотренные.")
        except Exception as e:
            logger.warning(f"Failed to update used_sub_angles: {e}")


def reset_acute_history():
    """Reset history of used sub-angles so user can see all topics again."""
    hist = load_news_history()
    hist["used_sub_angles"] = []
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
        logger.info("🔄 История использованных тем успешно сброшена.")
    except Exception as e:
        logger.warning(f"Failed to reset acute history: {e}")


def save_news_history(
    used_links: list[str],
    used_titles: list[str],
    new_video_title: str = "",
    used_sub_angle: str = "",
):
    """Save used article links, titles, sub-angle and generated video title to history."""
    hist = load_news_history()
    
    current_links = hist.get("used_links", [])
    current_titles = hist.get("used_titles", [])
    video_titles = hist.get("previous_video_titles", [])
    sub_angles = hist.get("used_sub_angles", [])
    
    for l in used_links:
        if l and l not in current_links:
            current_links.append(l)
    for t in used_titles:
        if t and t not in current_titles:
            current_titles.append(t)
            
    if new_video_title and new_video_title not in video_titles:
        video_titles.append(new_video_title)
        
    if used_sub_angle and used_sub_angle not in sub_angles:
        sub_angles.append(used_sub_angle)
        
    hist["used_links"] = current_links[-400:]
    hist["used_titles"] = current_titles[-400:]
    hist["previous_video_titles"] = video_titles[-35:]
    hist["used_sub_angles"] = sub_angles[-120:]
    
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save news history: {e}")


def get_recent_video_titles(limit: int = 8) -> list[str]:
    """Get list of recently generated video titles."""
    hist = load_news_history()
    return hist.get("previous_video_titles", [])[-limit:]


def identify_acute_cluster(topic: str) -> tuple[str, dict | None]:
    """Identify which acute catalog category matches the input topic."""
    t_lower = topic.lower()
    for cat_id, cat_info in ACUTE_TOPIC_CATALOG.items():
        if any(pat in t_lower for pat in cat_info["patterns"]):
            return cat_id, cat_info
    return "", None


def get_acute_angle_by_id(angle_id: str) -> dict | None:
    """Find a specific acute angle by its ID across all catalog categories."""
    if not angle_id:
        return None
    clean_id = angle_id.strip()
    for cat_id, cat_info in ACUTE_TOPIC_CATALOG.items():
        for ang in cat_info.get("sub_angles", []):
            if ang.get("id") == clean_id:
                return ang
    return None


def find_matching_acute_angle(topic: str, cat_info: dict | None = None) -> dict | None:
    """
    Check if the user's topic specifically matches a particular sub-angle in the catalog.
    Matches by ID, title, query strings, or key distinct terms.
    """
    if not topic:
        return None
    t_clean = topic.lower().strip()
    catalogs = [cat_info] if cat_info else list(ACUTE_TOPIC_CATALOG.values())
    
    # 1. Exact or substring match on ID
    for c in catalogs:
        if not c:
            continue
        for ang in c.get("sub_angles", []):
            ang_id = ang["id"].lower()
            if ang_id == t_clean or ang_id.replace("_", " ") in t_clean or t_clean in ang_id:
                return ang
                
    # 2. Check title matches (DE & RU)
    for c in catalogs:
        if not c:
            continue
        for ang in c.get("sub_angles", []):
            de_title = ang.get("title", "").lower()
            if t_clean in de_title or de_title in t_clean:
                return ang
            ru_title = ang.get("title_ru", "").lower()
            if ru_title and (t_clean in ru_title or ru_title in t_clean):
                return ang
            # Check overlap of significant title words
            de_words = [w for w in re.findall(r'[a-zA-Zäöüß0-9]{4,}', de_title) if w not in {"deutschland", "bundes", "aktuell", "politik"}]
            if de_words and sum(1 for w in de_words if w in t_clean) >= 2:
                return ang
            ru_words = [w for w in re.findall(r'[а-яё0-9]{4,}', ru_title) if w not in {"германии", "россии", "новости", "политика"}]
            if ru_words and sum(1 for w in ru_words if w in t_clean) >= 2:
                return ang

    # 3. Check query matches (if topic matches one of the sub-angle queries)
    for c in catalogs:
        if not c:
            continue
        for ang in c.get("sub_angles", []):
            for q in ang.get("queries", []):
                q_clean = q.lower().strip()
                if q_clean == t_clean or t_clean in q_clean or q_clean in t_clean:
                    return ang
                q_words = [w for w in re.findall(r'[a-zA-ZäöüßА-Яа-яё0-9]{4,}', q_clean) if w not in {"deutschland", "bundes", "politik", "aktuell"}]
                if q_words and sum(1 for w in q_words if w in t_clean) >= 2:
                    return ang

    return None


def is_umbrella_topic(topic: str, cat_id: str) -> bool:
    """
    Check if the user input is a generic/broad umbrella topic (e.g. 'Migration Deutschland')
    rather than a specific, narrow news headline or targeted inquiry.
    """
    t_clean = topic.lower().strip()
    words = t_clean.split()
    
    # Generic umbrella phrases per category
    UMBRELLA_PHRASES = {
        "migration_de": {
            "migration", "asyl", "asylpolitik", "flüchtlinge", "fluechtlinge", "flüchtlingskrise",
            "migration deutschland", "asylpolitik deutschland", "flüchtlinge deutschland",
            "миграция", "миграция германия", "беженцы германия", "миграционная политика"
        },
        "rente_soziales_de": {
            "rente", "rente deutschland", "rentenpaket", "sozialstaat", "bürgergeld",
            "пенсии германия", "бюргергельд", "социальная политика"
        },
        "wirtschaft_de": {
            "wirtschaft", "wirtschaft deutschland", "industrie deutschland", "deindustrialisierung",
            "экономика германия"
        },
        "ru_politics": {
            "политика", "россия", "новости", "новости россии", "политика россии"
        }
    }
    
    cluster_phrases = UMBRELLA_PHRASES.get(cat_id, set())
    if t_clean in cluster_phrases:
        return True
    
    # If topic is very short (1-3 words) and consists solely of generic category keywords
    if len(words) <= 3:
        cat_pats = ACUTE_TOPIC_CATALOG.get(cat_id, {}).get("patterns", [])
        if all(any(p in w for p in cat_pats) or w in {"deutschland", "politik", "berlin", "германия", "россия"} for w in words):
            return True
            
    return False


def pick_fresh_acute_angle(topic: str, explicit_id: str = "") -> dict | None:
    """
    Pick or resolve acute sub-angle for a topic.
    1. If explicit_id is provided, strictly use that sub-angle.
    2. If topic specifically matches a catalog sub-angle (by ID, title, or query), use that angle.
    3. If topic is a broad umbrella topic (e.g. 'Migration Deutschland'), rotate to a fresh, un-used angle.
    4. If topic is a specific user query (not in catalog), DO NOT override it with a random angle.
    """
    # 1. Explicit ID provided by UI selection
    if explicit_id:
        found = get_acute_angle_by_id(explicit_id)
        if found:
            logger.info(f"🎯 ИСПОЛЬЗУЕМ ВЫБРАННЫЙ ОСТРЫЙ РАКУРС ПО ID [{found['id']}]: {found['title']}")
            return found

    cat_id, cat_info = identify_acute_cluster(topic)
    if not cat_info:
        return None
        
    # 2. Check if topic specifically matches a known sub-angle
    matched = find_matching_acute_angle(topic, cat_info)
    if matched:
        logger.info(f"🎯 Найдено прямое соответствие выбранному ракурсу: [{matched['id']}] {matched['title']}")
        return matched

    # 3. Only pick a random fresh sub-angle if the topic is a genuine broad umbrella topic!
    if not is_umbrella_topic(topic, cat_id):
        logger.info(f"ℹ️ Тема '{topic}' является конкретным пользовательским запросом, случайная замена ракурса НЕ применяется.")
        return None

    # 4. For umbrella topics, pick a fresh un-used angle
    hist = load_news_history()
    recently_used = set(hist.get("used_sub_angles", [])[-8:])
    
    available = [ang for ang in cat_info["sub_angles"] if ang["id"] not in recently_used]
    if not available:
        available = cat_info["sub_angles"]
    
    chosen = random.choice(available)
    logger.info(f"🎯 Развёрнута общая тема '{topic}' в острый ракурс: [{chosen['id']}] {chosen['title']}")
    return chosen


async def fetch_rss_feed(client: httpx.AsyncClient, name: str, feed_url: str, max_items: int = 40) -> list[dict]:
    """Fetch articles directly from agency RSS feeds."""
    articles = []
    try:
        resp = await client.get(feed_url)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "xml")
            items = soup.find_all("item")
            for item in items[:max_items]:
                title_tag = item.find("title")
                link_tag = item.find("link")
                pub_tag = item.find("pubDate")
                desc_tag = item.find("description")
                
                title = title_tag.text.strip() if title_tag else ""
                link = link_tag.text.strip() if link_tag else ""
                pub = pub_tag.text.strip() if pub_tag else ""
                summary = desc_tag.text.strip() if desc_tag else ""
                
                if title and link:
                    if "<" in summary:
                        summary = BeautifulSoup(summary, "html.parser").get_text(strip=True)
                    articles.append({
                        "title": title,
                        "link": link,
                        "source": name,
                        "published": pub,
                        "summary": summary,
                    })
    except Exception as e:
        logger.debug(f"Direct feed '{name}' ({feed_url}) error: {e}")
        
    return articles


async def fetch_direct_agency_feeds(lang: str = "ru") -> list[dict]:
    """Fetch from premier news agencies that provide direct scrapeable URLs."""
    if lang == "ru":
        feeds = [
            ("Интерфакс", "https://www.interfax.ru/rss.asp"),
            ("Коммерсантъ", "https://www.kommersant.ru/RSS/news.xml"),
            ("Ведомости", "https://www.vedomosti.ru/rss/news"),
            ("Rambler", "https://news.rambler.ru/rss/world/"),
            ("Lenta.ru", "https://lenta.ru/rss/news/world"),
            ("Lenta.ru (РФ)", "https://lenta.ru/rss/news/russia"),
        ]
    elif lang == "de":
        feeds = [
            ("Tagesschau Inland", "https://www.tagesschau.de/inland/index~rss2.xml"),
            ("Tagesschau Politik", "https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml"),
            ("Focus Deutschland", "https://rss.focus.de/politik/deutschland/"),
            ("Focus Gesundheit", "https://rss.focus.de/gesundheit/"),
            ("T-Online Gesundheit", "https://www.t-online.de/gesundheit/feed.rss"),
            ("Die Welt Inland", "https://www.welt.de/feeds/section/politik/deutschland.rss"),
            ("FAZ Inland", "https://www.faz.net/rss/aktuell/politik/inland/"),
            ("SZ Politik", "https://rss.sueddeutsche.de/rss/Politik"),
            ("Der Spiegel Politik", "https://www.spiegel.de/politik/index.rss"),
            ("N-TV Politik", "https://www.n-tv.de/politik/rss"),
            ("Die Zeit", "https://newsfeed.zeit.de/politik/index"),
            ("ZDF Heute", "https://www.zdf.de/rss/zdf/nachrichten"),
        ]
    else:
        feeds = [
            ("BBC News", "http://feeds.bbci.co.uk/news/world/rss.xml"),
            ("Reuters", "https://www.reutersagency.com/feed/?taxonomy=markets&post_type=best"),
            ("The Guardian", "https://www.theguardian.com/world/rss"),
        ]
        
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
        tasks = [fetch_rss_feed(client, name, url) for name, url in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
    all_articles = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)
            
    logger.info(f"Собрано {len(all_articles)} новостей из прямых лент агентств ({lang})")
    return all_articles


async def fetch_google_news(topic: str, lang: str = "ru", max_results: int = 30) -> list[dict]:
    """Fetch fresh news from Google News RSS and decode direct publisher links."""
    lang_map = {
        "ru": ("ru", "RU"), "en": ("en", "US"), "de": ("de", "DE"),
        "fr": ("fr", "FR"), "es": ("es", "ES"),
    }
    hl, gl = lang_map.get(lang, ("ru", "RU"))
    
    # 1. Clean query from special syntax characters (: & " etc.) and trailing sources
    clean_topic = re.sub(r'[:&|–—"\'#?!+()«»]', ' ', topic).strip()
    clean_topic = re.sub(r'\s+[-–—|]\s+[A-Za-zА-Яа-я0-9.\s]+$', '', clean_topic).strip()
    clean_topic = re.sub(r'\s+', ' ', clean_topic)
    if not clean_topic:
        clean_topic = topic.strip()
        
    queries = [f"{clean_topic} when:2d", f"{clean_topic} when:3d"]
    
    # If topic has > 3 words, also add key query with the first 3 important words
    words = [w for w in clean_topic.split() if len(w) >= 3][:3]
    key_q = " ".join(words)
    if key_q and key_q != clean_topic:
        queries.append(f"{key_q} when:3d")
        
    articles = []
    seen_links = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    async def _execute_query(q: str, max_age_days: float = 4.5):
        encoded_topic = quote_plus(q)
        url = f"https://news.google.com/rss/search?q={encoded_topic}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
        found = []
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    feed = feedparser.parse(resp.text)
                    for entry in feed.entries:
                        link = entry.get("link", "")
                        if link and link not in seen_links:
                            pub_str = getattr(entry, "published", "")
                            if pub_str and get_article_age_days(pub_str) > max_age_days:
                                continue
                            seen_links.add(link)
                            source = ""
                            if hasattr(entry, "source") and hasattr(entry.source, "title"):
                                source = entry.source.title
                            direct_link = decode_google_news_token(link)
                            found.append({
                                "title": entry.get("title", ""),
                                "link": direct_link,
                                "raw_google_link": link,
                                "published": pub_str,
                                "source": source or "Google News",
                                "summary": entry.get("summary", ""),
                            })
        except Exception as e:
            logger.debug(f"Google News error for '{q}': {e}")
        return found

    for q in queries:
        new_arts = await _execute_query(q, max_age_days=4.5)
        articles.extend(new_arts)
        if len(articles) >= max_results:
            break

    # Progressive Fallback if 0 or very few articles were found (broaden search window & simplify)
    if len(articles) < 3:
        fallback_queries = [
            f"{clean_topic} when:7d",
            f"{key_q} when:7d" if key_q else "",
            clean_topic,
            key_q if key_q else "",
        ]
        for fq in [q for q in fallback_queries if q]:
            new_arts = await _execute_query(fq, max_age_days=7.0)
            articles.extend(new_arts)
            if len(articles) >= 6:
                break
                
    return articles[:max_results]


async def search_ddg_news(query: str, lang: str = "de", max_results: int = 20) -> list[dict]:
    """Search DuckDuckGo HTML for news articles with direct publisher links."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': f'{lang}-{lang.upper()},{lang};q=0.9,en;q=0.7',
    }
    articles = []
    suffix = "nachrichten" if lang == "de" else ("news" if lang in ["en", "fr", "es"] else "новости")
    queries = [f"{query} {suffix}", f"{query} aktuell" if lang == "de" else f"{query} today"]
    seen_urls = set()
    
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
            for q in queries:
                try:
                    resp = await client.post('https://html.duckduckgo.com/html/', data={'q': q})
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        for res in soup.find_all('div', class_='result'):
                            title_a = res.find('a', class_='result__a')
                            snippet_a = res.find('a', class_='result__snippet')
                            if title_a:
                                raw_url = title_a.get('href', '')
                                parsed = urlparse(raw_url)
                                real_url = parse_qs(parsed.query).get('uddg', [raw_url])[0]
                                title = title_a.get_text(strip=True)
                                snippet = snippet_a.get_text(strip=True) if snippet_a else ''
                                if (real_url.startswith('http') and 
                                    'duckduckgo.com' not in real_url and 
                                    real_url not in seen_urls and 
                                    len(title) > 10):
                                    seen_urls.add(real_url)
                                    domain = urlparse(real_url).netloc.replace('www.', '')
                                    articles.append({
                                        'title': title,
                                        'link': real_url,
                                        'source': domain,
                                        'summary': snippet,
                                        'published': '',
                                    })
                except Exception as e:
                    logger.debug(f"DDG query '{q}' error: {e}")
                if len(articles) >= max_results:
                    break
    except Exception as e:
        logger.debug(f"DuckDuckGo news search failed for '{query}': {e}")
        
    return articles[:max_results]


async def search_lenta_news(query: str, count: int = 15) -> list[dict]:
    """Search Lenta.ru directly."""
    encoded = quote_plus(query)
    url = f"https://lenta.ru/search/v2/process?from=0&size={count}&sort=2&title_only=0&domain=1&query={encoded}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    articles = []
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                for m in data.get("matches", []):
                    text = m.get("text", "")
                    title = m.get("title", "")
                    link = m.get("url", "")
                    if title and link:
                        articles.append({
                            "title": title,
                            "link": link,
                            "source": "Lenta.ru",
                            "full_text": text,
                            "text_len": len(text),
                            "preview": (text[:300] + "...") if len(text) > 300 else text,
                            "published": datetime.fromtimestamp(m.get("pubdate", 0)).isoformat() if m.get("pubdate") else "",
                            "summary": m.get("snippet", "") or (text[:250] + "..." if text else ""),
                        })
    except Exception as e:
        logger.debug(f"Lenta search failed for '{query}': {e}")
    return articles


async def search_kommersant_news(query: str, count: int = 15) -> list[dict]:
    """Search Kommersant directly."""
    encoded = quote_plus(query)
    url = f"https://www.kommersant.ru/search/results?search_query={encoded}&sort_type=1"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    articles = []
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for item in soup.find_all("article")[:count]:
                    h = item.find(["h2", "h3"])
                    a = item.find("a")
                    if a and a.get("href"):
                        title = h.get_text(strip=True) if h else a.get_text(strip=True)
                        link = a.get("href")
                        if not link.startswith("http"):
                            link = "https://www.kommersant.ru" + link
                        if title and len(title) > 10:
                            articles.append({
                                "title": title,
                                "link": link,
                                "source": "Коммерсантъ",
                                "summary": title,
                                "published": "",
                            })
    except Exception as e:
        logger.debug(f"Kommersant search failed for '{query}': {e}")
    return articles


async def search_ria_news(query: str, count: int = 15) -> list[dict]:
    """Search RIA Novosti directly."""
    encoded = quote_plus(query)
    url = f"https://ria.ru/search/?query={encoded}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    articles = []
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for item in soup.find_all("div", class_="list-item__content")[:count]:
                    a = item.find("a", class_="list-item__title")
                    if a and a.get("href"):
                        title = a.get_text(strip=True)
                        link = a.get("href")
                        if not link.startswith("http"):
                            link = "https://ria.ru" + link
                        articles.append({
                            "title": title,
                            "link": link,
                            "source": "РИА Новости",
                            "summary": "",
                            "published": "",
                        })
    except Exception as e:
        logger.debug(f"RIA search failed for '{query}': {e}")
    return articles


async def resolve_direct_url_by_title(title: str) -> str | None:
    """Find the real publisher URL for a Google News or agency headline via fast search."""
    if not title or len(title) < 8:
        return None
    from urllib.parse import unquote
    clean_title = re.sub(r'\s*[-|–—]\s*[^|–—]+$', '', title).strip()
    if len(clean_title) < 8:
        clean_title = title.strip()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,ru;q=0.7",
    }
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
            # 1. DuckDuckGo Lite (fast, highly reliable, rarely blocked)
            try:
                resp = await client.get("https://lite.duckduckgo.com/lite/", params={"q": clean_title})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", class_="result-link"):
                        href = a.get("href", "")
                        if "uddg=" in href:
                            target = unquote(href.split("uddg=")[1].split("&")[0])
                            if not any(bad in target for bad in ["google.com", "duckduckgo.com", "facebook.com", "twitter.com", "youtube.com"]):
                                return target
                        elif href.startswith("http") and not any(bad in href for bad in ["google.com", "duckduckgo.com"]):
                            return href
            except Exception:
                pass

            # 2. DuckDuckGo HTML POST fallback
            try:
                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": clean_title})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", class_="result__url"):
                        href = a.get("href", "")
                        if "uddg=" in href:
                            target = unquote(href.split("uddg=")[1].split("&")[0])
                            if not any(bad in target for bad in ["google.com", "duckduckgo.com", "facebook.com", "twitter.com", "youtube.com"]):
                                return target
                        elif href.startswith("http") and not any(bad in href for bad in ["google.com", "duckduckgo.com"]):
                            return href
            except Exception:
                pass

            # 3. Cloudflare Worker fallback (if datacenter IP was rate-limited by DuckDuckGo)
            worker = config.get_image_proxy_worker()
            if worker:
                try:
                    target_ddg = f"https://lite.duckduckgo.com/lite/?q={quote_plus(clean_title)}"
                    p_url = f"{worker}?url={quote_plus(target_ddg)}"
                    resp = await client.get(p_url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.find_all("a", class_="result-link"):
                            href = a.get("href", "")
                            if "uddg=" in href:
                                target = unquote(href.split("uddg=")[1].split("&")[0])
                                if not any(bad in target for bad in ["google.com", "duckduckgo.com", "facebook.com", "twitter.com", "youtube.com"]):
                                    return target
                            elif href.startswith("http") and not any(bad in href for bad in ["google.com", "duckduckgo.com"]):
                                return href
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Direct URL resolution failed for '{title}': {e}")
    return None


async def extract_article_text(url: str, title: str = "", client: httpx.AsyncClient = None) -> str:
    """Extract full article text from direct URL, automatically resolving Google News redirect tokens."""
    if not url:
        return ""
    decoded_url = decode_google_news_token(url)
    
    # If Google News redirect token cannot be parsed offline, resolve direct publisher URL via title!
    if "news.google.com" in decoded_url or "consent.google" in decoded_url:
        if title:
            real_url = await resolve_direct_url_by_title(title)
            if real_url:
                decoded_url = real_url
            else:
                return ""
        else:
            return ""
        
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,ru;q=0.7",
        }
        
        async def _do_req(c):
            try:
                resp = await c.get(decoded_url)
                if resp.status_code == 200:
                    final_url = str(resp.url)
                    if "consent.google" not in final_url and "consent.youtube" not in final_url:
                        return resp.text
            except Exception as ex:
                logger.debug(f"Direct article fetch failed for {decoded_url[:50]}: {ex}")

            # If direct request returned 403 / blocked / consent, retry via Cloudflare Worker
            worker = config.get_image_proxy_worker()
            if worker and not decoded_url.startswith(worker):
                try:
                    p_url = f"{worker}?url={quote_plus(decoded_url)}"
                    resp = await c.get(p_url)
                    if resp.status_code == 200:
                        return resp.text
                except Exception as ex:
                    logger.debug(f"Proxy article fetch failed for {decoded_url[:50]}: {ex}")
            return ""

        if client is not None:
            html = await _do_req(client)
        else:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as c:
                html = await _do_req(c)

        if not html or len(html) < 200:
            return ""
        
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text.strip()) > 250:
            return text.strip()
        
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        
        article = soup.find("article")
        paragraphs = article.find_all("p") if article else soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
        return text.strip() if len(text) > 250 else ""
    except Exception:
        return ""


def _title_similarity(a: str, b: str) -> float:
    """Word overlap similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / min(len(words_a), len(words_b))


def _extract_keywords(text: str) -> tuple[set[str], set[str], set[str]]:
    """Extract general, specific entity keywords, and root stems from topic text."""
    stop_words = {
        "новости", "в", "на", "и", "с", "по", "для", "о", "об", "за", "из",
        "к", "от", "до", "про", "что", "как", "это", "world", "news", "the", "in", "of", "and",
        "und", "der", "die", "das", "mit", "von", "aus", "für", "auf", "nach", "über", "im", "am", "zu"
    }
    broad_categories = {
        "политика", "россия", "россии", "внутренняя", "внешняя", "новости",
        "общество", "события", "экономика", "армия", "политики", "депутаты",
        "politik", "nachrichten", "deutschland", "gesellschaft", "wirtschaft"
    }
    words = set(re.findall(r'[а-яёa-z0-9äöüß]{3,}', text.lower()))
    all_kws = {w for w in words if w not in stop_words}
    specific_kws = {w for w in all_kws if w not in broad_categories}

    stems = set()
    for w in all_kws:
        if w.startswith("asyl"):
            stems.add("asyl")
        elif w.startswith("migrat"):
            stems.add("migrat")
        elif w.startswith("grenz"):
            stems.add("grenz")
        elif w.startswith("flücht"):
            stems.add("flücht")
        elif w.startswith("einwander"):
            stems.add("einwander")
        elif w.startswith("zuwander"):
            stems.add("zuwander")
        elif w.startswith("abschieb"):
            stems.add("abschieb")
        elif w.startswith("unterkunft") or w.startswith("unterkünf"):
            stems.add("unterkunft")
        elif w.startswith("bamf"):
            stems.add("bamf")
        elif len(w) >= 6:
            stems.add(w[:5])

    return all_kws, specific_kws, stems


async def fetch_news(topic: str, lang: str = "ru", newsapi_key: str = "", acute_angle_id: str = "") -> list[dict]:
    """
    Fetch news from targeted sources and agencies.
    Automatically expands umbrella/broad topics into acute sub-angles to guarantee variety and sharpness.
    Filters out already used articles and previous video angles.
    """
    all_kws, specific_kws, stems = _extract_keywords(topic)
    logger.info(f"Ключевые слова темы: общие={all_kws}, специфические={specific_kws}, корни={stems}")
    
    # 1. Check for chosen acute sub-angle or umbrella topic expansion
    acute_angle = pick_fresh_acute_angle(topic, explicit_id=acute_angle_id)
    
    # 2. Build search tasks: broad topic + targeted acute queries
    tasks = []
    
    if lang == "ru":
        tasks.append(search_kommersant_news(topic, count=15))
        tasks.append(search_lenta_news(topic, count=15))
        tasks.append(search_ria_news(topic, count=15))
        
        if acute_angle:
            for aq in acute_angle.get("queries", [])[:2]:
                tasks.append(search_kommersant_news(aq, count=12))
                tasks.append(search_lenta_news(aq, count=10))
                
        if specific_kws:
            specific_query = " ".join(specific_kws)
            if specific_query != topic.lower():
                tasks.append(search_kommersant_news(specific_query, count=12))
                tasks.append(search_lenta_news(specific_query, count=10))
                
        tasks.append(fetch_google_news(topic, lang=lang, max_results=30))
        tasks.append(fetch_direct_agency_feeds(lang=lang))
    else:
        # German / International
        tasks.append(search_ddg_news(topic, lang=lang, max_results=20))
        tasks.append(fetch_google_news(topic, lang=lang, max_results=30))
        tasks.append(fetch_direct_agency_feeds(lang=lang))
        
        # Search targeted acute angle queries
        if acute_angle:
            for aq in acute_angle.get("queries", [])[:2]:
                tasks.append(search_ddg_news(aq, lang=lang, max_results=15))
                tasks.append(fetch_google_news(aq, lang=lang, max_results=15))
                aq_words = [w for w in re.sub(r'[-–—:&|#?!+()«»"]', ' ', aq).split() if len(w) >= 3][:3]
                if len(aq_words) >= 2:
                    tasks.append(fetch_google_news(" ".join(aq_words), lang=lang, max_results=15))
            if acute_angle.get("title"):
                title_words = [w for w in re.sub(r'[-–—:&|#?!+()«»]', ' ', acute_angle["title"]).split() if len(w) >= 3][:3]
                tasks.append(fetch_google_news(" ".join(title_words), lang=lang, max_results=15))
                
        if specific_kws:
            specific_query = " ".join(specific_kws)
            if specific_query != topic.lower():
                tasks.append(search_ddg_news(specific_query, lang=lang, max_results=15))
                tasks.append(fetch_google_news(specific_query, lang=lang, max_results=15))
                
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    all_raw = []
    num_primary = 4 if lang == "ru" else 2
    for idx, r in enumerate(raw_results):
        if isinstance(r, list):
            for art in r:
                if idx < num_primary:
                    art["is_primary_search"] = True
            all_raw.extend(r)
            
    logger.info(f"Всего собрано сырых новостей из всех источников: {len(all_raw)}")
    
    # 3. Load history of used articles and titles
    history = load_news_history()
    used_links = set(history.get("used_links", []))
    used_titles = set(t.lower().strip() for t in history.get("used_titles", []))
    
    # 4. Deduplicate and score by topic relevance
    fresh_articles = []
    seen_in_this_batch = set()
    
    acute_queries_words = set()
    if acute_angle:
        for q in acute_angle.get("queries", []):
            acute_queries_words.update(q.lower().split())
    
    for article in all_raw:
        title = article.get("title", "").strip()
        link = article.get("link", "").strip()
        if not title:
            continue
            
        # Skip stale news (> 4.5 days) if publication date is known
        pub_str = article.get("published", "")
        if pub_str and get_article_age_days(pub_str) > 4.5:
            continue
            
        title_lower = re.sub(r'\s+', ' ', title.lower())
        
        # Intra-batch deduplication
        is_intra_dupe = False
        for s in seen_in_this_batch:
            if _title_similarity(title_lower, s) > 0.7:
                is_intra_dupe = True
                break
        if is_intra_dupe:
            continue
        seen_in_this_batch.add(title_lower)
        
        # Skip if used in previous runs (except if it matches the current user topic / primary search)
        was_used = link in used_links or any(_title_similarity(title_lower, ut) > 0.75 for ut in used_titles)
        if was_used:
            is_target_topic = article.get("is_primary_search") or (_title_similarity(title_lower, topic.lower()) > 0.5)
            if not is_target_topic:
                continue
            
        # Calculate topical relevance score
        score = 0
        art_text = (title + " " + article.get("summary", "")).lower()
        
        for kw in all_kws:
            if kw in art_text:
                score += 3
        for stem in stems:
            if stem in art_text:
                score += 3
        for skw in specific_kws:
            if skw in art_text:
                score += 8
                
        # Boost acute sub-angle matches
        if acute_queries_words:
            matched_acute = sum(1 for aw in acute_queries_words if aw in art_text)
            score += matched_acute * 5

        # Massive boost for primary search results (matching user's explicit query)
        if article.get("is_primary_search"):
            score += 50
                
        # Filter out random irrelevant agency feed articles when user chose a specific topic
        is_agency_feed = article.get("source") in [
            "Tagesschau Inland", "Tagesschau Politik", "Focus Deutschland", "Die Welt Inland",
            "FAZ Inland", "SZ Politik", "Der Spiegel Politik", "N-TV Politik", "Die Zeit", "ZDF Heute",
            "Интерфакс", "Коммерсантъ", "Ведомости", "Rambler", "Lenta.ru", "Lenta.ru (РФ)"
        ]
        if is_agency_feed and len(specific_kws) >= 2 and score < 8:
            continue

        article["relevance_score"] = score
        if acute_angle:
            article["acute_angle_id"] = acute_angle["id"]
            article["acute_angle_title"] = acute_angle["title"]
        fresh_articles.append(article)
        
    logger.info(f"Свежих (ранее не использованных) статей: {len(fresh_articles)}")

    # Fallback: if strict filtering resulted in fewer than 4 articles, relax thresholds and search core keywords
    if len(fresh_articles) < 4:
        logger.warning(f"Мало свежих статей ({len(fresh_articles)}) для '{topic}'. Запускаем автоматический fallback...")
        for article in all_raw:
            if article in fresh_articles:
                continue
            art_text = (article.get("title", "") + " " + article.get("summary", "")).lower()
            if any(kw in art_text for kw in all_kws) or any(s in art_text for s in stems) or article.get("is_primary_search"):
                article["relevance_score"] = max(article.get("relevance_score", 0), 10)
                if acute_angle:
                    article["acute_angle_id"] = acute_angle["id"]
                    article["acute_angle_title"] = acute_angle["title"]
                fresh_articles.append(article)
        
        # If still < 4, perform broad Google News search
        if len(fresh_articles) < 4:
            clean_top = re.sub(r'[-–—:&|#?!+()«»"]', ' ', topic).strip()
            words = [w for w in clean_top.split() if len(w) >= 3]
            fb_queries = []
            if words:
                fb_queries.append(" ".join(words[:3]))
                if len(words) >= 2:
                    fb_queries.append(" ".join(words[:2]))
            if acute_angle:
                for aq in acute_angle.get("queries", [])[:2]:
                    aq_w = [w for w in re.sub(r'[-–—:&|#?!+()«»"]', ' ', aq).split() if len(w) >= 3][:2]
                    if aq_w:
                        fb_queries.append(" ".join(aq_w))

            for fq in fb_queries:
                extra = await fetch_google_news(f"{fq} when:7d", lang=lang, max_results=20)
                if not extra:
                    extra = await fetch_google_news(fq, lang=lang, max_results=20)
                for ea in extra:
                    ea["relevance_score"] = 25
                    if acute_angle:
                        ea["acute_angle_id"] = acute_angle["id"]
                        ea["acute_angle_title"] = acute_angle["title"]
                    fresh_articles.append(ea)
                if len(fresh_articles) >= 6:
                    break
    
    # Sort candidates by relevance score descending
    fresh_articles.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)
    candidates_to_enrich = fresh_articles[:20]
    
    # 5. Extract full text concurrently
    sem = asyncio.Semaphore(6)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as shared_client:
        async def enrich(a):
            if a.get("full_text") and len(a["full_text"]) >= 250:
                return a
            async with sem:
                text = await extract_article_text(a["link"], title=a.get("title", ""), client=shared_client)
            if not text and a.get("title"):
                # Fallback: try direct resolution by title if url had consent or redirect
                real_url = await resolve_direct_url_by_title(a["title"])
                if real_url and real_url != a.get("link"):
                    a["link"] = real_url
                    async with sem:
                        text = await extract_article_text(real_url, title=a["title"], client=shared_client)
            if not text and a.get("summary"):
                clean_sum = BeautifulSoup(a["summary"], "html.parser").get_text(separator=" ", strip=True)
                if len(clean_sum) >= 60:
                    text = clean_sum
            a["full_text"] = text
            a["text_len"] = len(text)
            a["preview"] = (text[:300] + "...") if len(text) > 300 else text
            return a
            
        enriched = await asyncio.gather(*[enrich(a) for a in candidates_to_enrich])
    
    articles_with_text = [a for a in enriched if a.get("full_text") and len(a["full_text"]) >= 150]
    
    # Ensure primary search article is always in the result
    primary_articles = [a for a in enriched if a.get("is_primary_search")]
    for pa in primary_articles:
        if pa not in articles_with_text:
            if not pa.get("full_text"):
                pa["full_text"] = pa.get("summary") or pa.get("title", "")
                pa["text_len"] = len(pa["full_text"])
                pa["preview"] = pa["full_text"]
            articles_with_text.append(pa)

    # Strictly sort by relevance score descending so the exact matching article is #1
    articles_with_text.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)

    if articles_with_text:
        result = articles_with_text[:15]
    else:
        result = candidates_to_enrich[:15]
        for a in result:
            summary = a.get("summary", "") or a.get("title", "")
            a["full_text"] = summary
            a["text_len"] = len(summary)
            a["preview"] = summary
            
    # Record chosen articles into history
    new_used_links = [a["link"] for a in result if a.get("link")]
    new_used_titles = [a["title"] for a in result if a.get("title")]
    sub_angle_id = acute_angle["id"] if acute_angle else ""
    save_news_history(new_used_links, new_used_titles, used_sub_angle=sub_angle_id)
    
    logger.info(f"Итого отобрано для сценария {len(result)} статей с подтвержденной фактурой")
    return result


async def get_acute_topics_preview(
    topic: str = "",
    lang: str = "de",
    offset: int = 0,
    exclude_ids: list[str] = None,
    limit: int = 8,
) -> dict:
    """
    Generate an interactive list of sharp, acute, live topics of the day for UI selection.
    Strictly excludes already chosen/used topics, filters out ANY news older than 3.5 days,
    and dynamically extracts fresh stories from agency feeds or Google News when:2d/3d.
    """
    from services.translator import translate_to_ru

    cat_id, cat_info = identify_acute_cluster(topic) if topic else ("", None)
    if not cat_info:
        cat_id = "migration_de" if lang == "de" else "ru_politics"
        cat_info = ACUTE_TOPIC_CATALOG[cat_id]
        
    hist = load_news_history()
    already_used_angles = set(hist.get("used_sub_angles", []))
    all_excluded = set(already_used_angles)
    if exclude_ids:
        all_excluded.update(exclude_ids)
    
    used_history_titles = set(t.lower().strip() for t in hist.get("used_titles", []))
    MAX_AGE_DAYS = 3.5

    # 1. Fetch live headlines from premier agency feeds (Tagesschau, Focus, Welt, FAZ, Spiegel, etc.)
    live_feeds = await fetch_direct_agency_feeds(lang=lang)
    strictly_fresh_live = [
        a for a in live_feeds
        if a.get("title") and get_article_age_days(a.get("published", "")) <= MAX_AGE_DAYS
    ]

    cluster_patterns = cat_info.get("patterns", [])
    relevant_fresh_live = [
        a for a in strictly_fresh_live
        if not cluster_patterns or any(p in a.get("title", "").lower() for p in cluster_patterns)
    ]

    GENERIC_WORDS = {
        "deutschland", "berlin", "länder", "laender", "zahlen", "bundes", "reform", 
        "europa", "aktuell", "nachrichten", "politik", "heute", "immer", "mehr", "wieder",
        "россия", "москва", "новости", "сегодня", "власти", "новый", "новые",
        "polen", "italien", "griechenland", "afghanistan", "syrien", "albanien", "ruanda",
        "flug", "modell", "streit", "plan", "kosten", "krise", "debatte", "frage", "jahr"
    }

    def get_match_tokens(ang: dict) -> list[str]:
        tokens = set()
        for q in ang.get("queries", []):
            for word in re.findall(r'[a-zA-ZäöüßА-Яа-яё0-9]{4,}', q.lower()):
                if word not in GENERIC_WORDS and len(word) >= 5:
                    tokens.add(word)
        for part in ang["id"].split("_"):
            if len(part) >= 5 and part not in GENERIC_WORDS:
                tokens.add(part)
        return list(tokens)

    available_catalog = [ang for ang in cat_info["sub_angles"] if ang["id"] not in all_excluded]
    if not available_catalog:
        # All catalog angles have been used in previous runs.
        # Recycle catalog angles so the user is NEVER left with an empty screen with 0 items:
        logger.info(f"All catalog angles for '{cat_id}' are in history. Recycling catalog angles for new cycle.")
        available_catalog = list(cat_info["sub_angles"])
        all_excluded = set()

    fresh_cards_pool = []
    used_live_articles = set()

    # Match catalog sub-angles against strictly fresh news only
    catalog_matched: list[tuple[dict, list[dict]]] = []
    unmatched_catalog = []

    for ang in available_catalog:
        tokens = get_match_tokens(ang)
        matched_arts = []
        for a in relevant_fresh_live:
            t_low = a["title"].lower()
            if any(re.search(r'\b' + re.escape(tok), t_low) for tok in tokens):
                raw_sum = a.get("summary", "")
                clean_sum = re.sub(r'<[^>]+>', ' ', raw_sum).strip()
                clean_sum = re.sub(r'\s+', ' ', clean_sum)
                matched_arts.append({
                    "title": a["title"],
                    "source": a.get("source", "СМИ"),
                    "published": a.get("published", ""),
                    "pub_date": format_pub_date(a.get("published", "")),
                    "summary": clean_sum[:220],
                })
                if len(matched_arts) >= 4:
                    break
        if matched_arts:
            for m in matched_arts:
                used_live_articles.add(m["title"])
            catalog_matched.append((ang, matched_arts))
        else:
            unmatched_catalog.append(ang)

    # For unmatched catalog angles, search Google News strictly with when:3d and bounded concurrency
    if unmatched_catalog:
        sem = asyncio.Semaphore(8)
        async def _fetch_angle_fresh_news(ang: dict, client: httpx.AsyncClient) -> tuple[dict, list[dict]]:
            queries = ang.get("queries", [])
            base_q = queries[0] if queries else ang.get("title", "")
            # Use 1-2 significant words so Google News returns live breaking news with dates
            words = [w for w in re.findall(r'[a-zA-ZäöüßА-Яа-яё0-9]{4,}', base_q) if w.lower() not in {"deutschland", "aktuell", "zahlen", "politik", "berlin", "immer"}][:2]
            search_q = " ".join(words) if words else base_q.split()[0]
            full_q = f"{search_q} when:3d".strip()
            url = f"https://news.google.com/rss/search?q={quote_plus(full_q)}&hl={lang}&gl=DE&ceid=DE:{lang}"
            found_arts = []
            async with sem:
                try:
                    resp = await client.get(url, timeout=7.0)
                    if resp.status_code == 200:
                        feed = feedparser.parse(resp.text)
                        ang_tokens = get_match_tokens(ang)
                        for e in feed.entries[:8]:
                            pub = e.get("published", "")
                            if get_article_age_days(pub) <= MAX_AGE_DAYS:
                                e_title = e.get("title", "")
                                e_text = (e_title + " " + e.get("summary", "")).lower()
                                # Must match at least one specific angle token to prevent random junk/clickbait
                                if ang_tokens and not any(tok in e_text for tok in ang_tokens):
                                    continue
                                src = getattr(e, "source", None)
                                src_name = getattr(src, "title", "") if src else "Google News"
                                raw_sum = e.get("summary", "")
                                clean_sum = re.sub(r'<[^>]+>', ' ', raw_sum).strip()
                                clean_sum = re.sub(r'\s+', ' ', clean_sum)
                                found_arts.append({
                                    "title": e_title,
                                    "source": src_name,
                                    "published": pub,
                                    "pub_date": format_pub_date(pub),
                                    "summary": clean_sum[:220],
                                })
                                if len(found_arts) >= 4:
                                    break
                except Exception:
                    pass
            return ang, found_arts

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
            online_tasks = [_fetch_angle_fresh_news(ang, client) for ang in unmatched_catalog]
            online_results = await asyncio.gather(*online_tasks, return_exceptions=True)
            for res in online_results:
                if isinstance(res, tuple) and res[1]:
                    catalog_matched.append(res)

    # Build map of matched live headlines
    matched_map = {ang["id"]: arts for ang, arts in catalog_matched}

    # 1. First add catalog angles with confirmed live news attached (highest freshness)
    for ang in available_catalog:
        if ang["id"] in matched_map:
            arts = matched_map[ang["id"]]
            primary_art = arts[0] if arts else {}
            main_q = ang["queries"][0]
            hook_choice = random.choice(ang.get("hook_ideas", ["AKTUELLES EREIGNIS"]))
            hook_choice_ru = ang.get("hook_ideas_ru", {}).get(hook_choice, "")

            fresh_cards_pool.append({
                "id": ang["id"],
                "title": ang["title"],
                "title_ru": ang.get("title_ru", ""),
                "desc_ru": ang.get("desc_ru", ""),
                "badge": ang["badge"],
                "topic_query": main_q,
                "hook_sample": hook_choice,
                "hook_sample_ru": hook_choice_ru,
                "live_headline": primary_art.get("title", ""),
                "live_headline_ru": "",
                "live_source": primary_art.get("source", "Агентство"),
                "live_pub_date": primary_art.get("pub_date", ""),
                "live_summary": primary_art.get("summary", ""),
                "live_articles": arts,
                "is_recent": False,
                "is_live_dynamic": False,
            })

    # 2. Add remaining catalog angles (guarantees catalog topics are NEVER lost even if Google blocks RSS!)
    for ang in available_catalog:
        if ang["id"] not in matched_map:
            main_q = ang["queries"][0]
            hook_choice = random.choice(ang.get("hook_ideas", ["AKTUELLES EREIGNIS"]))
            hook_choice_ru = ang.get("hook_ideas_ru", {}).get(hook_choice, "")

            fresh_cards_pool.append({
                "id": ang["id"],
                "title": ang["title"],
                "title_ru": ang.get("title_ru", ""),
                "desc_ru": ang.get("desc_ru", ""),
                "badge": ang["badge"],
                "topic_query": main_q,
                "hook_sample": hook_choice,
                "hook_sample_ru": hook_choice_ru,
                "live_headline": "",
                "live_headline_ru": "",
                "live_source": "",
                "live_pub_date": "",
                "live_summary": "",
                "live_articles": [],
                "is_recent": False,
                "is_live_dynamic": False,
            })

    # Presets for punchy clickbait hooks on dynamic live cards
    HOOK_PRESETS = [
        ("AKTUELLE ENTWICKLUNG", "СРОЧНЫЕ ДЕТАЛИ"),
        ("NEUE ENTHÜLLUNG", "НОВЫЕ ПОДРОБНОСТИ"),
        ("ENTSCHEIDUNG GEFALLEN", "РЕШЕНИЕ ПРИНЯТО"),
        ("GROSSER WENDEPUNKT", "РЕЗКИЙ ПОВОРОТ"),
        ("DAS VERSTECKTE DETAIL", "СКРЫТАЯ ДЕТАЛЬ"),
        ("DRINGENDE WARNUNG", "ТРЕВОЖНЫЙ СИГНАЛ"),
        ("OFFIZIELLE ZAHLEN", "ОФИЦИАЛЬНЫЕ ЦИФРЫ"),
        ("SKANDAL-DEBATTE", "ОСТРЫЙ СПОР"),
    ]

    # Add dynamic fresh cards from relevant_fresh_live
    for art in relevant_fresh_live:
        art_title = art.get("title", "").strip()
        if not art_title or art_title in used_live_articles:
            continue
        t_low = art_title.lower()
        if any(_title_similarity(t_low, ut) > 0.7 for ut in used_history_titles):
            continue

        used_live_articles.add(art_title)
        slug = re.sub(r'[^a-zA-Z0-9]', '_', art_title)[:24].strip('_').lower()
        dynamic_id = f"live_{slug}_{abs(hash(art_title)) % 100000}"
        if dynamic_id in all_excluded:
            continue

        hk_de, hk_ru = random.choice(HOOK_PRESETS)
        pub_date_str = format_pub_date(art.get("published", ""))
        raw_sum = art.get("summary", "")
        clean_sum = re.sub(r'<[^>]+>', ' ', raw_sum).strip()
        clean_sum = re.sub(r'\s+', ' ', clean_sum)
        fresh_cards_pool.append({
            "id": dynamic_id,
            "title": art_title,
            "title_ru": "",
            "desc_ru": clean_sum[:220],
            "badge": f"🔥 {art.get('source', 'СМИ')}",
            "topic_query": art_title,
            "hook_sample": hk_de,
            "hook_sample_ru": hk_ru,
            "live_headline": art_title,
            "live_headline_ru": "",
            "live_source": art.get("source", "СМИ"),
            "live_pub_date": pub_date_str,
            "live_summary": clean_sum[:220],
            "live_articles": [{
                "title": art_title,
                "source": art.get("source", "СМИ"),
                "published": art.get("published", ""),
                "pub_date": pub_date_str,
                "summary": clean_sum[:220],
            }],
            "is_recent": False,
            "is_live_dynamic": True,
        })

    # If pool is still smaller than offset + limit, pull directly from Google News when:2d
    if len(fresh_cards_pool) < (offset + limit + 2):
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(headers=headers, timeout=6) as client:
            search_terms = [topic, cat_info.get("name", "")] if topic else [cat_info.get("name", "")]
            for term in search_terms:
                if len(fresh_cards_pool) >= (offset + limit + 6):
                    break
                for t_filter in ["when:2d", "when:3d"]:
                    url = f"https://news.google.com/rss/search?q={quote_plus(f'{term} {t_filter}')}&hl={lang}&gl=DE&ceid=DE:{lang}"
                    try:
                        r = await client.get(url)
                        if r.status_code == 200:
                            f = feedparser.parse(r.text)
                            for e in f.entries:
                                e_title = e.get("title", "").strip()
                                if not e_title or e_title in used_live_articles:
                                    continue
                                e_pub = e.get("published", "")
                                if get_article_age_days(e_pub) > MAX_AGE_DAYS:
                                    continue
                                used_live_articles.add(e_title)
                                src_name = getattr(getattr(e, "source", None), "title", "Google News") or "Google News"
                                slug = re.sub(r'[^a-zA-Z0-9]', '_', e_title)[:24].strip('_').lower()
                                dynamic_id = f"live_{slug}_{abs(hash(e_title)) % 100000}"
                                if dynamic_id in all_excluded:
                                    continue
                                hk_de, hk_ru = random.choice(HOOK_PRESETS)
                                raw_sum = e.get("summary", "")
                                clean_sum = re.sub(r'<[^>]+>', ' ', raw_sum).strip()
                                clean_sum = re.sub(r'\s+', ' ', clean_sum)
                                pub_str = format_pub_date(e_pub)
                                fresh_cards_pool.append({
                                    "id": dynamic_id,
                                    "title": e_title,
                                    "title_ru": "",
                                    "desc_ru": clean_sum[:220],
                                    "badge": f"🔥 {src_name}",
                                    "topic_query": e_title,
                                    "hook_sample": hk_de,
                                    "hook_sample_ru": hk_ru,
                                    "live_headline": e_title,
                                    "live_headline_ru": "",
                                    "live_source": src_name,
                                    "live_pub_date": pub_str,
                                    "live_summary": clean_sum[:220],
                                    "live_articles": [{
                                        "title": e_title,
                                        "source": src_name,
                                        "published": e_pub,
                                        "pub_date": pub_str,
                                        "summary": clean_sum[:220],
                                    }],
                                    "is_recent": False,
                                    "is_live_dynamic": True,
                                })
                    except Exception:
                        pass

    # Slice the pool by offset and limit
    sliced_cards = fresh_cards_pool[offset : offset + limit] if offset < len(fresh_cards_pool) else []

    # Concurrently translate any missing Russian titles, descriptions, hooks, or live headlines
    async def translate_card(card: dict):
        if not card["title_ru"]:
            card["title_ru"] = await asyncio.to_thread(translate_to_ru, card["title"])
        for art in card.get("live_articles", []):
            if not art.get("title_ru") and art.get("title"):
                art["title_ru"] = await asyncio.to_thread(translate_to_ru, art["title"])
        if not card["desc_ru"] and card.get("is_live_dynamic"):
            card["desc_ru"] = f"Свежая публикация ({card['live_source']}): оперативные данные и детали."
        elif card["desc_ru"] and card.get("is_live_dynamic"):
            card["desc_ru"] = await asyncio.to_thread(translate_to_ru, card["desc_ru"])
        if not card["hook_sample_ru"] and card["hook_sample"]:
            card["hook_sample_ru"] = await asyncio.to_thread(translate_to_ru, card["hook_sample"])
        if card["live_headline"] and not card.get("live_headline_ru"):
            first_art = card.get("live_articles", [{}])[0]
            card["live_headline_ru"] = first_art.get("title_ru") or await asyncio.to_thread(translate_to_ru, card["live_headline"])
        return card

    enriched_cards = await asyncio.gather(*[translate_card(c) for c in sliced_cards])

    has_more = len(fresh_cards_pool) > (offset + limit)
    return {
        "topics": enriched_cards,
        "total_catalog": max(len(cat_info["sub_angles"]), len(fresh_cards_pool)),
        "fresh_catalog_count": len(fresh_cards_pool),
        "offset": offset,
        "has_more": has_more,
    }


